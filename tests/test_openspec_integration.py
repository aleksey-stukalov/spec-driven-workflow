"""Exercise the published, pinned OpenSpec rather than emulating its output."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "_agentic_harness"
LAUNCHER = HARNESS / "tools/openspec.mjs"
UPSTREAM = HARNESS / "node_modules/@fission-ai/openspec/bin/openspec.js"
WORKFLOWS = {
    "openspec-propose",
    "openspec-explore",
    "openspec-apply-change",
    "openspec-update-change",
    "openspec-sync-specs",
    "openspec-archive-change",
}


@pytest.fixture
def cli_env(tmp_path):
    """Use child-only user directories; leave the developer's settings alone."""
    if not shutil.which("node") or not UPSTREAM.is_file():
        pytest.skip("Run npm ci --ignore-scripts --prefix _agentic_harness for OpenSpec integration tests")
    environment = os.environ.copy()
    for name, folder in (
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("CODEX_HOME", "codex"),
    ):
        path = tmp_path / "user" / folder
        path.mkdir(parents=True)
        environment[name] = str(path)
    environment.update(
        OPENSPEC_TELEMETRY="0",
        DO_NOT_TRACK="1",
        OPENSPEC_NO_ANIMATION="1",
        OPENSPEC_NO_AUTO_CONFIG="1",
        CI="1",
    )
    config = Path(environment["XDG_CONFIG_HOME"]) / "openspec/config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"profile": "core", "delivery": "skills"}) + "\n")
    return environment


def run_cli(directory, environment, *arguments, launcher=LAUNCHER):
    result = subprocess.run(
        [shutil.which("node"), str(launcher), *map(str, arguments)],
        cwd=directory,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def upstream_files(project):
    files = {}
    for provider in (".agents", ".claude"):
        skills = project / provider / "skills"
        if skills.exists():
            for entry in skills.iterdir():
                if entry.name.startswith("openspec-"):
                    for file in entry.rglob("*"):
                        if file.is_file():
                            files[file.relative_to(project).as_posix()] = file.read_bytes()
        marker = skills / ".openspec-target"
        if marker.is_file():
            files[marker.relative_to(project).as_posix()] = marker.read_bytes()
    return files


def write(project, relative, content):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_published_version_matches_the_exact_toolchain_pin(tmp_path, cli_env):
    package = json.loads((HARNESS / "package.json").read_text())
    lock = json.loads((HARNESS / "package-lock.json").read_text())
    assert package["dependencies"]["@fission-ai/openspec"] == "1.14.3"
    assert lock["packages"]["node_modules/@fission-ai/openspec"]["version"] == "1.14.3"
    assert run_cli(tmp_path, cli_env, "--version").stdout.strip() == "1.14.3"


def test_upstream_generation_and_update_preserve_local_content(tmp_path, cli_env):
    pristine = tmp_path / "pristine"
    project = tmp_path / "repository/services/api"
    pristine.mkdir()
    project.mkdir(parents=True)
    # Generate the reference directly with the published CLI, bypassing our launcher.
    run_cli(pristine, cli_env, "init", "--tools", "codex,claude", "--profile", "core", launcher=UPSTREAM)
    baseline = upstream_files(pristine)
    assert {Path(name).parts[2] for name in baseline if name.endswith("SKILL.md")} == WORKFLOWS
    assert len(baseline) == 13
    # The distribution itself must not carry patches under upstream names.
    assert upstream_files(ROOT) == baseline

    preserved = {
        "openspec/config.yaml": (
            "schema: spec-driven\ncontext: |\n  This API belongs to the product team.\n"
            "rules:\n  proposal:\n    - Describe compatibility for existing API clients.\n"
        ),
        "openspec/specs/payments/spec.md": "# Payments\n\nProduct-owned specification.\n",
        "openspec/changes/existing-change/notes.md": "Keep this in-progress design.\n",
        "openspec/workflow.yaml": (
            "# Application-owned workflow settings\nschema_version: 1\n"
            "code_roots: [services/api, tests/api]\nchecks: [[npm, test]]\n"
        ),
        ".agents/skills/sdw-project/SKILL.md": "Workflow-owned routing instructions.\n",
        ".claude/skills/sdw-project/SKILL.md": "Workflow-owned routing instructions.\n",
        ".agents/skills/product-helper/SKILL.md": "Local product skill.\n",
        "AGENTS.md": "Product-owned agent instructions.\n",
        "CLAUDE.md": "Product-owned Claude instructions.\n",
    }
    for name, content in preserved.items():
        write(project, name, content)
    run_cli(project, cli_env, "init", "--tools", "codex,claude", "--profile", "core")
    assert upstream_files(project) == baseline
    run_cli(project, cli_env, "update", "--force")
    assert upstream_files(project) == baseline
    for name, content in preserved.items():
        assert (project / name).read_text() == content, name
    assert not (project / ".claude/commands").exists()


def test_launcher_uses_the_callers_selected_project_root(tmp_path, cli_env):
    repository = tmp_path / "repository"
    project = repository / "services/api"
    deep = project / "src/handlers"
    deep.mkdir(parents=True)
    write(repository, "openspec/config.yaml", "schema: spec-driven\ncontext: Root project.\n")
    write(project, "openspec/config.yaml", "schema: spec-driven\ncontext: API project.\n")
    # Upstream root resolution starts at the caller's cwd, not the helper's location.
    context = json.loads(run_cli(deep, cli_env, "context", "--json").stdout)
    assert Path(context["root"]["path"]).resolve() == project.resolve()
    run_cli(deep, cli_env, "new", "change", "add-api-behavior")
    assert (project / "openspec/changes/add-api-behavior/.openspec.yaml").is_file()
    assert not (repository / "openspec/changes").exists()
    assert not (HARNESS / "openspec/changes/add-api-behavior").exists()


def test_installed_workflow_survives_upstream_update(tmp_path, cli_env, monkeypatch):
    import workflow

    target = tmp_path / "consumer"
    target.mkdir()
    subprocess.run(["git", "init", str(target)], check=True, capture_output=True)
    config = write(target, "openspec/config.yaml", "schema: spec-driven\ncontext: Existing product conventions.\n")
    product_spec = write(target, "openspec/specs/payments/spec.md", "# Existing payments specification\n")
    write(target, "AGENTS.md", "# Local instructions\n\nPreserve the product's conventions.\n")
    # Simulate a developer's explicit global Codex directory. Staged init must
    # not discover or clean legacy OpenSpec prompts in this separate directory.
    developer_codex = tmp_path / "developer-codex"
    global_prompt = write(developer_codex, "prompts/opsx-apply.md", "Developer-owned legacy prompt.\n")
    monkeypatch.setenv("CODEX_HOME", str(developer_codex))
    config_bytes, spec_bytes = config.read_bytes(), product_spec.read_bytes()
    result = workflow.installation(
        target,
        spec_root=".",
        scopes=["."],
        checks=[["python", "-c", "print('application check')"]],
        agents=["codex", "claude"],
        source=ROOT,
    )
    assert result["status"] == "installed"
    local_settings = target / "openspec/workflow.yaml"
    settings_bytes = local_settings.read_bytes()
    assert global_prompt.read_text() == "Developer-owned legacy prompt.\n"
    upstream_before = upstream_files(target)
    manifest = json.loads((target / "_agentic_harness/install.json").read_text())
    managed_before = {name: (target / name).read_bytes() for name in manifest["managed"]}
    assert any("/skills/sdw-" in name for name in managed_before)

    pristine = tmp_path / "reference"
    pristine.mkdir()
    run_cli(pristine, cli_env, "init", "--tools", "codex,claude", "--profile", "core", launcher=UPSTREAM)
    assert upstream_before == upstream_files(pristine)
    run_cli(target, cli_env, "update", "--force", launcher=target / "_agentic_harness/tools/openspec.mjs")
    assert upstream_files(target) == upstream_before
    assert {name: (target / name).read_bytes() for name in managed_before} == managed_before
    assert config.read_bytes() == config_bytes
    assert product_spec.read_bytes() == spec_bytes
    assert local_settings.read_bytes() == settings_bytes
    assert (target / "AGENTS.md").read_text().startswith("# Local instructions\n\nPreserve the product's conventions.\n")
    assert workflow.doctor(target)["status"] == "valid"


def test_folder_installation_uses_native_directory_discovery_without_a_name(tmp_path, cli_env):
    import workflow

    target = tmp_path / "consumer"
    project = target / "services/api"
    source = project / "src/handlers"
    source.mkdir(parents=True)
    (target / "tests/api").mkdir(parents=True)
    subprocess.run(["git", "init", str(target)], check=True, capture_output=True)
    result = workflow.installation(
        target, spec_root="services/api", scopes=["services/api", "tests/api"],
        checks=[["npm", "--prefix", "services/api", "test"]], agents=["codex"], source=ROOT,
    )
    assert result["status"] == "installed"
    assert not (target / "openspec").exists()
    companion = project / "openspec/workflow.yaml"
    assert companion.is_file()
    launcher = target / "_agentic_harness/tools/openspec.mjs"
    context = json.loads(run_cli(source, cli_env, "context", "--json", launcher=launcher).stdout)
    assert Path(context["root"]["path"]).resolve() == project.resolve()
    run_cli(source, cli_env, "new", "change", "describe-api-behavior", launcher=launcher)
    assert (project / "openspec/changes/describe-api-behavior/.openspec.yaml").is_file()
    assert workflow.installation(target, spec_root="services/api", source=ROOT)["changed"] == []
    assert workflow.doctor(target)["status"] == "valid"
