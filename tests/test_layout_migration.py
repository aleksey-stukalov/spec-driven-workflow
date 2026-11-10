"""Observable safety and preservation contracts for the package-directory rename."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess

import pytest
import yaml

from test_installer import adopt, distribution, files, legacy_configuration, target, workflow


LEGACY = "_agentic_harness"


def legacy_installation(source, target, *, version=2, root="."):
    """Keep the old ownership document consistent with a renamed fixture payload."""
    (target / root).mkdir(parents=True, exist_ok=True)
    scopes = [root]
    if root != ".":
        (target / "tests/backend").mkdir(parents=True)
        scopes.append("tests/backend")
    adopt(source, target, project="stable_backend", spec_root=root, scopes=scopes,
          checks=[["make", "verify-backend"]], agents=["codex", "claude"])
    expected = workflow.load_registry(target)
    if version == 1:
        legacy_configuration(target)
    current = target / workflow.HARNESS
    previous = target / LEGACY
    current.rename(previous)
    manifest_path = previous / "install.json"
    manifest = json.loads(manifest_path.read_text())
    prefix = workflow.HARNESS + "/"
    manifest["managed"] = {
        LEGACY + "/" + name[len(prefix):] if name.startswith(prefix) else name: value
        for name, value in manifest["managed"].items()
    }
    manifest["payload_sha256"] = workflow.digest(workflow.encoded({
        name: value for name, value in manifest["managed"].items()
        if name.startswith(LEGACY + "/")
    }))
    manifest_path.write_bytes(workflow.encoded(manifest))
    return expected


@pytest.mark.parametrize("version", [1, 2], ids=["inline-settings", "companion-settings"])
@pytest.mark.parametrize("root", [".", "services/backend"], ids=["repository", "component"])
def test_legacy_directory_upgrade_preserves_configuration_and_is_repeatable(
    distribution, target, version, root,
):
    source, calls = distribution
    expected = legacy_installation(source, target, version=version, root=root)
    native = target / workflow.join(root, "openspec/config.yaml")
    native.write_text("# Existing product context\nschema: spec-driven\ncontext: Keep this text.\n")
    product = target / workflow.join(root, "openspec/specs/payments/spec.md")
    product.parent.mkdir(parents=True)
    product.write_text("# Existing payment rules\n")
    settings = target / workflow.join(root, "openspec/workflow.yaml")
    if settings.exists():
        settings.write_text("# Human-maintained formatting\n" + settings.read_text())
    (target / ".codex").mkdir(exist_ok=True)
    (target / ".codex/config.toml").write_text('model = "project-choice"\n')
    (target / "AGENTS.md").write_text("# Local policy\n\n" + (target / "AGENTS.md").read_text())
    preserved = {
        path: path.read_bytes() for path in (
            native, product, target / ".codex/config.toml",
            target / workflow.join(root, ".agents/skills/openspec-propose/SKILL.md"),
        )
    }
    if settings.exists():
        preserved[settings] = settings.read_bytes()

    assert workflow.doctor(target)["status"] == "valid"
    assert workflow.load_registry(target) == expected
    before = files(target)
    before_calls = list(calls)
    preview = workflow.installation(target, source=source, update=True, dry_run=True)
    assert workflow.MANIFEST in preview["changed"]
    assert workflow.REGISTRY in preview["changed"]
    assert LEGACY + "/install.json" in preview["removed"]
    assert LEGACY + "/projects.yaml" in preview["removed"]
    assert files(target) == before
    assert calls == before_calls

    result = workflow.installation(target, source=source, update=True)
    assert result["projects"] == ["stable_backend"]
    assert workflow.load_registry(target) == expected
    assert workflow.doctor(target)["status"] == "valid"
    assert not (target / LEGACY / "install.json").exists()
    assert not (target / LEGACY / "projects.yaml").exists()
    assert (target / workflow.HARNESS / "policies/example.md").is_file()
    assert not (target / LEGACY / "policies/example.md").exists()
    assert {path: path.read_bytes() for path in preserved} == preserved
    assert (target / "AGENTS.md").read_text().startswith("# Local policy\n")

    after = files(target)
    repeat = workflow.installation(target, source=source, update=True)
    assert repeat["changed"] == repeat["removed"] == []
    assert not repeat["install_toolchain"]
    assert files(target) == after


def test_legacy_unowned_files_and_dependency_caches_keep_bytes_and_ignore_rules(distribution, target):
    source, _ = distribution
    legacy_installation(source, target)
    old = target / LEGACY
    for relative in ("notes/operator.txt", ".venv/config", "__pycache__/local.pyc"):
        path = old / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Local data that the package does not own.\n")
    preserved = {path: path.read_bytes() for path in (
        old / "notes/operator.txt", old / ".venv/config", old / "__pycache__/local.pyc",
        old / "node_modules/@fission-ai/openspec/package.json", old / ".gitignore",
    )}
    workflow.installation(target, source=source, update=True)
    assert {path: path.read_bytes() for path in preserved} == preserved
    for path in ("node_modules/@fission-ai/openspec/package.json", ".venv/config", "__pycache__/local.pyc"):
        ignored = subprocess.run(["git", "check-ignore", "-q", LEGACY + "/" + path], cwd=target)
        assert ignored.returncode == 0
    manifest = workflow.load_manifest(target)
    assert not any(name.startswith(LEGACY + "/") for name in manifest["managed"])


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("existing_destination", [False, True])
def test_successful_migration_preserves_permissions_before_publishing_files(
    distribution, target, monkeypatch, version, existing_destination,
):
    source, _ = distribution
    legacy_installation(source, target, version=version)
    old = target / LEGACY
    current = target / workflow.HARNESS
    modes = {"tools/example.md": 0o750, "install.json": 0o600,
             "projects.yaml": 0o600, ".gitignore": 0o600}
    for name, mode in modes.items():
        (old / name).chmod(mode)
    old.chmod(0o700)
    (old / "tools").chmod(0o700)
    root_mode = tools_mode = 0o700
    if existing_destination:
        (current / "tools").mkdir(parents=True)
        current.chmod(0o751)
        (current / "tools").chmod(0o755)
        root_mode, tools_mode = 0o751, 0o755
        (current / "tools/example.md").write_bytes((source / workflow.HARNESS / "tools/example.md").read_bytes())
        (current / "tools/example.md").chmod(0o640)
        modes["tools/example.md"] = 0o640

    # This file has no legacy owner; it keeps the ordinary new-file mode.
    (source / workflow.HARNESS / "tools/new.md").write_text("New package guidance.\n")
    replace = workflow.os.replace
    published = set()

    def inspect_publication(temporary, destination):
        destination = Path(destination)
        if destination.is_relative_to(current):
            name = destination.relative_to(current).as_posix()
            assert current.stat().st_mode & 0o7777 == root_mode
            if name.startswith("tools/"):
                assert (current / "tools").stat().st_mode & 0o7777 == tools_mode
            if name in modes:
                assert Path(temporary).stat().st_mode & 0o7777 == modes[name]
                published.add(name)
        return replace(temporary, destination)

    monkeypatch.setattr(workflow.os, "replace", inspect_publication)
    workflow.installation(target, source=source, update=True)
    for name, mode in modes.items():
        assert (current / name).stat().st_mode & 0o7777 == mode
    assert {"install.json", "projects.yaml", ".gitignore"} <= published
    if not existing_destination:
        assert "tools/example.md" in published
    assert (current / "tools/new.md").stat().st_mode & 0o7777 == 0o644
    assert old.stat().st_mode & 0o7777 == 0o700
    assert (old / ".gitignore").stat().st_mode & 0o7777 == 0o600
    assert workflow.doctor(target)["status"] == "valid"


@pytest.mark.parametrize("collision", ["manifest", "index", "dependencies", "payload"])
def test_existing_canonical_content_cannot_be_overwritten_during_migration(distribution, target, collision):
    source, calls = distribution
    legacy_installation(source, target)
    name = {
        "manifest": "install.json", "index": "projects.yaml",
        "dependencies": "node_modules/unowned.txt", "payload": "policies/example.md",
    }[collision]
    path = target / workflow.HARNESS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if collision == "manifest":
        path.write_bytes((target / LEGACY / name).read_bytes())
    elif collision == "index":
        path.write_bytes((target / LEGACY / name).read_bytes())
    else:
        path.write_text("Unowned destination content.\n")
    before, before_calls = files(target), list(calls)
    with pytest.raises(workflow.InstallError):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before
    assert calls == before_calls


def test_edited_legacy_owned_file_stops_before_migration(distribution, target):
    source, calls = distribution
    legacy_installation(source, target)
    (target / LEGACY / "policies/example.md").write_text("Local policy edits.\n")
    before, before_calls = files(target), list(calls)
    with pytest.raises(workflow.InstallError, match="locally changed"):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before
    assert calls == before_calls


@pytest.mark.parametrize("alias", ["legacy-root", "canonical-root"])
def test_migration_rejects_symlinked_package_roots(distribution, target, tmp_path, alias):
    source, calls = distribution
    legacy_installation(source, target)
    old = target / LEGACY
    outside = tmp_path / "outside-package"
    if alias == "legacy-root":
        old.rename(outside)
        old.symlink_to(outside, target_is_directory=True)
    else:
        outside.mkdir()
        (target / workflow.HARNESS).symlink_to(old, target_is_directory=True)
    before, outside_before, before_calls = files(target), files(outside), list(calls)
    with pytest.raises(workflow.InstallError, match="symlink"):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before
    assert files(outside) == outside_before
    assert calls == before_calls


@pytest.mark.parametrize("layout", ["current", "legacy"])
def test_manifest_cannot_claim_files_in_the_other_layout(distribution, target, layout):
    source, calls = distribution
    if layout == "legacy":
        legacy_installation(source, target)
        own, other = LEGACY, workflow.HARNESS
    else:
        adopt(source, target)
        own, other = workflow.HARNESS, LEGACY
    unowned = target / other / "policies/private.md"
    unowned.parent.mkdir(parents=True)
    unowned.write_text("Local policy that this installation does not own.\n")
    manifest_path = target / own / "install.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["managed"][other + "/policies/private.md"] = workflow.digest(unowned.read_bytes())
    manifest_path.write_bytes(workflow.encoded(manifest))
    before, before_calls = files(target), list(calls)
    with pytest.raises(workflow.InstallError, match="manifest claims"):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before
    assert calls == before_calls


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("mode", [0o750, 0o600])
def test_final_manifest_failure_restores_legacy_owned_files_and_configuration(
    distribution, target, monkeypatch, version, mode,
):
    source, _ = distribution
    legacy_installation(source, target, version=version)
    (target / "_agentic_harness/tools/example.md").chmod(mode)
    (target / "_agentic_harness/install.json").chmod(mode)
    (target / "AGENTS.md").chmod(mode)
    # Also exercise a rewritten existing file, not just legacy removals.
    adapter = source / "tools/adapters.py"
    adapter.write_text(adapter.read_text().replace("Workflow domains:", "Updated workflow domains:"))
    before = files(target)
    before_modes = {name: (target / name).stat().st_mode & 0o7777 for name in before}
    original_write = workflow.atomic_write

    def fail_final_manifest(path, content, **kwargs):
        if path == target / workflow.MANIFEST:
            raise OSError("new manifest unavailable")
        return original_write(path, content, **kwargs)

    monkeypatch.setattr(workflow, "atomic_write", fail_final_manifest)
    with pytest.raises(OSError, match="new manifest unavailable"):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before
    assert {name: (target / name).stat().st_mode & 0o7777 for name in before} == before_modes
    assert not list(target.rglob(".sdw-write-*"))
    assert not list(target.rglob(".sdw-deps-*"))
    assert workflow.doctor(target)["status"] == "valid"


@pytest.mark.parametrize("changed", [
    "_agentic_harness/projects.yaml", "_agentic_harness/install.json",
    "agentic_harness/projects.yaml", "agentic_harness/install.json",
])
def test_concurrent_layout_authority_edit_survives_without_partial_migration(
    distribution, target, monkeypatch, changed,
):
    source, _ = distribution
    legacy_installation(source, target)
    original_prepare = workflow.prepare_dependencies
    before = files(target)
    path = target / changed
    edited = (path.read_bytes() + b"\n") if path.exists() else b"{}\n"

    def concurrent_edit(*args):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(edited)
        return original_prepare(*args)

    monkeypatch.setattr(workflow, "prepare_dependencies", concurrent_edit)
    with pytest.raises(workflow.InstallError, match="target changed while preparing"):
        workflow.installation(target, source=source, update=True)
    before[changed] = edited
    assert files(target) == before


@pytest.mark.parametrize("setting", ["code-root", "tool-scope", "lockfile", "check", "prepare"])
def test_migration_preserves_and_rejects_local_settings_that_reference_moved_paths(
    distribution, target, setting,
):
    source, calls = distribution
    legacy_installation(source, target)
    companion = target / "openspec/workflow.yaml"
    configuration = yaml.safe_load(companion.read_text())
    if setting in {"code-root", "tool-scope"}:
        configuration["code_roots"] = [LEGACY if setting == "code-root" else LEGACY + "/tools"]
    elif setting == "lockfile":
        configuration["environment"]["lockfiles"] = [LEGACY + "/package-lock.json"]
    elif setting == "check":
        configuration["checks"] = [["uv", "run", "--project=" + LEGACY, "python", LEGACY + "/tools/harness.py", "project"]]
    else:
        configuration["environment"]["prepare"] = [["npm", "--prefix", LEGACY, "ci"]]
    companion.write_text("# Local path must be resolved deliberately\n" + yaml.safe_dump(configuration))
    before, before_calls = files(target), list(calls)
    with pytest.raises(workflow.InstallError):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before
    assert calls == before_calls


def test_legacy_evidence_exclusion_is_preserved_when_unowned_content_remains(distribution, target):
    source, _ = distribution
    legacy_installation(source, target)
    private = target / LEGACY / "private/local.txt"
    private.parent.mkdir()
    private.write_bytes(b"Local evidence exclusion remains authoritative.\n")
    companion = target / "openspec/workflow.yaml"
    configuration = yaml.safe_load(companion.read_text())
    configuration["evidence_exclude"] = [LEGACY + "/private"]
    companion.write_text(yaml.safe_dump(configuration))
    before = companion.read_bytes()
    workflow.installation(target, source=source, update=True)
    assert companion.read_bytes() == before
    assert private.read_bytes() == b"Local evidence exclusion remains authoritative.\n"
    assert workflow.load_registry(target)["projects"]["stable_backend"]["evidence_exclude"] == [LEGACY + "/private"]


def test_active_legacy_worktree_is_not_migrated(distribution, target):
    source, calls = distribution
    legacy_installation(source, target)
    database = target / ".git/agentic-harness/coordination.sqlite3"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE records(kind TEXT,key TEXT,data TEXT,PRIMARY KEY(kind,key))")
        claim = {"id": "stable_backend:change", "worktree": str(target), "state": "running"}
        connection.execute("INSERT INTO records VALUES (?,?,?)", ("claim", claim["id"], json.dumps(claim)))
    before, before_calls = files(target), list(calls)
    with pytest.raises(workflow.InstallError, match="active workflow claim"):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before
    assert calls == before_calls


@pytest.mark.parametrize("relative", ["tools/example.md", "tools", "."])
def test_concurrent_permission_change_stops_migration_without_overwriting_it(
    distribution, target, monkeypatch, relative,
):
    source, _ = distribution
    legacy_installation(source, target)
    owned = target / LEGACY / relative
    owned.chmod(0o750)
    changed_mode = 0o700 if owned.is_dir() else 0o600
    before = files(target)
    prepare = workflow.prepare_dependencies

    def chmod_during_preparation(*args):
        owned.chmod(changed_mode)
        return prepare(*args)

    monkeypatch.setattr(workflow, "prepare_dependencies", chmod_during_preparation)
    with pytest.raises(workflow.InstallError, match="target changed while preparing"):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before
    assert owned.stat().st_mode & 0o7777 == changed_mode
    assert not (target / workflow.HARNESS).exists()
