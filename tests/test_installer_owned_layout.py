"""Typed discovery and all-home authority migration acceptance checks."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
import yaml

from test_installer import adopt, distribution, legacy_configuration, target, workflow


def tree(root):
    """Include empty directories, literal links and portable permissions."""
    result = {}
    def walk(directory):
        for path in directory.iterdir():
            name = path.relative_to(root).as_posix()
            if name == ".git":
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                result[name] = ("link", os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                result[name] = ("directory", stat.S_IMODE(info.st_mode))
                walk(path)
            else:
                result[name] = ("file", stat.S_IMODE(info.st_mode), path.read_bytes())
    walk(root)
    return result


def test_fresh_layout_uses_canonical_skills_and_only_selected_links(distribution, target):
    source, _ = distribution
    adopt(source, target, agents=["codex"])
    manifest = workflow.load_manifest(target)
    assert manifest["schema_version"] == 2
    assert manifest["links"] == {name: {"kind": "directory_symlink", "target": literal}
                                 for name, literal in workflow.discovery_links(["codex"]).items()}
    for name, literal in workflow.discovery_links(["codex"]).items():
        assert (target / name).is_symlink()
        assert os.readlink(target / name) == literal
        assert (target / name / "SKILL.md").read_bytes() == (source / "agentic_harness/skills" / Path(name).name / "SKILL.md").read_bytes()
    assert not (target / ".claude").exists()
    assert "agentic_harness/config/workflow.yaml" not in manifest["managed"]
    assert not (target / "openspec/queue.yaml").exists()
    assert yaml.safe_load((target / workflow.REGISTRY).read_text())["schema_version"] == 3
    before = tree(target)
    result = workflow.installation(target, source=source, update=True, dry_run=True)
    assert result["changed"] == [] and result["links"] == {}
    assert tree(target) == before


@pytest.mark.parametrize("conflict", ["extra-file", "extra-empty-directory", "edited-child", "unowned-directory", "unowned-link", "wrong-link"])
def test_only_verified_sole_owned_skill_child_can_be_converted(distribution, target, conflict):
    source, calls = distribution
    adopt(source, target)
    legacy_configuration(target, version=2)
    name = ".agents/skills/sdw-run"
    leaf = target / name
    if conflict == "extra-file":
        (leaf / "local.txt").write_text("local")
    elif conflict == "extra-empty-directory":
        (leaf / "empty").mkdir()
    elif conflict == "edited-child":
        (leaf / "SKILL.md").write_text("edited")
    elif conflict == "unowned-directory":
        manifest_path = target / workflow.MANIFEST
        manifest = json.loads(manifest_path.read_text())
        del manifest["managed"][name + "/SKILL.md"]
        manifest_path.write_bytes(workflow.encoded(manifest))
    else:
        (leaf / "SKILL.md").unlink()
        leaf.rmdir()
        leaf.symlink_to(workflow.expected_target(name) if conflict == "unowned-link" else "../../elsewhere")
    before, preparations = tree(target), list(calls)
    with pytest.raises(workflow.InstallError):
        workflow.installation(target, source=source, update=True)
    assert tree(target) == before and calls == preparations


def test_migration_preserves_settings_map_bytes_modes_and_directory_mode_on_rollback(distribution, target, monkeypatch):
    source, _ = distribution
    adopt(source, target)
    legacy_configuration(target, version=2)
    for name in ("openspec/workflow.yaml", "openspec/queue.yaml", ".agents/skills/sdw-run/SKILL.md"):
        path = target / name
        path.write_bytes(b"# Preserved human comment\n" + path.read_bytes())
        path.chmod(0o600)
    # The old installer owns and verifies its copied skill's exact recorded bytes.
    manifest_path = target / workflow.MANIFEST
    manifest = json.loads(manifest_path.read_text())
    skill = ".agents/skills/sdw-run/SKILL.md"
    manifest["managed"][skill] = workflow.digest((target / skill).read_bytes())
    manifest_path.write_bytes(workflow.encoded(manifest))
    (target / ".agents/skills/sdw-run").chmod(0o700)
    before = tree(target)
    preview = workflow.installation(target, source=source, update=True, dry_run=True)
    assert ".agents/skills/sdw-run" in preview["conversions"]
    assert preview["links"][".agents/skills/sdw-run"] == "../../agentic_harness/skills/sdw-run"
    assert tree(target) == before
    original = workflow.atomic_write
    def fail_manifest(path, content, **kwargs):
        if path == target / workflow.MANIFEST:
            raise OSError("manifest unavailable")
        return original(path, content, **kwargs)
    monkeypatch.setattr(workflow, "atomic_write", fail_manifest)
    with pytest.raises(OSError, match="manifest unavailable"):
        workflow.installation(target, source=source, update=True)
    assert tree(target) == before
    monkeypatch.setattr(workflow, "atomic_write", original)
    workflow.installation(target, source=source, update=True)
    for old, new in (("openspec/workflow.yaml", "agentic_harness/config/workflow.yaml"), ("openspec/queue.yaml", "openspec/dependency-map.yaml")):
        assert not (target / old).exists()
        assert (target / new).read_bytes() == before[old][2]
        assert stat.S_IMODE((target / new).stat().st_mode) == 0o600


@pytest.mark.parametrize("kind", ["settings", "map"])
def test_equivalent_duplicates_coalesce_only_during_explicit_migration(distribution, target, kind):
    source, _ = distribution
    adopt(source, target)
    legacy_configuration(target, version=2)
    old, new = (("openspec/workflow.yaml", "agentic_harness/config/workflow.yaml") if kind == "settings"
                else ("openspec/queue.yaml", "openspec/dependency-map.yaml"))
    destination = target / new
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = b"# Destination format wins\n" + (target / old).read_bytes()
    destination.write_bytes(content)
    destination.chmod(0o640)
    before = tree(target)
    with pytest.raises(workflow.InstallError):
        workflow.doctor(target)
    assert tree(target) == before
    workflow.installation(target, source=source, update=True)
    assert not (target / old).exists()
    assert destination.read_bytes() == content
    assert stat.S_IMODE(destination.stat().st_mode) == 0o640


@pytest.mark.parametrize("kind", ["settings", "map"])
def test_missing_indexed_authority_never_uses_an_alternate(distribution, target, kind):
    source, calls = distribution
    adopt(source, target)
    legacy_configuration(target, version=2)
    old, new = (("openspec/workflow.yaml", "agentic_harness/config/workflow.yaml") if kind == "settings"
                else ("openspec/queue.yaml", "openspec/dependency-map.yaml"))
    destination = target / new
    destination.parent.mkdir(parents=True, exist_ok=True)
    (target / old).rename(destination)
    before, preparations = tree(target), list(calls)
    with pytest.raises(workflow.InstallError, match="missing"):
        workflow.installation(target, source=source, checks=[["fallback"]])
    assert tree(target) == before and calls == preparations


def test_failed_install_preserves_concurrent_poststate_and_reports_recovery(distribution, target, monkeypatch):
    source, _ = distribution
    adopt(source, target)
    changed = "agentic_harness/policies/example.md"
    (source / changed).write_text("new package policy")
    original = workflow.atomic_write
    def fail_manifest(path, content, **kwargs):
        if path == target / workflow.MANIFEST:
            (target / changed).write_text("concurrent human policy")
            raise OSError("manifest unavailable")
        return original(path, content, **kwargs)
    monkeypatch.setattr(workflow, "atomic_write", fail_manifest)
    with pytest.raises(workflow.InstallError, match="recovery required:.*policies/example.md"):
        workflow.installation(target, source=source, update=True)
    assert (target / changed).read_text() == "concurrent human policy"


def test_multiple_registered_homes_migrate_in_one_transaction(distribution, target, monkeypatch):
    source, _ = distribution
    for root in ("services/api", "web/site"):
        (target / root).mkdir(parents=True)
        adopt(source, target, project=root.rsplit("/", 1)[1], spec_root=root, scopes=[root])
    legacy_configuration(target, version=2)
    before = tree(target)
    original = workflow.atomic_write
    def fail_second(path, content, **kwargs):
        if path == target / workflow.workflow_name("web/site"):
            raise OSError("second settings unavailable")
        return original(path, content, **kwargs)
    monkeypatch.setattr(workflow, "atomic_write", fail_second)
    with pytest.raises(OSError, match="second settings"):
        workflow.installation(target, source=source, update=True)
    assert tree(target) == before
    monkeypatch.setattr(workflow, "atomic_write", original)
    workflow.installation(target, source=source, update=True)
    assert set(yaml.safe_load((target / workflow.REGISTRY).read_text())["projects"]) == {"api", "site"}
    for root in ("services/api", "web/site"):
        assert (target / workflow.workflow_name(root)).is_file()
        assert (target / root / "openspec/dependency-map.yaml").is_file()
        assert not (target / root / "openspec/workflow.yaml").exists()


def test_removing_a_provider_unlinks_only_owned_discovery_leaves(distribution, target):
    source, _ = distribution
    adopt(source, target)
    local = target / ".claude/skills/product-helper/SKILL.md"
    local.parent.mkdir(parents=True)
    local.write_text("product skill")
    adopt(source, target, agents=["codex"])
    assert local.read_text() == "product skill"
    for name in workflow.discovery_links(["claude"]):
        assert not (target / name).is_symlink()
        assert not (target / name).exists()
    assert (target / "agentic_harness/skills/sdw-run/SKILL.md").is_file()


@pytest.mark.parametrize("invalid", ["unknown-kind", "wrong-target", "extra-field", "unselected-provider", "missing-map", "managed-overlap"])
def test_manifest_links_are_exact_typed_selected_records(distribution, target, invalid):
    source, _ = distribution
    adopt(source, target, agents=["codex"])
    path = target / workflow.MANIFEST
    manifest = json.loads(path.read_text())
    name = ".agents/skills/sdw-run"
    if invalid == "unknown-kind":
        manifest["links"][name]["kind"] = "file_symlink"
    elif invalid == "wrong-target":
        manifest["links"][name]["target"] = "../../outside"
    elif invalid == "extra-field":
        manifest["links"][name]["extra"] = "x"
    elif invalid == "unselected-provider":
        manifest["links"][".claude/skills/sdw-run"] = dict(manifest["links"][name])
    elif invalid == "missing-map":
        del manifest["links"]
    else:
        manifest["managed"][name + "/SKILL.md"] = workflow.digest(b"x")
    path.write_bytes(workflow.encoded(manifest))
    with pytest.raises(workflow.InstallError, match="link"):
        workflow.load_manifest(target)


@pytest.mark.parametrize("kind", ["settings", "map"])
def test_aliases_in_consumer_migration_authorities_are_rejected(distribution, target, kind):
    source, calls = distribution
    adopt(source, target)
    legacy_configuration(target, version=2)
    path = target / ("openspec/workflow.yaml" if kind == "settings" else "openspec/queue.yaml")
    if kind == "settings":
        path.write_text("schema_version: 1\ncode_roots: &roots ['.']\nchecks: [[npm, test]]\nevidence_exclude: *roots\n")
    else:
        path.write_text("queue: &entries []\n")
    before, preparations = tree(target), list(calls)
    with pytest.raises(workflow.InstallError, match="aliases"):
        workflow.installation(target, source=source, update=True)
    assert tree(target) == before and calls == preparations


def test_dependency_rollback_preserves_concurrent_poststate(distribution, target, monkeypatch):
    source, _ = distribution
    adopt(source, target)
    (source / "agentic_harness/package-lock.json").write_text("changed package lock")
    path = target / "agentic_harness/node_modules/operator.txt"
    original = workflow.atomic_write
    def fail_manifest(destination, content, **kwargs):
        if destination == target / workflow.MANIFEST:
            path.write_text("concurrent dependency-tree edit")
            raise OSError("manifest unavailable")
        return original(destination, content, **kwargs)
    monkeypatch.setattr(workflow, "atomic_write", fail_manifest)
    with pytest.raises(workflow.InstallError, match="recovery required:.*node_modules"):
        workflow.installation(target, source=source, update=True)
    assert path.read_text() == "concurrent dependency-tree edit"
    assert list((target / "agentic_harness").glob(".sdw-old-deps-*"))


def test_parent_swap_cannot_redirect_atomic_writes(distribution, target, tmp_path, monkeypatch):
    source, _ = distribution
    adopt(source, target)
    source_policy = source / "agentic_harness/policies/example.md"
    source_policy.write_text("new package policy")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "example.md").write_text("outside content")
    parent = target / "agentic_harness/policies"
    detached = target / "agentic_harness/detached-policies"
    original = workflow.atomic_write
    swapped = False
    def swap_parent(path, content, **kwargs):
        nonlocal swapped
        if path == parent / "example.md" and not swapped:
            parent.rename(detached)
            parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original(path, content, **kwargs)
    monkeypatch.setattr(workflow, "atomic_write", swap_parent)
    with pytest.raises(workflow.InstallError, match="recovery required"):
        workflow.installation(target, source=source, update=True)
    assert (outside / "example.md").read_text() == "outside content"
    assert parent.is_symlink()


def test_legacy_provider_removal_can_be_reselected_without_unowned_empty_leaves(distribution, target):
    source, _ = distribution
    adopt(source, target)
    legacy_configuration(target, version=2)
    adopt(source, target, agents=["codex"])
    for name in workflow.discovery_links(["claude"]):
        assert not (target / name).exists()
    adopt(source, target, agents=["codex", "claude"])
    assert all((target / name).is_symlink() for name in workflow.discovery_links(["claude"]))


def test_unsupported_discovery_link_creation_restores_the_complete_legacy_tree(distribution, target, monkeypatch):
    source, _ = distribution
    adopt(source, target)
    legacy_configuration(target, version=2)
    before = tree(target)
    def unsupported(*args, **kwargs):
        raise OSError("filesystem does not support symlinks")
    monkeypatch.setattr(workflow.os, "symlink", unsupported)
    with pytest.raises(OSError, match="does not support symlinks"):
        workflow.installation(target, source=source, update=True)
    assert tree(target) == before


@pytest.mark.parametrize("existing", [False, True])
def test_staged_file_publication_preserves_concurrent_destination(distribution, target, monkeypatch, existing):
    source, _ = distribution
    adopt(source, target)
    name = "agentic_harness/policies/example.md" if existing else "agentic_harness/policies/added.md"
    (source / name).write_text("replacement package policy")
    original_write, original_fsync = workflow.atomic_write, workflow.os.fsync
    staging = False
    edited = False
    def scoped_write(path, content, **kwargs):
        nonlocal staging
        staging = path == target / name
        try:
            return original_write(path, content, **kwargs)
        finally:
            staging = False
    def edit_after_fsync(fd):
        nonlocal edited
        original_fsync(fd)
        if staging and not edited:
            (target / name).write_text("concurrent human policy")
            edited = True
    monkeypatch.setattr(workflow, "atomic_write", scoped_write)
    monkeypatch.setattr(workflow.os, "fsync", edit_after_fsync)
    with pytest.raises(workflow.InstallError, match="recovery required:.*" + name):
        workflow.installation(target, source=source, update=True)
    assert edited and (target / name).read_text() == "concurrent human policy"
    assert not list(target.rglob(".sdw-write-*"))
    assert not workflow._WRITE_HANDLES and not workflow._WRITE_GUARDS


def test_staged_link_publication_preserves_concurrent_destination(distribution, target, monkeypatch):
    source, _ = distribution
    adopt(source, target)
    legacy_configuration(target, version=2)
    name = ".agents/skills/sdw-run"
    original = workflow.os.symlink
    edited = False
    def stage_then_create(literal, leaf, **kwargs):
        nonlocal edited
        result = original(literal, leaf, **kwargs)
        if str(leaf).startswith(".sdw-link-") and not edited:
            (target / name).write_text("concurrent discovery entry")
            edited = True
        return result
    monkeypatch.setattr(workflow.os, "symlink", stage_then_create)
    with pytest.raises(workflow.InstallError, match="recovery required:.*sdw-run"):
        workflow.installation(target, source=source, update=True)
    assert edited and (target / name).read_text() == "concurrent discovery entry"
    assert not list(target.rglob(".sdw-link-*"))


@pytest.mark.parametrize("replacement", ["real-parent", "symlink-parent", "leaf"])
def test_rollback_rechecks_pinned_parent_and_leaf(distribution, target, tmp_path, monkeypatch, replacement):
    source, _ = distribution
    adopt(source, target)
    name = "agentic_harness/policies/example.md"
    (source / name).write_text("new package policy")
    original_write, original_observe = workflow.atomic_write, workflow.observe
    rollback = False
    swapped = False
    def fail_manifest(path, content, **kwargs):
        nonlocal rollback
        if path == target / workflow.MANIFEST:
            rollback = True
            raise OSError("manifest unavailable")
        return original_write(path, content, **kwargs)
    def swap_after_observation(root, relative):
        nonlocal swapped
        state = original_observe(root, relative)
        if rollback and relative == name and not swapped:
            path = target / name
            if replacement == "leaf":
                path.unlink()
            else:
                parent = path.parent
                parent.rename(parent.with_name("detached-policies"))
                if replacement == "real-parent":
                    parent.mkdir()
                else:
                    outside = tmp_path / "outside"
                    outside.mkdir()
                    parent.symlink_to(outside, target_is_directory=True)
            path.write_text("concurrent replacement policy")
            swapped = True
        return state
    monkeypatch.setattr(workflow, "atomic_write", fail_manifest)
    monkeypatch.setattr(workflow, "observe", swap_after_observation)
    with pytest.raises(workflow.InstallError, match="recovery required:.*" + name):
        workflow.installation(target, source=source, update=True)
    assert swapped and (target / name).read_text() == "concurrent replacement policy"


def test_staged_rollback_restoration_preserves_concurrent_edit(distribution, target, monkeypatch):
    source, _ = distribution
    adopt(source, target)
    name = "agentic_harness/policies/example.md"
    (source / name).write_text("new package policy")
    original_write, original_fsync = workflow.atomic_write, workflow.os.fsync
    rollback = False
    edited = False
    def fail_manifest(path, content, **kwargs):
        nonlocal rollback
        if path == target / workflow.MANIFEST:
            rollback = True
            raise OSError("manifest unavailable")
        return original_write(path, content, **kwargs)
    def edit_during_restore(fd):
        nonlocal edited
        original_fsync(fd)
        if rollback and not edited:
            (target / name).write_text("concurrent rollback edit")
            edited = True
    monkeypatch.setattr(workflow, "atomic_write", fail_manifest)
    monkeypatch.setattr(workflow.os, "fsync", edit_during_restore)
    with pytest.raises(workflow.InstallError, match="recovery required:.*" + name):
        workflow.installation(target, source=source, update=True)
    assert edited and (target / name).read_text() == "concurrent rollback edit"
    assert not list(target.rglob(".sdw-write-*"))


@pytest.mark.parametrize("skill", ["sdw-run", "sdw-harden", "sdw-review"])
def test_current_canonical_skill_bindings_survive_unchanged_maintenance(distribution, target, skill):
    source, _ = distribution
    command = ["test", "-f", f"agentic_harness/skills/{skill}/SKILL.md"]
    adopt(source, target, checks=[command])
    settings = target / "agentic_harness/config/workflow.yaml"
    data = yaml.safe_load(settings.read_text())
    data["environment"]["prepare"] = [command]
    settings.write_text(yaml.safe_dump(data))
    workflow.installation(target, source=source, update=True)
    before = tree(target)
    for options in ({"update": True, "dry_run": True}, {"update": True}, {"project": "app"}):
        result = workflow.installation(target, source=source, **options)
        assert result["changed"] == [] and result["links"] == {}
        assert tree(target) == before


@pytest.mark.parametrize("home", [".", "services/api"])
@pytest.mark.parametrize("version", [2, 3])
def test_configuration_conflict_names_schema_selected_settings(distribution, target, home, version):
    source, _ = distribution
    (target / home).mkdir(parents=True, exist_ok=True)
    adopt(source, target, spec_root=home)
    if version == 2:
        legacy_configuration(target, version=2)
    authority = workflow.workflow_name(home, version)
    with pytest.raises(workflow.InstallError, match=authority):
        adopt(source, target, spec_root=home, checks=[["different-check"]])
    with pytest.raises(workflow.InstallError, match=authority):
        adopt(source, target, spec_root=home, checks=[])


@pytest.mark.parametrize("home", [".", "services/api"])
def test_fresh_missing_checks_names_harness_destination(distribution, target, home):
    source, _ = distribution
    with pytest.raises(workflow.InstallError, match=workflow.workflow_name(home)):
        workflow.installation(target, source=source, spec_root=home)


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("home", [".", "services/api"])
def test_index_shape_guidance_names_actual_schema_and_settings(distribution, target, home, version):
    source, _ = distribution
    (target / home).mkdir(parents=True, exist_ok=True)
    adopt(source, target, spec_root=home)
    if version == 2:
        legacy_configuration(target, version=2)
    index = target / workflow.REGISTRY
    data = yaml.safe_load(index.read_text())
    data["projects"]["app"]["checks"] = [["true"]]
    index.write_text(yaml.safe_dump(data))
    with pytest.raises(workflow.InstallError) as error:
        workflow.load_registry(target)
    assert f"version {version}" in str(error.value)
    assert workflow.workflow_name(home, version) in str(error.value)


@pytest.mark.parametrize("home", [".", "services/api"])
@pytest.mark.parametrize("field,value,cause", [
    ("checks", [], "project requires concrete validation commands"),
    ("code_roots", [], "invalid source scope"),
    ("environment", {"prepare": "not argv"}, "invalid environment prepare"),
    ("evidence_exclude", "not paths", "invalid configuration paths"),
    ("environment", "not mapping", "environment supports lockfiles and prepare lists"),
    ("checks", ["npm test"], "a check must be a nonempty JSON argv array"),
    ("environment", {"prepare": ["npm install"]}, "a check must be a nonempty JSON argv array"),
    ("code_roots", ["../outside"], "unsafe repository-relative path: '../outside'"),
    ("environment", {"lockfiles": ["../outside.lock"]}, "unsafe repository-relative path: '../outside.lock'"),
    ("evidence_exclude", ["../outside"], "unsafe repository-relative path: '../outside'"),
])
def test_doctor_semantic_settings_errors_retain_authority_and_cause(distribution, target, home, field, value, cause):
    source, _ = distribution
    (target / home).mkdir(parents=True, exist_ok=True)
    adopt(source, target, spec_root=home)
    relative = workflow.workflow_name(home)
    path = target / relative
    settings = yaml.safe_load(path.read_text())
    settings[field] = value
    path.write_text(yaml.safe_dump(settings))
    with pytest.raises(workflow.InstallError) as error:
        workflow.doctor(target)
    assert type(error.value) is workflow.InstallError
    assert relative in str(error.value) and cause in str(error.value)
    assert isinstance(error.value.__cause__, workflow.InstallError)
    assert cause in str(error.value.__cause__)


@pytest.mark.parametrize("home", [".", "services/api"])
@pytest.mark.parametrize("payload,cause", [
    (b"checks: [\n", "invalid YAML"),
    (b"checks: []\nchecks: []\n", "configuration has a non-string or duplicate key"),
    (b"\xff\xfe", "invalid YAML"),
])
def test_doctor_decoding_errors_name_settings_and_retain_chain(distribution, target, home, payload, cause):
    source, _ = distribution
    (target / home).mkdir(parents=True, exist_ok=True)
    adopt(source, target, spec_root=home)
    relative = workflow.workflow_name(home)
    (target / relative).write_bytes(payload)
    with pytest.raises(workflow.InstallError) as error:
        workflow.doctor(target)
    assert relative in str(error.value) and cause in str(error.value)
    assert isinstance(error.value.__cause__, workflow.InstallError)


@pytest.mark.parametrize("home", [".", "services/api"])
@pytest.mark.parametrize("version", [1, 2])
def test_legacy_companion_validation_names_legacy_file(distribution, target, home, version):
    source, _ = distribution
    (target / home).mkdir(parents=True, exist_ok=True)
    adopt(source, target, spec_root=home)
    legacy_configuration(target, version=version)
    relative = workflow.workflow_name(home, 2)
    # Schema 1 permits an optional companion agreeing with the inline settings.
    if version == 1:
        index = yaml.safe_load((target / workflow.REGISTRY).read_text())
        settings = workflow.workflow_settings(index["projects"]["app"])
    else:
        settings = yaml.safe_load((target / relative).read_text())
    settings.update(schema_version=1, checks=["npm test"])
    (target / relative).write_text(yaml.safe_dump(settings))
    with pytest.raises(workflow.InstallError) as error:
        workflow.doctor(target)
    assert relative in str(error.value) and "a check must be a nonempty JSON argv array" in str(error.value)
    assert workflow.workflow_name(home) not in str(error.value)


@pytest.mark.parametrize("home", [".", "services/api"])
@pytest.mark.parametrize("kind", ["environment", "duplicate-key"])
def test_public_project_and_doctor_cli_keep_settings_context(distribution, target, home, kind):
    import shutil
    import subprocess
    import sys
    source, _ = distribution
    (target / home).mkdir(parents=True, exist_ok=True)
    adopt(source, target, spec_root=home)
    # Synthetic adoption controls toolchain setup. Execute the real unchanged
    # CLI entrypoints with the actual repaired settings readers in the target.
    for name in ("harness.py", "projects.py", "dependency_maps.py"):
        shutil.copyfile(workflow.SOURCE / "agentic_harness/tools" / name,
                        target / "agentic_harness/tools" / name)
    relative = workflow.workflow_name(home)
    path = target / relative
    if kind == "duplicate-key":
        path.write_text("checks: []\nchecks: []\n")
        runtime_cause, doctor_cause = "duplicate configuration key: checks", "configuration has a non-string or duplicate key"
    else:
        settings = yaml.safe_load(path.read_text())
        settings["environment"] = "not mapping"
        path.write_text(yaml.safe_dump(settings))
        runtime_cause, doctor_cause = "invalid environment", "environment supports lockfiles and prepare lists"
    for command, status, field, cause in (
        ([sys.executable, "-B", str(target / "agentic_harness/tools/harness.py"), "project", "--at", home], "blocked", "reason", runtime_cause),
        ([sys.executable, "-B", str(workflow.SOURCE / "tools/workflow.py"), "doctor", "--target", str(target)], "error", "message", doctor_cause),
    ):
        result = subprocess.run(command, cwd=target, capture_output=True, text=True)
        assert result.returncode == 1
        diagnostic = json.loads(result.stderr)
        assert diagnostic["status"] == status
        assert relative in diagnostic[field] and cause in diagnostic[field]


@pytest.mark.parametrize("home", [".", "services/api"])
@pytest.mark.parametrize("location", ["top", "nested"])
@pytest.mark.parametrize("key,kind", [("? [non, string, key]", "list"), ("? {non: string}", "dict")])
def test_public_unhashable_settings_keys_preserve_runtime_and_doctor_diagnostics(distribution, target, home, location, key, kind):
    import projects
    import shutil
    import subprocess
    import sys
    source, _ = distribution
    (target / home).mkdir(parents=True, exist_ok=True)
    adopt(source, target, spec_root=home)
    assert projects.resolve("app", target)["workflow"] == workflow.workflow_name(home)
    assert workflow.doctor(target)["status"] == "valid"
    for name in ("harness.py", "projects.py", "dependency_maps.py"):
        shutil.copyfile(workflow.SOURCE / "agentic_harness/tools" / name,
                        target / "agentic_harness/tools" / name)
    authority = workflow.workflow_name(home)
    malformed = key + "\n: invalid\n"
    if location == "nested":
        malformed = "schema_version: 1\ncode_roots: [.]\nchecks:\n  " + key + "\n  : invalid\n"
    (target / authority).write_text(malformed)
    runtime_cause = f"unhashable type: '{kind}'"
    with pytest.raises(ValueError) as selection_error:
        projects.resolve("app", target)
    assert authority in str(selection_error.value) and runtime_cause in str(selection_error.value)
    assert isinstance(selection_error.value.__cause__.__cause__, TypeError)
    doctor_cause = "configuration has a non-string or duplicate key"
    with pytest.raises(workflow.InstallError) as doctor_error:
        workflow.doctor(target)
    assert authority in str(doctor_error.value) and doctor_cause in str(doctor_error.value)
    for command, status, field, cause in (
        ([sys.executable, "-B", str(target / "agentic_harness/tools/harness.py"), "project", "--at", home], "blocked", "reason", runtime_cause),
        ([sys.executable, "-B", str(workflow.SOURCE / "tools/workflow.py"), "doctor", "--target", str(target)], "error", "message", doctor_cause),
    ):
        result = subprocess.run(command, cwd=target, capture_output=True, text=True)
        assert result.returncode == 1
        diagnostic = json.loads(result.stderr)
        assert diagnostic["status"] == status
        assert authority in diagnostic[field] and cause in diagnostic[field]
