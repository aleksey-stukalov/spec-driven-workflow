"""Installer ownership and adoption behavior; upstream CLI tests live separately."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sdw_installer_tests", ROOT / "tools/workflow.py")
workflow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file() and not p.is_symlink() and ".git" not in p.relative_to(root).parts}


@pytest.fixture
def distribution(tmp_path, monkeypatch):
    source = tmp_path / "distribution"
    source.mkdir()
    harness = source / workflow.HARNESS
    for folder in workflow.PAYLOAD_DIRECTORIES:
        (harness / folder).mkdir(parents=True)
        (harness / folder / "example.md").write_text(f"Shared {folder}.\n")
    for filename in workflow.PAYLOAD_FILES:
        (harness / filename).write_text("source metadata\n")
    (harness / ".gitignore").write_text("node_modules/\n.venv/\n__pycache__/\n*.py[cod]\n")
    (harness / "package.json").write_text(json.dumps({"dependencies": {"@fission-ai/openspec": workflow.OPENSPEC_VERSION}}))
    (source / "tools").mkdir()
    (source / "tools/adapters.py").write_text('''
def outputs(registry, agents):
    result = {}
    for agent in agents:
        folder = ".agents" if agent == "codex" else ".claude"
        result[folder + "/skills/sdw-run/SKILL.md"] = "Own workflow skill.\\n"
    return result

def entrypoint(registry):
    return "Workflow domains: " + ", ".join(sorted(registry["projects"]))
''')
    calls = []

    def render(source, target, registry, registrations):
        outputs, initial = {}, {}
        for name, project in registry["projects"].items():
            root = project["root"]
            for agent in registrations[name]["agents"]:
                folder = ".agents" if agent == "codex" else ".claude"
                path = workflow.join(root, folder + "/skills/openspec-propose/SKILL.md")
                outputs[path] = b"Pristine upstream skill.\n"
            config = workflow.join(root, "openspec/config.yaml")
            if not (target / config).exists():
                initial[config] = b"schema: spec-driven\n"
        return outputs, initial

    def dependencies(source, temporary):
        calls.append("npm ci")
        modules = temporary / "node_modules"
        package = modules / "@fission-ai/openspec/package.json"
        package.parent.mkdir(parents=True)
        package.write_text(json.dumps({"version": workflow.OPENSPEC_VERSION}))
        return modules

    monkeypatch.setattr(workflow, "render_upstream", render)
    monkeypatch.setattr(workflow, "prepare_dependencies", dependencies)
    monkeypatch.setattr(workflow, "verify_project_root", lambda *args: None)
    return source, calls


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "consumer"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def adopt(source, target, **kwargs):
    options = dict(project="app", scopes=["."], checks=[["npm", "test"]], agents=["codex", "claude"])
    options.update(kwargs)
    return workflow.installation(target, source=source, **options)


def test_install_preserves_user_settings_and_upstream_bytes(distribution, target):
    source, calls = distribution
    (target / ".codex").mkdir()
    (target / ".codex/config.toml").write_text('model = "chosen-by-user"\n')
    (target / ".claude").mkdir()
    (target / ".claude/settings.json").write_text('{"permissions": {"deny": ["Bash(rm:*)"]}}\n')
    (target / "AGENTS.md").write_text("# Existing policy\nKeep this requirement.\n")
    result = adopt(source, target)
    assert result["status"] == "installed"
    assert (target / ".codex/config.toml").read_text() == 'model = "chosen-by-user"\n'
    assert (target / ".claude/settings.json").read_text() == '{"permissions": {"deny": ["Bash(rm:*)"]}}\n'
    assert (target / "AGENTS.md").read_text().startswith("# Existing policy\nKeep this requirement.\n")
    assert (target / ".agents/skills/openspec-propose/SKILL.md").read_bytes() == b"Pristine upstream skill.\n"
    assert (target / ".agents/skills/sdw-run/SKILL.md").is_file()
    assert (target / "openspec/specs").is_dir()
    assert (target / "openspec/changes").is_dir()
    assert calls == ["npm ci"]
    assert workflow.doctor(target)["status"] == "valid"
    ignored = subprocess.run(["git", "check-ignore", "_agentic_harness/node_modules/@fission-ai/openspec/package.json"], cwd=target, capture_output=True)
    assert ignored.returncode == 0


def test_repeat_install_is_noop(distribution, target):
    source, calls = distribution
    adopt(source, target)
    before = files(target)
    result = adopt(source, target)
    assert result["changed"] == []
    assert result["removed"] == []
    assert not result["install_toolchain"]
    assert files(target) == before
    assert calls == ["npm ci"]


def test_scope_can_cover_disjoint_non_python_directories(distribution, target):
    source, _ = distribution
    for directory in ("services/api", "tests/api", "unrelated"):
        (target / directory).mkdir(parents=True)
    (target / "services/api/package-lock.json").write_text('{"lockfileVersion": 3}\n')
    (target / "unrelated/README.md").write_text("Different process.\n")
    result = adopt(source, target, spec_root="services/api", scopes=["services/api", "tests/api"], lockfiles=["services/api/package-lock.json"])
    registry = workflow.load_registry(target)
    project = registry["projects"]["app"]
    assert project["code_roots"] == ["services/api", "tests/api"]
    assert project["root"] == "services/api"
    assert project["environment"]["lockfiles"] == ["services/api/package-lock.json"]
    assert not (target / "uv.lock").exists()
    assert not (target / "openspec").exists()
    assert (target / "services/api/.agents/skills/openspec-propose/SKILL.md").is_file()
    assert (target / "unrelated/README.md").read_text() == "Different process.\n"
    assert result["projects"] == ["app"]


def test_existing_product_config_specs_and_queue_are_user_owned(distribution, target):
    source, _ = distribution
    (target / "openspec/specs/product").mkdir(parents=True)
    (target / "openspec/changes/in-flight").mkdir(parents=True)
    config = b"# Local policy\nschema: custom\ncontext: Keep existing context.\n"
    spec = b"# Contract\nPreserve product behavior.\n"
    queue = b"# Human ordering\nqueue:\n- change: in-flight\n  depends_on: []\n"
    (target / "openspec/config.yaml").write_bytes(config)
    (target / "openspec/specs/product/spec.md").write_bytes(spec)
    (target / "openspec/queue.yaml").write_bytes(queue)
    adopt(source, target)
    assert (target / "openspec/config.yaml").read_bytes() == config
    assert (target / "openspec/specs/product/spec.md").read_bytes() == spec
    assert (target / "openspec/queue.yaml").read_bytes() == queue
    manifest = json.loads((target / workflow.MANIFEST).read_text())
    assert "openspec/config.yaml" not in manifest["managed"]
    assert workflow.REGISTRY not in manifest["managed"]


def test_dry_run_changes_neither_target_nor_dependencies(distribution, target):
    source, calls = distribution
    (target / "README.md").write_text("Existing project.\n")
    before = files(target)
    result = adopt(source, target, dry_run=True)
    assert result["status"] == "planned"
    assert result["changed"]
    assert result["install_toolchain"]
    assert "Keep" not in result["diffs"]["AGENTS.md"]
    assert "+" + workflow.START in result["diffs"]["AGENTS.md"]
    assert files(target) == before
    assert calls == []


def test_update_rejects_locally_edited_payload_before_writes(distribution, target):
    source, _ = distribution
    adopt(source, target)
    (target / "_agentic_harness/policies/example.md").write_text("Locally edited package rule.\n")
    before = files(target)
    with pytest.raises(workflow.InstallError, match="locally changed"):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before


def test_update_preserves_local_config_and_surrounding_instructions(distribution, target):
    source, _ = distribution
    adopt(source, target)
    (source / "_agentic_harness/policies/example.md").write_text("Updated package rule.\n")
    agents = target / "AGENTS.md"
    agents.write_text("User addition before.\n\n" + agents.read_text() + "\nUser addition after.\n")
    config = target / "openspec/workflow.yaml"
    data = yaml.safe_load(config.read_text())
    data["checks"] = [["npm", "run", "verify"]]
    config.write_text("# Local configuration comment\n" + yaml.safe_dump(data))
    before_config = config.read_bytes()
    result = workflow.installation(target, source=source, update=True)
    assert "_agentic_harness/policies/example.md" in result["changed"]
    assert (target / "_agentic_harness/policies/example.md").read_text() == "Updated package rule.\n"
    assert config.read_bytes() == before_config
    assert agents.read_text().startswith("User addition before.")
    assert agents.read_text().endswith("User addition after.\n")
    assert workflow.doctor(target)["status"] == "valid"


def test_second_independent_domain_and_overlap_rejection(distribution, target):
    source, _ = distribution
    (target / "apps/a").mkdir(parents=True)
    (target / "apps/b").mkdir(parents=True)
    adopt(source, target, project="a", spec_root="apps/a", scopes=["apps/a"])
    result = adopt(source, target, project="b", spec_root="apps/b", scopes=["apps/b"])
    assert result["projects"] == ["a", "b"]
    before = files(target)
    (target / "third").mkdir()
    with pytest.raises(workflow.InstallError, match="overlaps another domain"):
        adopt(source, target, project="third", spec_root="third", scopes=["apps"])
    assert files(target) == before


def test_customized_upstream_collision_is_preserved(distribution, target):
    source, calls = distribution
    path = target / ".agents/skills/openspec-propose/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("Custom wrapper using upstream name.\n")
    before = files(target)
    with pytest.raises(workflow.InstallError, match="existing file conflicts"):
        adopt(source, target)
    assert files(target) == before
    assert calls == []


def test_dependency_failure_does_not_leave_partial_install(distribution, target, monkeypatch):
    source, _ = distribution
    (target / "AGENTS.md").write_text("Original.\n")
    before = files(target)

    def fail(*args):
        raise workflow.InstallError("npm unavailable")

    monkeypatch.setattr(workflow, "prepare_dependencies", fail)
    with pytest.raises(workflow.InstallError, match="npm unavailable"):
        adopt(source, target)
    assert files(target) == before
    assert not (target / workflow.HARNESS).exists()


@pytest.mark.parametrize("scope", ["../outside", "/tmp/outside", "apps/../outside", "apps//api", ".git"])
def test_unsafe_scope_rejected_without_writes(distribution, target, scope):
    source, calls = distribution
    with pytest.raises(workflow.InstallError):
        adopt(source, target, scopes=[scope])
    assert files(target) == {}
    assert calls == []


def test_symlinked_install_path_cannot_escape_target(distribution, target, tmp_path):
    source, _ = distribution
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / ".agents").symlink_to(outside, target_is_directory=True)
    with pytest.raises(workflow.InstallError, match="symlink"):
        adopt(source, target)
    assert files(outside) == {}
    assert files(target) == {}


def test_claude_symlink_to_agents_remains_intact(distribution, target):
    source, _ = distribution
    (target / "AGENTS.md").write_text("Shared human instructions.\n")
    (target / "CLAUDE.md").symlink_to("AGENTS.md")
    adopt(source, target)
    assert (target / "CLAUDE.md").is_symlink()
    assert (target / "AGENTS.md").read_text().count(workflow.START) == 1
    assert workflow.doctor(target)["status"] == "valid"


def test_existing_active_changes_need_a_deliberate_queue(distribution, target):
    source, calls = distribution
    (target / "openspec/changes/pending").mkdir(parents=True)
    (target / "openspec/changes/pending/proposal.md").write_text("# Existing work\n")
    before = files(target)
    with pytest.raises(workflow.InstallError, match="explicit dependency queue"):
        adopt(source, target)
    assert files(target) == before
    assert calls == []


def test_child_environment_does_not_reuse_user_codex_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "real-user-config"))
    environment = workflow.isolated_environment(tmp_path / "isolated")
    assert environment["CODEX_HOME"] == str(tmp_path / "isolated/codex")
    assert environment["HOME"] == str(tmp_path / "isolated")
    assert not (tmp_path / "real-user-config").exists()


@pytest.mark.parametrize("group,path", [("managed", "README.md"), ("managed", "_agentic_harness/projects.yaml"), ("managed", "openspec/workflow.yaml"), ("upstream", ".codex/config.toml"), ("blocks", "CONTRIBUTING.md")])
def test_manifest_cannot_claim_unrelated_files(distribution, target, group, path):
    source, _ = distribution
    adopt(source, target)
    product = target / path
    product.parent.mkdir(parents=True, exist_ok=True)
    if not product.exists():
        product.write_text("User-owned content.\n")
    manifest_file = target / workflow.MANIFEST
    manifest = json.loads(manifest_file.read_text())
    manifest[group][path] = workflow.digest(product.read_bytes())
    manifest_file.write_text(json.dumps(manifest))
    before = files(target)
    with pytest.raises(workflow.InstallError, match="manifest claims"):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before


def test_target_must_be_git_worktree_root(distribution, target, tmp_path):
    source, _ = distribution
    nested = target / "component"
    nested.mkdir()
    with pytest.raises(workflow.InstallError, match="worktree root"):
        adopt(source, nested)
    blank = tmp_path / "not-git"
    blank.mkdir()
    with pytest.raises(workflow.InstallError, match="not a Git worktree"):
        adopt(source, blank)


def test_doctor_detects_stale_local_binding(distribution, target):
    source, _ = distribution
    (target / "a").mkdir()
    (target / "b").mkdir()
    adopt(source, target, scopes=["a"])
    config = target / "openspec/workflow.yaml"
    data = yaml.safe_load(config.read_text())
    data["code_roots"] = ["b"]
    config.write_text(yaml.safe_dump(data))
    with pytest.raises(workflow.InstallError, match="configuration changed"):
        workflow.doctor(target)
    workflow.installation(target, source=source, update=True)
    assert workflow.doctor(target)["status"] == "valid"


def test_atomic_write_failure_keeps_original(distribution, target, monkeypatch):
    source, _ = distribution
    adopt(source, target)
    (source / "_agentic_harness/policies/example.md").write_text("New content.\n")
    before = files(target)
    original_replace = workflow.os.replace

    def fail(source_path, destination):
        if Path(destination).name == "example.md" and Path(destination).parent.name == "policies":
            raise OSError("replacement failed")
        return original_replace(source_path, destination)

    monkeypatch.setattr(workflow.os, "replace", fail)
    with pytest.raises(OSError, match="replacement failed"):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before
    assert not list(target.rglob(".sdw-write-*"))


def test_active_claim_blocks_update_only_for_its_worktree(distribution, target, tmp_path):
    source, _ = distribution
    adopt(source, target)
    database = target / ".git/agentic-harness/coordination.sqlite3"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE records(kind TEXT,key TEXT,data TEXT,PRIMARY KEY(kind,key))")
    claim = {"id": "app:change", "worktree": str(target), "state": "running"}
    connection.execute("INSERT INTO records VALUES (?,?,?)", ("claim", claim["id"], json.dumps(claim)))
    connection.commit()
    before = files(target)
    with pytest.raises(workflow.InstallError, match="active workflow claim"):
        workflow.installation(target, source=source, update=True, dry_run=True)
    assert files(target) == before
    claim["worktree"] = str(tmp_path / "other-worktree")
    connection.execute("UPDATE records SET data=?", (json.dumps(claim),))
    connection.commit()
    connection.close()
    assert workflow.installation(target, source=source, update=True)["changed"] == []


def test_optional_environment_fields_and_underscore_id(distribution, target):
    source, _ = distribution
    adopt(source, target, project="my_app")
    config = target / "openspec/workflow.yaml"
    data = yaml.safe_load(config.read_text())
    data["environment"] = {}
    config.write_text(yaml.safe_dump(data))
    workflow.installation(target, source=source, update=True)
    assert workflow.doctor(target)["status"] == "valid"


def test_concurrent_local_config_edit_during_preparation_is_preserved(distribution, target, monkeypatch):
    source, _ = distribution
    adopt(source, target)
    package = source / "_agentic_harness/package-lock.json"
    package.write_text("updated lock\n")
    config = target / "openspec/workflow.yaml"
    original_prepare = workflow.prepare_dependencies
    prior_payload = (target / "_agentic_harness/package-lock.json").read_bytes()

    def concurrent_edit(*args):
        data = yaml.safe_load(config.read_text())
        data["checks"] = [["new-test-command"]]
        config.write_text(yaml.safe_dump(data))
        return original_prepare(*args)

    monkeypatch.setattr(workflow, "prepare_dependencies", concurrent_edit)
    with pytest.raises(workflow.InstallError, match="target changed while preparing"):
        workflow.installation(target, source=source, update=True)
    assert yaml.safe_load(config.read_text())["checks"] == [["new-test-command"]]
    assert (target / "_agentic_harness/package-lock.json").read_bytes() == prior_payload


@pytest.mark.parametrize("invalid", ["ambiguous", "external-store", "invalid-yaml", "symlink"])
def test_doctor_rejects_invalid_openspec_authority(distribution, target, invalid, tmp_path):
    source, _ = distribution
    adopt(source, target)
    config = target / "openspec/config.yaml"
    if invalid == "ambiguous":
        (target / "openspec/config.yml").write_text("schema: spec-driven\n")
    elif invalid == "external-store":
        config.write_text("store: external\n")
    elif invalid == "invalid-yaml":
        config.write_text("[unterminated\n")
    else:
        other = tmp_path / "other.yaml"
        other.write_text("schema: spec-driven\n")
        config.unlink()
        config.symlink_to(other)
    with pytest.raises(workflow.InstallError):
        workflow.doctor(target)


def test_missing_declared_lock_is_supported_but_directory_is_rejected(distribution, target):
    source, _ = distribution
    adopt(source, target, lockfiles=["package-lock.json"])
    assert workflow.doctor(target)["status"] == "valid"
    (target / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    assert workflow.doctor(target)["status"] == "valid"
    (target / "package-lock.json").unlink()
    (target / "package-lock.json").mkdir()
    with pytest.raises(workflow.InstallError, match="not a regular file"):
        workflow.doctor(target)


@pytest.mark.parametrize("metadata_first", [True, False])
@pytest.mark.parametrize("dry_run", [True, False])
def test_source_and_other_domain_metadata_cannot_overlap(distribution, target, metadata_first, dry_run):
    source, calls = distribution
    for path in ("homes/a/openspec", "homes/b", "src/a"):
        (target / path).mkdir(parents=True)
    a = dict(project="a", spec_root="homes/a", scopes=["src/a"])
    b = dict(project="b", spec_root="homes/b", scopes=["homes/a/openspec"])
    first, second = (a, b) if metadata_first else (b, a)
    adopt(source, target, **first)
    before = files(target)
    previous_calls = list(calls)
    with pytest.raises(workflow.InstallError, match="project area overlaps another domain"):
        adopt(source, target, **second, dry_run=dry_run)
    assert files(target) == before
    assert calls == previous_calls


def test_doctor_rejects_source_scope_covering_another_domains_metadata(distribution, target):
    source, _ = distribution
    for path in ("homes/a", "homes/b", "src/a", "src/b"):
        (target / path).mkdir(parents=True)
    adopt(source, target, project="a", spec_root="homes/a", scopes=["src/a"])
    adopt(source, target, project="b", spec_root="homes/b", scopes=["src/b"])
    projects = workflow.load_registry(target)["projects"]
    assert projects["a"]["code_roots"] == ["src/a"]
    assert projects["b"]["code_roots"] == ["src/b"]
    config = target / "homes/b/openspec/workflow.yaml"
    data = yaml.safe_load(config.read_text())
    data["code_roots"] = ["homes/a/openspec"]
    config.write_text(yaml.safe_dump(data))
    with pytest.raises(workflow.InstallError, match="project area overlaps another domain"):
        workflow.doctor(target)


@pytest.mark.parametrize("name", ["_agentic_harness/policies/example.md", ".agents/skills/openspec-propose/SKILL.md", "AGENTS.md"])
def test_early_generator_edit_cannot_become_trusted_baseline(distribution, target, monkeypatch, name):
    source, calls = distribution
    adopt(source, target)
    original_manifest = (target / workflow.MANIFEST).read_bytes()
    existing_calls = list(calls)
    module = workflow.adapter_module(source)
    edited = target / name
    user_content = edited.read_bytes() + b"\nConcurrent human edit.\n"

    def generate(registry, agents):
        edited.write_bytes(user_content)
        return module.outputs(registry, agents)

    monkeypatch.setattr(workflow, "adapter_module", lambda source: SimpleNamespace(outputs=generate, entrypoint=module.entrypoint))
    with pytest.raises(workflow.InstallError, match="target changed while preparing"):
        workflow.installation(target, source=source, update=True)
    assert edited.read_bytes() == user_content
    assert (target / workflow.MANIFEST).read_bytes() == original_manifest
    assert calls == existing_calls


def legacy_configuration(target):
    """Seed the previous on-disk format while keeping an installed payload."""
    expanded = workflow.load_registry(target)
    for project in expanded["projects"].values():
        (target / workflow.join(project["root"], "openspec/workflow.yaml")).unlink()
    (target / workflow.REGISTRY).write_text(yaml.safe_dump(expanded, sort_keys=False))
    return expanded


@pytest.mark.parametrize("environment", [None, {}, {"lockfiles": []}, {"prepare": []}])
def test_doctor_preserves_legacy_hashes_with_omitted_defaults(distribution, target, environment):
    source, _ = distribution
    adopt(source, target)
    legacy = legacy_configuration(target)
    project = legacy["projects"]["app"]
    project.pop("evidence_exclude")
    if environment is None:
        project.pop("environment")
    else:
        project["environment"] = environment
    (target / workflow.REGISTRY).write_text(yaml.safe_dump(legacy))
    manifest_path = target / workflow.MANIFEST
    manifest = json.loads(manifest_path.read_text())
    manifest["registry_sha256"] = workflow.digest(workflow.encoded(legacy))
    manifest_path.write_text(json.dumps(manifest))
    assert workflow.doctor(target)["status"] == "valid"

    # Compatibility accepts only the recorded bytes' semantic document, not
    # arbitrary edits to executable policy in an unmigrated installation.
    project["checks"] = [["npm", "run", "changed-check"]]
    (target / workflow.REGISTRY).write_text(yaml.safe_dump(legacy))
    with pytest.raises(workflow.InstallError, match="configuration changed"):
        workflow.doctor(target)


@pytest.mark.parametrize("spec_root", [".", "services/api"])
def test_install_without_name_uses_selected_openspec_root(distribution, target, spec_root):
    source, _ = distribution
    (target / spec_root).mkdir(parents=True, exist_ok=True)
    result = workflow.installation(target, source=source, spec_root=spec_root,
                                   checks=[["npm", "test"]], agents=["codex"])
    index = yaml.safe_load((target / workflow.REGISTRY).read_text())
    assert index["schema_version"] == 2
    assert len(result["projects"]) == 1
    identity = result["projects"][0]
    assert index["projects"] == {identity: {"root": spec_root}}
    settings_path = workflow.join(spec_root, "openspec/workflow.yaml")
    settings = yaml.safe_load((target / settings_path).read_text())
    assert settings["schema_version"] == 1
    assert settings["code_roots"] == [spec_root]
    assert settings["checks"] == [["npm", "test"]]
    manifest = json.loads((target / workflow.MANIFEST).read_text())
    assert settings_path not in manifest["managed"]
    assert workflow.doctor(target)["status"] == "valid"


def test_repeat_without_name_or_settings_preserves_existing_registration(distribution, target):
    source, calls = distribution
    for path in ("services/api", "tests/api"):
        (target / path).mkdir(parents=True)
    adopt(source, target, project="original_api", spec_root="services/api",
          scopes=["services/api", "tests/api"], checks=[["make", "verify-api"]],
          lockfiles=["services/api/package-lock.json"], agents=["codex"])
    before = files(target)
    result = workflow.installation(target, source=source, spec_root="services/api")
    assert result["projects"] == ["original_api"]
    assert result["changed"] == []
    assert result["removed"] == []
    assert not result["install_toolchain"]
    assert files(target) == before
    assert calls == ["npm ci"]
    assert not (target / ".claude").exists()


def test_automatic_ids_distinguish_roots_with_same_slug(distribution, target):
    source, _ = distribution
    for root in ("services/api", "services-api"):
        (target / root).mkdir(parents=True)
        workflow.installation(target, source=source, spec_root=root,
                              checks=[["npm", "--prefix", root, "test"]])
    projects = workflow.load_registry(target)["projects"]
    assert len(projects) == 2
    assert {project["root"] for project in projects.values()} == {"services/api", "services-api"}
    before = files(target)
    for root in ("services/api", "services-api"):
        assert workflow.installation(target, source=source, spec_root=root)["changed"] == []
    assert files(target) == before


@pytest.mark.parametrize("project,spec_root", [("replacement", "apps/a"), ("original", "apps/b")])
def test_explicit_alias_cannot_rename_or_reassign_existing_identity(distribution, target, project, spec_root):
    source, calls = distribution
    for root in ("apps/a", "apps/b"):
        (target / root).mkdir(parents=True)
    adopt(source, target, project="original", spec_root="apps/a", scopes=["apps/a"])
    before = files(target)
    with pytest.raises(workflow.InstallError):
        workflow.installation(target, source=source, project=project, spec_root=spec_root,
                              checks=[["npm", "test"]])
    assert files(target) == before
    assert calls == ["npm ci"]


def test_legacy_update_migration_is_reviewable_and_preserves_settings(distribution, target):
    source, _ = distribution
    (target / "services/api").mkdir(parents=True)
    (target / "tests/api").mkdir(parents=True)
    adopt(source, target, project="original_api", spec_root="services/api",
          scopes=["services/api", "tests/api"], agents=["codex"])
    legacy = legacy_configuration(target)
    legacy["projects"]["original_api"]["environment"] = {
        "lockfiles": ["services/api/package-lock.json"],
        "prepare": [["npm", "--prefix", "services/api", "ci"]],
    }
    legacy["projects"]["original_api"]["evidence_exclude"] = ["services/api/private"]
    (target / workflow.REGISTRY).write_text("# Previous configuration\n" + yaml.safe_dump(legacy))
    native = target / "services/api/openspec/config.yaml"
    native.write_text("# Existing native rules\nschema: spec-driven\ncontext: Keep existing context.\n")
    native_before = native.read_bytes()
    before = files(target)
    preview = workflow.installation(target, source=source, update=True, dry_run=True)
    settings_path = "services/api/openspec/workflow.yaml"
    assert workflow.REGISTRY in preview["changed"]
    assert settings_path in preview["changed"]
    assert "+schema_version: 2" in preview["diffs"][workflow.REGISTRY]
    assert "evidence_exclude:" in preview["diffs"][settings_path]
    assert files(target) == before
    result = workflow.installation(target, source=source, update=True)
    assert result["projects"] == ["original_api"]
    assert workflow.load_registry(target) == legacy
    assert yaml.safe_load((target / workflow.REGISTRY).read_text()) == {
        "schema_version": 2, "projects": {"original_api": {"root": "services/api"}},
    }
    assert native.read_bytes() == native_before
    assert workflow.doctor(target)["status"] == "valid"
    after = files(target)
    assert workflow.installation(target, source=source, update=True)["changed"] == []
    assert files(target) == after


def test_install_migrates_existing_legacy_identity_without_name(distribution, target):
    source, _ = distribution
    adopt(source, target, project="existing_name", agents=["codex"])
    legacy = legacy_configuration(target)
    result = workflow.installation(target, source=source)
    assert result["projects"] == ["existing_name"]
    assert yaml.safe_load((target / workflow.REGISTRY).read_text())["schema_version"] == 2
    assert workflow.load_registry(target) == legacy
    assert not (target / ".claude").exists()


@pytest.mark.parametrize("conflicting", [False, True])
def test_legacy_companion_must_agree_and_preserves_original_bytes(distribution, target, conflicting):
    source, _ = distribution
    adopt(source, target)
    settings_file = target / "openspec/workflow.yaml"
    settings = yaml.safe_load(settings_file.read_text())
    legacy_configuration(target)
    if conflicting:
        settings["checks"] = [["different-test-command"]]
    content = ("# Human-maintained settings\n" + yaml.safe_dump(settings, sort_keys=False)).encode()
    settings_file.write_bytes(content)
    before = files(target)
    if conflicting:
        with pytest.raises(workflow.InstallError):
            workflow.installation(target, source=source, update=True)
        assert files(target) == before
    else:
        workflow.installation(target, source=source, update=True)
        assert settings_file.read_bytes() == content
        assert workflow.doctor(target)["status"] == "valid"


def test_unindexed_companion_supplies_settings_without_check_flags(distribution, target):
    source, _ = distribution
    for directory in ("backend/openspec", "tests/backend"):
        (target / directory).mkdir(parents=True)
    settings = {
        "schema_version": 1,
        "code_roots": ["backend", "tests/backend"],
        "checks": [["npm", "--prefix", "backend", "test"]],
        "environment": {"lockfiles": ["backend/package-lock.json"], "prepare": [["npm", "--prefix", "backend", "ci"]]},
        "evidence_exclude": ["backend/private"],
    }
    companion = target / "backend/openspec/workflow.yaml"
    content = ("# Already reviewed for this project\n" + yaml.safe_dump(settings, sort_keys=False)).encode()
    companion.write_bytes(content)
    result = workflow.installation(target, source=source, spec_root="backend", agents=["codex"])
    assert len(result["projects"]) == 1
    selected = workflow.load_registry(target)["projects"][result["projects"][0]]
    assert selected["checks"] == settings["checks"]
    assert selected["code_roots"] == settings["code_roots"]
    assert selected["environment"] == settings["environment"]
    assert selected["evidence_exclude"] == settings["evidence_exclude"]
    assert companion.read_bytes() == content
    assert workflow.doctor(target)["status"] == "valid"


def test_first_install_still_requires_concrete_checks(distribution, target):
    source, calls = distribution
    with pytest.raises(workflow.InstallError):
        workflow.installation(target, source=source)
    assert files(target) == {}
    assert calls == []


@pytest.mark.parametrize("invalid", ["missing", "malformed", "directory", "symlink", "unknown-field", "missing-checks"])
def test_invalid_indexed_companion_is_not_recreated_or_overwritten(distribution, target, tmp_path, invalid):
    source, calls = distribution
    adopt(source, target)
    companion = target / "openspec/workflow.yaml"
    if invalid == "malformed":
        companion.write_text("[unterminated\n")
    elif invalid in {"unknown-field", "missing-checks"}:
        data = yaml.safe_load(companion.read_text())
        if invalid == "unknown-field":
            data["typo_in_configuration"] = True
        else:
            data.pop("checks")
        companion.write_text(yaml.safe_dump(data))
    else:
        companion.unlink()
        if invalid == "directory":
            companion.mkdir()
        elif invalid == "symlink":
            outside = tmp_path / "outside-settings.yaml"
            outside.write_text("schema_version: 1\ncode_roots: ['.']\nchecks: [[npm, test]]\n")
            companion.symlink_to(outside)
    before = files(target)
    with pytest.raises(workflow.InstallError):
        workflow.installation(target, source=source, update=True)
    with pytest.raises(workflow.InstallError):
        workflow.installation(target, source=source, checks=[["npm", "test"]])
    with pytest.raises(workflow.InstallError):
        workflow.doctor(target)
    assert files(target) == before
    assert calls == ["npm ci"]


@pytest.mark.parametrize("indexed", [False, True])
def test_companion_is_observed_before_its_first_read(distribution, target, monkeypatch, indexed):
    source, calls = distribution
    if indexed:
        adopt(source, target)
    else:
        (target / "openspec").mkdir()
        (target / "openspec/workflow.yaml").write_text("schema_version: 1\ncode_roots: ['.']\nchecks: [[npm, test]]\n")
    companion = target / "openspec/workflow.yaml"
    original_read = workflow.read_yaml
    previous_calls = list(calls)
    before = files(target)
    edited = False

    def concurrent_read(path):
        nonlocal edited
        result = original_read(path)
        if path == companion and not edited:
            replacement = dict(result, checks=[["concurrently-changed-command"]])
            companion.write_text(yaml.safe_dump(replacement))
            edited = True
        return result

    monkeypatch.setattr(workflow, "read_yaml", concurrent_read)
    with pytest.raises(workflow.InstallError, match="target changed while preparing"):
        workflow.installation(target, source=source, update=indexed)
    assert edited
    before["openspec/workflow.yaml"] = companion.read_bytes()
    assert yaml.safe_load(companion.read_text())["checks"] == [["concurrently-changed-command"]]
    assert files(target) == before
    assert calls == previous_calls


def test_failed_migration_rolls_back_index_and_new_companion(distribution, target, monkeypatch):
    source, _ = distribution
    adopt(source, target)
    legacy_configuration(target)
    (source / "_agentic_harness/policies/example.md").write_text("Updated policy delivered with migration.\n")
    before = files(target)
    original_write = workflow.atomic_write

    def fail_manifest(path, content):
        if path == target / workflow.MANIFEST:
            raise OSError("manifest write failed")
        return original_write(path, content)

    monkeypatch.setattr(workflow, "atomic_write", fail_manifest)
    with pytest.raises(OSError, match="manifest write failed"):
        workflow.installation(target, source=source, update=True)
    assert files(target) == before
    assert not (target / "openspec/workflow.yaml").exists()
