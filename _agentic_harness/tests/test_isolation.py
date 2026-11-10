"""Portable project registration and scope isolation use synthetic trees only."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PROJECTS_PATH = ROOT / "_agentic_harness/tools/projects.py"
spec = importlib.util.spec_from_file_location("harness_isolation_projects", PROJECTS_PATH)
projects = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = projects
spec.loader.exec_module(projects)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def entry(root, project_root):
    folder = root / project_root
    write(folder / "openspec/config.yaml", "schema: spec-driven\n")
    queue = write(folder / "openspec/queue.yaml", "queue: []\n")
    return {
        "root": project_root,
        "queue": queue.relative_to(root).as_posix(),
        "code_roots": [project_root],
        "checks": [["node", "--test"]],
    }


def save_registry(root, data):
    write(root / "_agentic_harness/projects.yaml", yaml.safe_dump(data))


@pytest.fixture
def registered(tmp_path):
    root = tmp_path / "repository"
    data = {"schema_version": 1, "projects": {"service": entry(root, "packages/service")}}
    save_registry(root, data)
    return root, data


def test_sole_project_resolves_canonical_nested_authority_without_creating_other_root(registered):
    root, _ = registered
    before = sorted(path.relative_to(root) for path in root.rglob("*"))
    selected = projects.resolve(None, root)
    assert selected["id"] == "service"
    assert selected == projects.resolve("service", root)
    assert root / selected["queue"] == root / selected["root"] / "openspec/queue.yaml"
    assert selected["environment"] == {"lockfiles": [], "prepare": []}
    assert selected["evidence_exclude"] == []
    assert not (root / "openspec").exists()
    with pytest.raises(ValueError, match="unknown OpenSpec project"):
        projects.resolve("unknown", root)
    assert sorted(path.relative_to(root) for path in root.rglob("*")) == before


def test_whole_repository_registration_needs_no_application_lockfile(tmp_path):
    root = tmp_path / "repository"
    data = {"schema_version": 1, "projects": {"project": entry(root, ".")}}
    save_registry(root, data)
    selected = projects.resolve(None, root)
    assert selected["root"] == "."
    assert selected["queue"] == "openspec/queue.yaml"
    assert selected["code_roots"] == ["."]
    assert selected["environment"]["lockfiles"] == []
    assert not (root / "uv.lock").exists()
    assert projects.relative_root(root, ".", exists=True) == root
    with pytest.raises(ValueError):
        projects.relative_path(root, ".")


def test_distinct_scopes_require_explicit_selection_and_keep_separate_authorities(registered):
    root, data = registered
    data["projects"]["frontend"] = entry(root, "packages/frontend")
    save_registry(root, data)
    with pytest.raises(ValueError):
        projects.resolve(None, root)
    service = projects.resolve("service", root)
    frontend = projects.resolve("frontend", root)
    assert service["root"] == "packages/service"
    assert frontend["root"] == "packages/frontend"
    assert service["queue"] != frontend["queue"]
    assert service["code_roots"] == ["packages/service"]
    assert frontend["code_roots"] == ["packages/frontend"]
    assert not (root / "openspec").exists()


def test_duplicate_authority_and_duplicate_yaml_keys_rejected(registered):
    root, data = registered
    data["projects"]["second-name"] = dict(data["projects"]["service"])
    save_registry(root, data)
    with pytest.raises(ValueError, match="conflicting/missing OpenSpec authority"):
        projects.registry(root)
    (root / "_agentic_harness/projects.yaml").write_text("schema_version: 1\nschema_version: 1\nprojects: {}\n")
    with pytest.raises(ValueError, match="duplicate configuration key"):
        projects.registry(root)


@pytest.mark.parametrize("value", [
    "../outside", "/absolute/outside", "packages/../outside", "packages/./service",
    "packages\\service", "packages//service", "packages/service/", "",
])
def test_escaped_or_noncanonical_roots_rejected(registered, value):
    root, data = registered
    data["projects"]["service"]["root"] = value
    save_registry(root, data)
    with pytest.raises(ValueError):
        projects.registry(root)
    assert not (root / "openspec").exists()


@pytest.mark.parametrize("field", ["root", "queue", "code_roots"])
def test_symlink_aliases_cannot_expand_registered_scope(registered, tmp_path, field):
    root, data = registered
    outside = tmp_path / "outside"
    entry(outside, ".")
    (root / "alias").symlink_to(outside, target_is_directory=True)
    project = data["projects"]["service"]
    if field == "root":
        project.update(root="alias", queue="alias/openspec/queue.yaml")
    elif field == "queue":
        queue = root / project["queue"]
        queue.unlink()
        queue.symlink_to(outside / "openspec/queue.yaml")
    else:
        project["code_roots"] = ["alias"]
    save_registry(root, data)
    with pytest.raises(ValueError, match="aliased"):
        projects.registry(root)


@pytest.mark.parametrize("missing", ["root", "queue", "config"])
def test_missing_canonical_project_artifacts_block_resolution(registered, missing):
    root, data = registered
    project = data["projects"]["service"]
    if missing == "root":
        shutil.rmtree(root / project["root"])
    elif missing == "queue":
        (root / project["queue"]).unlink()
    else:
        (root / project["root"] / "openspec/config.yaml").unlink()
    with pytest.raises(ValueError):
        projects.registry(root)
    assert not (root / "openspec").exists()


def test_queue_cannot_be_borrowed_from_another_openspec_project(registered):
    root, data = registered
    other = entry(root, "other")
    data["projects"]["service"]["queue"] = other["queue"]
    save_registry(root, data)
    with pytest.raises(ValueError, match="conflicting/missing OpenSpec authority"):
        projects.registry(root)


def test_environment_settings_are_portable_and_declared_locks_may_be_created_later(registered):
    root, data = registered
    configured = {
        "lockfiles": ["package-lock.json", "packages/service/deno.lock"],
        "prepare": [["npm", "ci", "--ignore-scripts"], ["node", "scripts/check-env.mjs"]],
    }
    data["projects"]["service"]["environment"] = configured
    save_registry(root, data)
    assert projects.resolve("service", root)["environment"] == configured
    assert not (root / "package-lock.json").exists()
    assert not (root / "packages/service/deno.lock").exists()


@pytest.mark.parametrize("configured,expected", [
    ({}, {"lockfiles": [], "prepare": []}),
    ({"lockfiles": []}, {"lockfiles": [], "prepare": []}),
    ({"prepare": [["node", "--version"]]}, {"lockfiles": [], "prepare": [["node", "--version"]]}),
])
def test_partial_environment_settings_normalize_without_python_assumptions(registered, configured, expected):
    root, data = registered
    data["projects"]["service"]["environment"] = configured
    save_registry(root, data)
    assert projects.resolve("service", root)["environment"] == expected


@pytest.mark.parametrize("environment", [
    "npm ci", None, {"unknown": True}, {"lockfiles": "package-lock.json"},
    {"lockfiles": ["package-lock.json", "package-lock.json"]},
    {"lockfiles": ["."]}, {"lockfiles": ["../external.lock"]},
    {"lockfiles": ["/external.lock"]}, {"lockfiles": ["nested/../lock"]},
    {"prepare": "npm ci"}, {"prepare": [[]]}, {"prepare": [["node", ""]]},
    {"prepare": [["node", 1]]},
])
def test_malformed_environment_cannot_weaken_binding(registered, environment):
    root, data = registered
    data["projects"]["service"]["environment"] = environment
    save_registry(root, data)
    with pytest.raises(ValueError):
        projects.registry(root)


@pytest.mark.parametrize("field,value", [
    ("lockfiles", ["alias.lock"]), ("evidence_exclude", ["alias-private"]),
])
def test_optional_paths_reject_symlink_aliases(registered, tmp_path, field, value):
    root, data = registered
    outside = write(tmp_path / "external.lock", "synthetic\n")
    if field == "lockfiles":
        (root / "alias.lock").symlink_to(outside)
        data["projects"]["service"]["environment"] = {"lockfiles": value}
    else:
        (root / "alias-private").symlink_to(tmp_path, target_is_directory=True)
        data["projects"]["service"][field] = value
    save_registry(root, data)
    with pytest.raises(ValueError, match="aliased"):
        projects.registry(root)


def test_evidence_exclusions_are_explicit_project_policy(registered):
    root, data = registered
    data["projects"]["service"]["evidence_exclude"] = ["private", "packages/service/fixtures/private"]
    save_registry(root, data)
    assert projects.resolve("service", root)["evidence_exclude"] == ["private", "packages/service/fixtures/private"]


@pytest.mark.parametrize("excluded", ["private", ["../private"], ["/private"], ["private", "private"]])
def test_invalid_evidence_exclusions_rejected(registered, excluded):
    root, data = registered
    data["projects"]["service"]["evidence_exclude"] = excluded
    save_registry(root, data)
    with pytest.raises(ValueError):
        projects.registry(root)


@pytest.mark.parametrize("scope,path,expected", [
    (".", "source.js", True), (".", "packages/service/source.js", True),
    ("packages/service", "packages/service/source.js", True),
    ("packages/service", "packages/service", True),
    ("packages/service", "packages/service-extra/source.js", False),
    ("packages/service", "packages/frontend/source.js", False),
])
def test_scope_membership_respects_path_component_boundaries(scope, path, expected):
    assert projects.scope_contains(scope, path) is expected


@pytest.mark.parametrize("path", ["../outside", "/outside", "source/../../outside", "source\\outside", ""])
def test_repository_wide_scope_does_not_authorize_unsafe_paths(path):
    try:
        covered = projects.scope_contains(".", path)
    except ValueError:
        return
    assert covered is False
