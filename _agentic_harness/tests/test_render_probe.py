"""Exercise browser-only rendering failures against temporary handbook copies."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

import check_render as render


HARNESS = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def browser_executable() -> str:
    try:
        return render.find_browser()
    except render.GraphValidationError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def handbook_copy(tmp_path: Path):
    source = HARNESS / "index.html"
    original = source.read_bytes()
    page = tmp_path / "handbook.html"
    page.write_bytes(original)
    yield page, HARNESS / "handbook.yaml"
    assert source.read_bytes() == original


@pytest.mark.parametrize("dark", [False, True], ids=["default-theme", "dark-theme"])
def test_generated_graph_is_readable_at_desktop_and_mobile_widths(
    handbook_copy: tuple[Path, Path], browser_executable: str, dark: bool,
) -> None:
    page, handbook = handbook_copy
    results = render.validate_html(page, handbook, browser_executable, dark=dark)
    assert [(item["width"], item["nodeCount"], item["edgeCount"]) for item in results] == [
        (1440, 21, 30), (390, 21, 30),
    ]
    assert all(not item["errors"] for item in results)
    if dark:
        assert all(item["colorScheme"] == "dark" for item in results)


@pytest.mark.parametrize(
    "rule,width,diagnostic",
    [
        (".diagram marker path{fill:transparent!important}", 1440, "arrow marker target is empty"),
        (".diagram .node-title{font-size:250px!important}", 1440, "node label extends outside its box"),
        ("body{width:1800px!important}", 390, "page overflows horizontally"),
    ],
    ids=["invisible-arrow", "overflowing-label", "mobile-page-overflow"],
)
def test_render_probe_rejects_graph_and_page_regressions(
    handbook_copy: tuple[Path, Path], browser_executable: str,
    rule: str, width: int, diagnostic: str,
) -> None:
    page, handbook = handbook_copy
    source = page.read_text()
    assert "</head>" in source
    page.write_text(source.replace("</head>", f"<style>{rule}</style></head>", 1))
    mutated = page.read_bytes()
    with pytest.raises(render.GraphValidationError, match=diagnostic):
        render.validate_html(page, handbook, browser_executable, widths=(width,))
    assert page.read_bytes() == mutated


@pytest.mark.parametrize("failure", ["browser-exit", "timeout", "viewport-mismatch"])
def test_browser_failures_are_reported_and_temporary_profile_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    page = tmp_path / "handbook.html"
    page.write_text("<!doctype html><html><body></body></html>")
    handbook = tmp_path / "handbook.yaml"
    handbook.write_text(yaml.safe_dump({"graph": {"nodes": [], "edges": []}}))
    original = page.read_bytes()
    profiles = []

    def run_browser(command: list[str], **kwargs):
        profile = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--user-data-dir=")))
        profiles.append(profile)
        assert profile.parent.is_dir()
        assert "--disable-background-networking" in command
        assert "--host-resolver-rules=MAP * ~NOTFOUND" in command
        assert kwargs["timeout"] == 30
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if failure == "browser-exit":
            return subprocess.CompletedProcess(command, 7, "", "synthetic browser failure")
        result = {"width": 500, "nodeCount": 0, "edgeCount": 0, "errors": []}
        return subprocess.CompletedProcess(command, 0, f"<pre>{render.RESULT_MARKER}{json.dumps(result)}</pre>", "")

    monkeypatch.setattr(render, "RUN_SUBPROCESS", run_browser)
    diagnostic = {
        "browser-exit": "headless browser failed at 390px.*synthetic browser failure",
        "timeout": "headless browser timed out at 390px",
        "viewport-mismatch": "browser viewport mismatch: requested 390px, rendered 500px",
    }[failure]
    with pytest.raises(render.GraphValidationError, match=diagnostic):
        render.validate_html(page, handbook, sys.executable, widths=(390,))
    assert page.read_bytes() == original
    assert len(profiles) == 1 and not profiles[0].parent.exists()
