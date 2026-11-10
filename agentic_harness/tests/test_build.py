"""Offline regression tests for the portable, presentation-only handbook build."""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import pytest
import yaml


HARNESS = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location(
        "sdw_handbook_build_regressions", HARNESS / "tools/build.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness(tmp_path: Path) -> Path:
    """Use only the shipped harness, with no files from the source project."""
    destination = tmp_path / "consumer" / "agentic_harness"
    shutil.copytree(
        HARNESS,
        destination,
        ignore=shutil.ignore_patterns("node_modules", ".venv", "__pycache__", ".git", "tests"),
    )
    return destination


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def selected_markdown(harness: Path) -> Path:
    return harness / read_yaml(harness / "handbook.yaml")["sections"][0]["path"]


def generated_html(build, harness: Path) -> str:
    outputs = build.expected_outputs(harness)
    assert set(outputs) == {harness / "index.html"}
    return outputs[harness / "index.html"]


def materialize(build, harness: Path) -> str:
    content = generated_html(build, harness)
    (harness / "index.html").write_text(content)
    return content


def snapshot(root: Path, *, exclude: set[Path] | None = None) -> dict:
    """Record bytes and timestamps to detect even same-content rewrites."""
    return {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file() and path not in (exclude or set())
    }


def run_builder(harness: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(harness / "tools/build.py"), *arguments],
        cwd=harness.parent,
        capture_output=True,
        text=True,
        check=False,
    )


class HTMLInventory(HTMLParser):
    def __init__(self, content: str):
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.links: list[str] = []
        self.assets: list[str] = []
        self.tags: Counter = Counter()
        self.text: list[str] = []
        self.rows: list[str] = []
        self._row: list[str] | None = None
        self.feed(content)

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = dict(attributes)
        self.tags[tag] += 1
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"script", "img", "iframe", "audio", "video", "source", "embed"}:
            if attrs.get("src"):
                self.assets.append(attrs["src"])
        if tag in {"link", "use", "image"}:
            for name in ("href", "xlink:href"):
                if attrs.get(name):
                    self.assets.append(attrs[name])
        if tag == "object" and attrs.get("data"):
            self.assets.append(attrs["data"])
        if tag == "tr":
            self._row = []

    def handle_startendtag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attributes)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._row is not None:
            self.rows.append(" ".join(" ".join(self._row).split()))
            self._row = None

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._row is not None:
            self._row.append(data)


def test_checked_in_page_is_current_and_only_declared_output(build) -> None:
    assert generated_html(build, HARNESS) == (HARNESS / "index.html").read_text()


def test_same_package_at_different_checkout_paths_has_identical_output(build, harness: Path, tmp_path: Path) -> None:
    second = tmp_path / "another" / "deeply nested checkout" / "agentic_harness"
    shutil.copytree(harness, second)
    first_html = generated_html(build, harness)
    assert first_html == generated_html(build, second)
    assert str(harness) not in first_html
    assert str(HARNESS) not in first_html


@pytest.mark.parametrize("state", ["missing", "stale", "current"])
def test_check_is_read_only_for_every_output_state(build, harness: Path, state: str) -> None:
    output = harness / "index.html"
    materialize(build, harness)
    if state == "missing":
        output.unlink()
    elif state == "stale":
        output.write_text("stale handbook\n")
    before = snapshot(harness.parent)
    result = run_builder(harness, "--check")
    assert (result.returncode == 0) is (state == "current"), result.stdout + result.stderr
    assert snapshot(harness.parent) == before
    if state != "current":
        assert "index.html" in result.stdout + result.stderr


def test_source_markdown_drift_is_detected_without_writes(build, harness: Path) -> None:
    previous = materialize(build, harness)
    source = selected_markdown(harness)
    source.write_text(source.read_text() + "\nHandbook source drift regression probe.\n")
    updated = generated_html(build, harness)
    assert "Handbook source drift regression probe." in " ".join(HTMLInventory(updated).text)
    assert updated != previous
    before = snapshot(harness.parent)
    result = run_builder(harness, "--check")
    assert result.returncode != 0
    assert snapshot(harness.parent) == before


@pytest.mark.parametrize("relative,suffix", [
    ("handbook.yaml", "\n# Handbook metadata drift probe\n"),
    ("templates/graph-layout.yaml", "\n# Graph layout drift probe\n"),
    ("templates/handbook.css", "\n/* Stylesheet drift probe */\n"),
    ("templates/diagram-frame.svg", "\n<!-- Diagram frame drift probe -->\n"),
    ("tools/build.py", "\n# Generator source drift probe\n"),
])
def test_presentation_inputs_participate_in_freshness(build, harness: Path, relative: str, suffix: str) -> None:
    previous = materialize(build, harness)
    source = harness / relative
    source.write_text(source.read_text() + suffix)
    assert generated_html(build, harness) != previous
    before = snapshot(harness.parent)
    result = run_builder(harness, "--check")
    assert result.returncode != 0
    assert snapshot(harness.parent) == before


def test_catalog_labels_and_limits_are_rendered_from_current_data(build, harness: Path) -> None:
    previous = materialize(build, harness)
    path = harness / "plans.yaml"
    catalog = read_yaml(path)
    probe = "Catalog lookup regression probe"
    next(step for step in catalog["steps"] if step["id"] == "lookup")["label"] = probe
    rule = catalog["plans"]["budget"]["steps"]["lookup"]
    rule["maximum"] = 17
    rule["routes"]["codex"] = {"model": "gpt-6-astra", "effort": "xhigh"}
    rule["routes"]["claude"] = {"model": "claude-opus-5-5", "effort": "xhigh"}
    write_yaml(path, catalog)
    updated = generated_html(build, harness)
    rows = [row for row in HTMLInventory(updated).rows if probe in row]
    assert rows, "The role label must be visible in a catalog-derived table"
    assert any(re.search(r"\b17\b", row) for row in rows), rows
    assert any("astra" in row.lower() and "opus" in row.lower() and "xhigh" in row for row in rows), rows
    assert updated != previous
    assert run_builder(harness, "--check").returncode != 0


def test_invalid_catalog_is_rejected_before_output(build, harness: Path) -> None:
    path = harness / "plans.yaml"
    catalog = read_yaml(path)
    catalog["plans"]["budget"]["steps"]["lookup"]["maximum"] = -1
    write_yaml(path, catalog)
    before = snapshot(harness.parent)
    with pytest.raises(ValueError):
        build.expected_outputs(harness)
    assert snapshot(harness.parent) == before


def test_rebuild_changes_only_html_and_is_repeatable(build, harness: Path) -> None:
    sentinels = {
        ".codex/config.toml": 'model = "consumer-default"\n',
        ".claude/settings.json": '{"model": "consumer-default"}\n',
        ".agents/skills/openspec-apply-change/SKILL.md": "# Upstream skill sentinel\n",
        "openspec/config.yaml": "schema: spec-driven\n",
        "README.md": "# Consumer instructions\n",
    }
    for relative, content in sentinels.items():
        destination = harness.parent / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    output = harness / "index.html"
    output.write_text("stale handbook\n")
    before = snapshot(harness.parent, exclude={output})
    expected = generated_html(build, harness)
    result = run_builder(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_text() == expected
    assert snapshot(harness.parent, exclude={output}) == before
    first_bytes = output.read_bytes()
    result = run_builder(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_bytes() == first_bytes
    assert snapshot(harness.parent, exclude={output}) == before


def test_invalid_graph_endpoint_is_rejected(build, harness: Path) -> None:
    path = harness / "handbook.yaml"
    config = read_yaml(path)
    config["graph"]["edges"][0]["to"] = "nonexistent-node"
    write_yaml(path, config)
    with pytest.raises(ValueError):
        build.expected_outputs(harness)


def test_graph_rejects_bypass_even_with_matching_layout(build, harness: Path) -> None:
    path = harness / "handbook.yaml"
    config = read_yaml(path)
    config["graph"]["edges"].append({
        "id": "test-bypass", "from": "queue", "to": "pr-ready",
        "kind": "forward", "condition": "skip gates", "caption": [],
    })
    write_yaml(path, config)
    layout_path = harness / "templates/graph-layout.yaml"
    layout = read_yaml(layout_path)
    layout["edges"]["test-bypass"] = {"path": "M400 160V1079", "caption_positions": []}
    write_yaml(layout_path, layout)
    with pytest.raises(ValueError):
        build.expected_outputs(harness)


@pytest.mark.parametrize("edge", [
    ("design-gate", "design-fix"),
    ("design-fix", "spec-contract-review"),
    ("code-gate", "code-fix"),
    ("code-fix", "runtime-review"),
    ("pr-ready", "human-review"),
    ("human-review", "merge-authorization"),
])
def test_required_gate_and_repair_edges_cannot_disappear(build, harness: Path, edge: tuple[str, str]) -> None:
    path = harness / "handbook.yaml"
    config = read_yaml(path)
    removed = next(item for item in config["graph"]["edges"] if (item["from"], item["to"]) == edge)
    config["graph"]["edges"].remove(removed)
    write_yaml(path, config)
    layout_path = harness / "templates/graph-layout.yaml"
    layout = read_yaml(layout_path)
    del layout["edges"][removed["id"]]
    write_yaml(layout_path, layout)
    with pytest.raises(ValueError):
        build.expected_outputs(harness)


@pytest.mark.parametrize("href", ["missing-handbook-link.md", "#missing-handbook-fragment"])
def test_broken_local_links_fail_without_replacing_html(build, harness: Path, href: str) -> None:
    materialize(build, harness)
    source = selected_markdown(harness)
    source.write_text(source.read_text() + f"\n[Broken regression probe]({href})\n")
    before = snapshot(harness.parent)
    with pytest.raises(ValueError):
        build.expected_outputs(harness)
    result = run_builder(harness)
    assert result.returncode != 0
    assert snapshot(harness.parent) == before


def test_html_is_offline_and_all_inline_anchors_resolve(build, harness: Path) -> None:
    content = generated_html(build, harness)
    html = HTMLInventory(content)
    assert html.tags["h1"] == 1
    assert html.tags["svg"] >= 1
    assert html.tags["style"] >= 1
    assert html.tags["script"] == 0
    assert len(html.ids) == len(set(html.ids)), "Duplicate IDs make handbook links ambiguous"
    assert html.links
    for link in html.links:
        url = urlsplit(link)
        if not url.scheme and not url.netloc and not url.path and url.fragment:
            assert unquote(url.fragment) in html.ids, link
    css_assets = re.findall(r"url\(\s*['\"]?([^)'\"\s]+)", content)
    assert all(asset.startswith(("#", "data:")) for asset in html.assets + css_assets)
    assert not re.search(r"@import\s", content, flags=re.IGNORECASE)


def test_markdown_and_graph_labels_are_escaped(build, harness: Path) -> None:
    source = selected_markdown(harness)
    source.write_text(source.read_text() + '\n<script>alert("markdown probe")</script>\n')
    path = harness / "handbook.yaml"
    config = read_yaml(path)
    config["graph"]["nodes"][0]["label"] = '<script>alert("graph probe")</script>'
    write_yaml(path, config)
    content = generated_html(build, harness)
    assert HTMLInventory(content).tags["script"] == 0
    assert "&lt;script&gt;" in content
    assert "markdown probe" in content
    assert "graph probe" in content
