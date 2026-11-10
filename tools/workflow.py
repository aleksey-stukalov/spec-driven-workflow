#!/usr/bin/env python3
"""Install a pinned workflow without taking ownership of application settings.

OpenSpec renders its own integration files in a temporary project. This module
only transfers those unchanged bytes and independently owns the sdw namespace.
All target writes follow conflict detection and dependency preparation.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
from contextlib import contextmanager
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field

import yaml

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "agentic_harness/tools"))
from projects import workflow_path
from dependency_maps import parse as parse_dependency_map
from skill_links import discovery_links, expected_target, validate_link
VERSION = "0.1.0"
OPENSPEC_VERSION = "1.14.3"
HARNESS = "agentic_harness"
LEGACY_HARNESS = "_agentic_harness"
MANIFEST = f"{HARNESS}/install.json"
REGISTRY = f"{HARNESS}/projects.yaml"
START = "<!-- spec-driven-workflow:start -->"
END = "<!-- spec-driven-workflow:end -->"
PAYLOAD_DIRECTORIES = ("tools", "policies", "procedures", "roles", "templates", "skills")
PAYLOAD_FILES = ("README.md", ".gitignore", "plans.yaml", "handbook.yaml", "index.html",
                 "package.json", "package-lock.json", "pyproject.toml", "uv.lock")
AGENTS = {"codex", "claude"}


class InstallError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise InstallError("configuration has a non-string or duplicate key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def read_yaml(path: Path, *, aliases=True):
    try:
        text = path.read_text()
        if not aliases and any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(text)):
            raise InstallError(f"YAML aliases are unsupported: {path}")
        return yaml.load(text, Loader=UniqueLoader)
    except (yaml.YAMLError, UnicodeError) as exc:
        raise InstallError(f"invalid YAML: {path}") from exc


def relative(value: str, *, root=False) -> str:
    if root and value == ".":
        return value
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise InstallError(f"invalid repository-relative path: {value!r}")
    if Path(value).is_absolute() or any(p in {"", ".", ".."} for p in value.split("/")):
        raise InstallError(f"unsafe repository-relative path: {value!r}")
    if value.split("/")[0] == ".git":
        raise InstallError("Git metadata is not an installation scope")
    return value


def target_path(target: Path, value: str, *, root=False) -> Path:
    relative(value, root=root)
    path = target if value == "." else target / value
    cursor = target
    for part in (() if value == "." else Path(value).parts):
        cursor /= part
        if cursor.is_symlink():
            raise InstallError(f"installation path is a symlink: {value}")
    if not path.resolve().is_relative_to(target.resolve()):
        raise InstallError(f"installation path escapes repository: {value}")
    return path


def overlap(left: str, right: str) -> bool:
    return left == "." or right == "." or left == right or left.startswith(right + "/") or right.startswith(left + "/")


def join(root: str, suffix: str) -> str:
    return suffix if root == "." else root + "/" + suffix


def _argv(value) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(a, str) or not a or "\0" in a for a in value):
        raise InstallError("a check must be a nonempty JSON argv array")
    return value


def installation_layout(target: Path) -> str:
    """Select one authority; an old leftover directory is not an installation."""
    manifests = []
    indices = []
    for harness in (HARNESS, LEGACY_HARNESS):
        root = target_path(target, harness)
        if root.exists() and not root.is_dir():
            raise InstallError(f"workflow package root is not a directory: {harness}")
        for filename, found in (("install.json", manifests), ("projects.yaml", indices)):
            path = target_path(target, f"{harness}/{filename}")
            if path.exists():
                if not path.is_file():
                    raise InstallError(f"workflow authority is not a regular file: {harness}/{filename}")
                found.append(harness)
    if len(manifests) > 1 or len(indices) > 1:
        raise InstallError("ambiguous workflow layouts: both package directories contain authority")
    if manifests:
        selected = manifests[0]
        if indices and indices[0] != selected:
            raise InstallError("conflicting workflow layout: manifest and registry use different directories")
        return selected
    if LEGACY_HARNESS in indices:
        raise InstallError("legacy workflow registry has no installation manifest; reconcile ownership before updating")
    return HARNESS


def load_manifest(target: Path, *, harness=None) -> dict | None:
    harness = installation_layout(target) if harness is None else harness
    path = target_path(target, f"{harness}/install.json")
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError) as exc:
        raise InstallError("invalid workflow installation manifest") from exc
    required = {"schema_version", "workflow_version", "openspec_version", "payload_sha256", "registry_sha256", "managed", "upstream", "blocks", "projects"}
    if not isinstance(value, dict) or not required <= set(value) or type(value["schema_version"]) is not int or value["schema_version"] not in {1, 2}:
        raise InstallError("unsupported workflow installation manifest")
    if not isinstance(value["projects"], dict) or not value["projects"]:
        raise InstallError("installation manifest has no projects")
    for record in value["projects"].values():
        if not isinstance(record, dict) or set(record) != {"agents", "root"}:
            raise InstallError("invalid installed domain binding")
        relative(record["root"], root=True)
        agents = record["agents"]
        if not isinstance(agents, list) or not agents or any(not isinstance(a, str) or a not in AGENTS for a in agents):
            raise InstallError("invalid installed agent binding")
    for group in ("managed", "upstream", "blocks"):
        if not isinstance(value[group], dict):
            raise InstallError("invalid installation ownership records")
        for name, sha in value[group].items():
            relative(name)
            if group == "managed" and not managed_path(name, harness=harness):
                raise InstallError(f"manifest claims a non-package file: {name}")
            if group == "upstream" and not upstream_path(name, value["projects"]):
                raise InstallError(f"manifest claims a non-OpenSpec file: {name}")
            if group == "blocks" and name not in {"AGENTS.md", "CLAUDE.md"}:
                raise InstallError(f"manifest claims an unsupported instruction file: {name}")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise InstallError("invalid installed file digest")
    if value["schema_version"] == 2:
        if "links" not in value or not isinstance(value["links"], dict):
            raise InstallError("manifest schema 2 requires typed links")
        selected = {agent for record in value["projects"].values() for agent in record["agents"]}
        allowed = discovery_links(selected)
        if set(value["links"]) != set(allowed):
            raise InstallError("manifest links do not match selected provider discovery")
        for name, record in value["links"].items():
            if (not isinstance(record, dict) or name not in allowed or record != {"kind": "directory_symlink", "target": allowed[name]}
                    or set(record) != {"kind", "target"}
                    or any(overlap(name, path) for path in value["managed"])):
                raise InstallError(f"invalid installation link ownership: {name}")
    elif "links" in value:
        raise InstallError("legacy manifest cannot claim links")
    if not isinstance(value["registry_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["registry_sha256"]):
        raise InstallError("invalid installed registry binding")
    return value


def managed_path(name: str, *, harness=HARNESS) -> bool:
    if name in {f"{harness}/{part}" for part in PAYLOAD_FILES}:
        return True
    if any(name.startswith(f"{harness}/{directory}/") for directory in PAYLOAD_DIRECTORIES):
        return True
    return bool(re.fullmatch(r"(?:\.agents|\.claude)/skills/sdw-[a-z0-9-]+/SKILL\.md", name)
                or re.fullmatch(r"\.codex/agents/sdw-[a-z0-9-]+\.toml", name)
                or re.fullmatch(r"\.claude/agents/sdw-[a-z0-9-]+\.md", name))


def upstream_path(name: str, registrations: dict) -> bool:
    for record in registrations.values():
        prefix = "" if record["root"] == "." else record["root"] + "/"
        if not name.startswith(prefix):
            continue
        local = name[len(prefix):]
        if "codex" in record["agents"] and (local == ".agents/skills/.openspec-target" or re.fullmatch(r"\.agents/skills/openspec-[a-z0-9-]+/SKILL\.md", local)):
            return True
        if "claude" in record["agents"] and re.fullmatch(r"\.claude/skills/openspec-[a-z0-9-]+/SKILL\.md", local):
            return True
    return False


def block(text: str) -> str | None:
    starts, ends = text.count(START), text.count(END)
    if starts != ends or starts > 1:
        raise InstallError("malformed or duplicate workflow instruction block")
    if not starts:
        return None
    begin, end = text.index(START), text.index(END)
    if end < begin:
        raise InstallError("malformed workflow instruction block")
    return text[begin:end + len(END)]


def merge_block(text: str, body: str) -> str:
    new = START + "\n" + body.strip() + "\n" + END
    old = block(text)
    if old is not None:
        return text.replace(old, new, 1)
    return text + ("" if not text or text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n") + new + "\n"


def verify_owned(target: Path, manifest: dict | None) -> None:
    if manifest is None:
        return
    for group in ("managed", "upstream"):
        for name, expected in manifest[group].items():
            path = target_path(target, name)
            if not path.is_file() or digest(path.read_bytes()) != expected:
                raise InstallError(f"locally changed or missing {group} file: {name}; resolve the change before updating")
    for name, record in manifest.get("links", {}).items():
        try:
            if validate_link(target, name) != record:
                raise ValueError("different link record")
        except ValueError as exc:
            raise InstallError(f"locally changed or missing managed link: {name}") from exc
    for name, expected in manifest["blocks"].items():
        path = target_path(target, name)
        current = block(path.read_text()) if path.is_file() else None
        if current is None or digest(current.encode()) != expected:
            raise InstallError(f"locally changed or missing workflow block: {name}")


def workflow_name(root: str, schema_version=3) -> str:
    return workflow_path(relative(root, root=True), schema_version=schema_version)


def workflow_settings(project: dict) -> dict:
    """Normalize defaults without rewriting the project's local YAML."""
    environment = project.get("environment", {})
    if not isinstance(environment, dict) or set(environment) - {"lockfiles", "prepare"}:
        raise InstallError("environment supports lockfiles and prepare lists")
    return {
        "code_roots": project["code_roots"], "checks": project["checks"],
        "environment": {"lockfiles": environment.get("lockfiles", []),
                        "prepare": environment.get("prepare", [])},
        "evidence_exclude": project.get("evidence_exclude", []),
    }


def read_workflow(target: Path, root: str, *, readset=None, required=False, schema_version=3) -> dict | None:
    name = workflow_name(root, schema_version)
    if readset is not None and name not in readset:
        remember(target, name, readset)
    path = target_path(target, name)
    if not path.exists():
        if required:
            raise InstallError(f"missing workflow configuration: {name}")
        return None
    if not path.is_file():
        raise InstallError(f"workflow configuration is not a regular file: {name}")
    try:
        value = read_yaml(path, aliases=False)
        required_fields = {"schema_version", "code_roots", "checks"}
        if (not isinstance(value, dict) or not required_fields <= set(value)
                or set(value) - required_fields - {"environment", "evidence_exclude"}
                or type(value["schema_version"]) is not int or value["schema_version"] != 1):
            raise InstallError(f"unsupported workflow configuration: {name}")
        normalized = workflow_settings(value)
        validate_settings(normalized, name)
        return normalized
    except InstallError as exc:
        raise InstallError(f"invalid workflow configuration {name}: {exc}") from exc


def validate_settings(value: dict, name: str) -> None:
    roots = value["code_roots"]
    checks = value["checks"]
    environment = value["environment"]
    if not isinstance(roots, list) or not roots or any(not isinstance(item, str) for item in roots) or len(set(roots)) != len(roots):
        raise InstallError(f"invalid source scope: {name}")
    for item in roots:
        relative(item, root=True)
    if not isinstance(checks, list) or not checks:
        raise InstallError(f"project requires concrete validation commands: {name}")
    for command in checks:
        _argv(command)
    for field in ("lockfiles", "prepare"):
        if not isinstance(environment[field], list):
            raise InstallError(f"invalid environment {field}: {name}")
    for command in environment["prepare"]:
        _argv(command)
    for items in (environment["lockfiles"], value["evidence_exclude"]):
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items) or len(set(items)) != len(items):
            raise InstallError(f"invalid configuration paths: {name}")
        for item in items:
            relative(item, root=True)


def load_registry(target: Path, *, readset=None, harness=None, migration=False) -> dict:
    """Expand either index version into the runtime's stable project structure."""
    harness = installation_layout(target) if harness is None else harness
    name = f"{harness}/projects.yaml"
    if readset is not None and name not in readset:
        remember(target, name, readset)
    path = target_path(target, name)
    if not path.exists():
        return {"schema_version": 1, "projects": {}}
    value = read_yaml(path)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "projects"}
            or type(value["schema_version"]) is not int or value["schema_version"] not in {1, 2, 3}
            or not isinstance(value["projects"], dict)):
        raise InstallError("unsupported projects.yaml; existing configuration was preserved")
    projects = {}
    for name, project in value["projects"].items():
        if not isinstance(project, dict) or "root" not in project:
            raise InstallError(f"incomplete project registration: {name}")
        root = relative(project["root"], root=True)
        local = read_workflow(target, root, readset=readset, required=value["schema_version"] in {2, 3}, schema_version=value["schema_version"])
        alternate = read_workflow(target, root, readset=readset, schema_version=2 if value["schema_version"] == 3 else 3)
        if alternate is not None and not migration:
            raise InstallError("ambiguous workflow configuration; reconcile legacy settings")
        if value["schema_version"] != 3 and alternate is not None and local is not None and alternate != local:
            raise InstallError("workflow configuration conflicts with migration destination")
        if value["schema_version"] in {2, 3}:
            if set(project) != {"root"}:
                raise InstallError(f"version {value['schema_version']} projects.yaml contains only OpenSpec roots; edit {workflow_name(root, value['schema_version'])}")
            projects[name] = {"root": root, "queue": join(root, "openspec/dependency-map.yaml" if value["schema_version"] == 3 else "openspec/queue.yaml"), **local}
        else:
            required_fields = {"root", "queue", "code_roots", "checks"}
            if not required_fields <= set(project) or set(project) - required_fields - {"environment", "evidence_exclude"}:
                raise InstallError(f"invalid legacy project configuration: {name}")
            settings = workflow_settings(project)
            if local is not None and local != settings:
                raise InstallError(f"workflow configuration conflicts with legacy projects.yaml: {workflow_name(root)}")
            projects[name] = {"root": root, "queue": project["queue"], **settings}
        authority = projects[name]["queue"]
        alternate_map = join(root, "openspec/queue.yaml" if value["schema_version"] == 3 else "openspec/dependency-map.yaml")
        for candidate in (authority, alternate_map):
            if readset is not None:
                remember(target, candidate, readset)
        if not target_path(target, authority).is_file():
            raise InstallError(f"missing indexed dependency map: {authority}")
        dependency_document(target_path(target, authority))
        if target_path(target, alternate_map).exists():
            dependency_document(target_path(target, alternate_map))
            if not migration:
                raise InstallError(f"ambiguous dependency map: {alternate_map}")
    return {"schema_version": 1, "projects": projects}


def project_identifier(root: str, projects: dict) -> str:
    """Allocate once; the stored identity survives later configuration changes."""
    base = "root" if root == "." else re.sub(r"[^a-z0-9_-]+", "-", root.lower()).strip("-_")
    if not base or not base[0].isalpha():
        base = "project-" + base if base else "project"
    if base not in projects:
        return base
    suffix = digest(root.encode())
    for width in range(12, len(suffix) + 1, 4):
        candidate = base + "-" + suffix[:width]
        if candidate not in projects:
            return candidate
    raise InstallError("cannot allocate a unique workflow identity; specify --project explicitly")


def validate_registry(target: Path, registry: dict) -> None:
    roots = []
    scopes = []
    for name, project in registry["projects"].items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", name) or not isinstance(project, dict):
            raise InstallError("project IDs must use lowercase letters, digits, underscores and hyphens")
        if not {"root", "queue", "code_roots", "checks"} <= set(project):
            raise InstallError(f"incomplete project registration: {name}")
        if set(project) - {"root", "queue", "code_roots", "checks", "environment", "evidence_exclude"}:
            raise InstallError(f"unknown project configuration field: {name}")
        root = relative(project["root"], root=True)
        if not target_path(target, root, root=True).is_dir():
            raise InstallError(f"OpenSpec project directory does not exist: {root}")
        if project["queue"] not in {join(root, "openspec/queue.yaml"), join(root, "openspec/dependency-map.yaml")}:
            raise InstallError(f"queue must belong to its OpenSpec project: {name}")
        target_path(target, project["queue"])
        if root in roots:
            raise InstallError("two domains cannot share an OpenSpec authority")
        # Nested authorities make cwd-based native operations ambiguous.
        if any(overlap(root, other) for other in roots):
            raise InstallError("overlapping OpenSpec roots require an explicit migration")
        roots.append(root)
        areas = project["code_roots"]
        if not isinstance(areas, list) or not areas or any(not isinstance(p, str) for p in areas) or len(set(areas)) != len(areas):
            raise InstallError(f"invalid source scope: {name}")
        for area in areas:
            relative(area, root=True)
            if not target_path(target, area, root=True).exists():
                raise InstallError(f"source scope does not exist: {area}")
        # A domain owns its OpenSpec metadata separately from its source scope.
        # Check both directions without widening the persisted code_roots.
        metadata = join(root, "openspec")
        target_path(target, metadata)
        for area in dict.fromkeys([*areas, metadata, workflow_name(root)]):
            if any(owner != name and overlap(area, prior) for owner, prior in scopes):
                raise InstallError(f"project area overlaps another domain: {name} ({area})")
            scopes.append((name, area))
        checks = project["checks"]
        if not isinstance(checks, list) or not checks:
            raise InstallError(f"project requires concrete validation commands: {name}")
        for command in checks:
            _argv(command)
        environment = project.get("environment", {})
        if not isinstance(environment, dict) or set(environment) - {"lockfiles", "prepare"}:
            raise InstallError("environment supports lockfiles and prepare lists")
        locks = environment.get("lockfiles", [])
        preparation = environment.get("prepare", [])
        if not isinstance(locks, list) or any(not isinstance(p, str) for p in locks) or len(set(locks)) != len(locks):
            raise InstallError("lockfiles must be a unique list")
        for lock in locks:
            path = target_path(target, lock)
            if path.exists() and not path.is_file():
                raise InstallError(f"declared dependency lock is not a regular file: {lock}")
        if not isinstance(preparation, list):
            raise InstallError("environment prepare must be a list of argv arrays")
        for command in preparation:
            _argv(command)
        exclusions = project.get("evidence_exclude", [])
        if not isinstance(exclusions, list) or any(not isinstance(p, str) for p in exclusions) or len(set(exclusions)) != len(exclusions):
            raise InstallError("evidence_exclude must be a list")
        for path in exclusions:
            target_path(target, path, root=True)


def git_common_dir(target: Path) -> Path:
    result = subprocess.run(["git", "rev-parse", "--show-toplevel", "--git-common-dir"], cwd=target,
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise InstallError("target is not a Git worktree; initialize Git explicitly for a new project before installing")
    lines = result.stdout.splitlines()
    if len(lines) != 2 or Path(lines[0]).resolve() != target.resolve():
        raise InstallError("--target must identify the Git worktree root; use --spec-root for a component")
    common = Path(lines[1])
    common = common if common.is_absolute() else target / common
    return common.resolve()


def guard_active_worktree(target: Path) -> None:
    """Protect runs known to this clone's coordinator, without creating its DB."""
    database = git_common_dir(target) / "agentic-harness/coordination.sqlite3"
    if not database.exists():
        return
    try:
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            records = [(kind, json.loads(data)) for kind, data in connection.execute("SELECT kind,data FROM records")]
        finally:
            connection.close()
        if any(not isinstance(record, dict) for _, record in records):
            raise ValueError("invalid coordinator record")
        claims = {r["id"]: r for kind, r in records if kind == "claim"}
        owned = {key for key, r in claims.items() if Path(r["worktree"]).resolve() == target.resolve()}
        if any(claims[key].get("state") not in {"released", "completed"} for key in owned):
            raise InstallError("target worktree has an active workflow claim; update in a fresh or idle worktree")
        for kind, record in records:
            if kind == "assignment" and record.get("claim") in owned and record.get("state") != "released":
                raise InstallError("target worktree has an unreleased workflow assignment")
            if kind in {"freeze", "pin"} and record.get("active"):
                path = Path(record["path"]).resolve()
                if path == target or path.is_relative_to(target):
                    raise InstallError("target worktree has an active workflow freeze or retained source pin")
    except (sqlite3.Error, KeyError, ValueError, TypeError) as exc:
        if isinstance(exc, InstallError):
            raise
        raise InstallError("cannot safely read the existing workflow coordinator; reconcile it before updating") from exc


def package_payload(source: Path) -> dict[str, bytes]:
    result = {}
    base = source / HARNESS
    for directory in PAYLOAD_DIRECTORIES:
        path = base / directory
        if path.is_symlink():
            raise InstallError(f"source payload contains a symlink: {path}")
        if not path.is_dir():
            raise InstallError(f"source distribution is incomplete: {path}")
        for item in sorted(path.rglob("*")):
            if any(p in {"__pycache__", ".venv", "node_modules"} for p in item.relative_to(path).parts):
                continue
            if item.is_symlink():
                raise InstallError(f"source payload contains a symlink: {item}")
            if item.is_file() and item.suffix not in {".pyc", ".pyo"}:
                result[item.relative_to(source).as_posix()] = item.read_bytes()
    for name in PAYLOAD_FILES:
        path = base / name
        if path.is_symlink():
            raise InstallError(f"source payload contains a symlink: {path}")
        if path.is_file():
            result[f"{HARNESS}/{name}"] = path.read_bytes()
        elif name != "README.md":
            raise InstallError(f"source distribution is incomplete: {path}")
    package = json.loads(result[f"{HARNESS}/package.json"])
    if package.get("dependencies", {}).get("@fission-ai/openspec") != OPENSPEC_VERSION:
        raise InstallError("source distribution has an unexpected OpenSpec pin")
    return result


def adapter_module(source: Path):
    path = source / "tools/adapters.py"
    spec = importlib.util.spec_from_file_location("sdw_install_adapters", path)
    if spec is None or spec.loader is None:
        raise InstallError("source distribution has no adapter generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def isolated_environment(home: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update({
        "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_DATA_HOME": str(home / "data"), "XDG_CACHE_HOME": str(home / "cache"),
        "CODEX_HOME": str(home / "codex"),
        "OPENSPEC_TELEMETRY": "0", "OPENSPEC_NO_ANIMATION": "1", "OPENSPEC_NO_AUTO_CONFIG": "1",
    })
    config = home / "config/openspec/config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"profile": "core", "delivery": "skills"}))
    return environment


def run(command, *, cwd: Path, env=None) -> str:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    except OSError as exc:
        raise InstallError(f"cannot run {command[0]}: {exc.strerror}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise InstallError(f"{command[0]} failed ({result.returncode}): {detail}")
    return result.stdout.strip()


def installed_openspec(target: Path, harness=HARNESS) -> bool:
    package = target_path(target, f"{harness}/node_modules/@fission-ai/openspec/package.json")
    if not package.is_file():
        return False
    try:
        return json.loads(package.read_text()).get("version") == OPENSPEC_VERSION
    except (ValueError, UnicodeError):
        return False


def project_config(target: Path, root: str, *, required=False) -> Path | None:
    candidates = [target_path(target, join(root, "openspec/" + name)) for name in ("config.yaml", "config.yml")]
    configs = [path for path in candidates if path.exists()]
    if len(configs) > 1 or (required and not configs):
        raise InstallError(f"OpenSpec project requires exactly one config.yaml or config.yml: {root}")
    if not configs:
        return None
    config = configs[0]
    if not config.is_file():
        raise InstallError(f"OpenSpec configuration is not a regular file: {root}")
    value = read_yaml(config)
    if not isinstance(value, dict):
        raise InstallError(f"OpenSpec configuration must be a mapping: {root}")
    if value.get("store"):
        raise InstallError("external OpenSpec stores need an explicit migration; local installation was not changed")
    if "schema" in value and (not isinstance(value["schema"], str) or not value["schema"].strip()):
        raise InstallError(f"invalid OpenSpec schema selection: {root}")
    return config


def verify_project_root(target: Path, project: dict, harness=HARNESS) -> None:
    """Ask the pinned CLI to resolve the authority, without relying on cwd guesses."""
    root = target_path(target, project["root"], root=True)
    with tempfile.TemporaryDirectory(prefix="sdw-doctor-") as temporary:
        environment = isolated_environment(Path(temporary) / "user")
        output = run(["node", str(target / harness / "tools/openspec.mjs"), "list", "--json"], cwd=root, env=environment)
    try:
        reported = json.loads(output)["root"]["path"]
        if Path(reported).resolve() != root.resolve():
            raise InstallError("OpenSpec resolved an unexpected project root")
    except (ValueError, KeyError, TypeError) as exc:
        raise InstallError(f"OpenSpec did not resolve the registered project: {project['root']}") from exc


def render_upstream(source: Path, target: Path, registry: dict, registrations: dict) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """Return pristine upstream-owned files and new user-owned configuration.

    Existing config is copied only into the isolated render project, where
    upstream init must preserve it byte-for-byte. Product specs are never copied
    or rewritten. Existing native files are compared by the installation plan.
    """
    helper = source / HARNESS / "tools/openspec.mjs"
    if not installed_openspec(source):
        raise InstallError(f"install the source toolchain first: npm --prefix {source / HARNESS} ci --ignore-scripts")
    outputs, initial = {}, {}
    with tempfile.TemporaryDirectory(prefix="sdw-upstream-") as temporary:
        stage = Path(temporary)
        env = isolated_environment(stage / "user")
        for name, project in registry["projects"].items():
            project_stage = stage / "projects" / name
            project_stage.mkdir(parents=True)
            root = project["root"]
            actual = target_path(target, root, root=True)
            config = project_config(target, root)
            configs = [config] if config is not None else []
            previous = {}
            for config in configs:
                rel = config.relative_to(target).as_posix()
                target_path(target, rel)
                destination = project_stage / "openspec" / config.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                previous[destination] = config.read_bytes()
                destination.write_bytes(config.read_bytes())
            schemas = actual / "openspec/schemas"
            if schemas.exists():
                target_path(target, schemas.relative_to(target).as_posix())
                for path in schemas.rglob("*"):
                    target_path(target, path.relative_to(target).as_posix())
                shutil.copytree(schemas, project_stage / "openspec/schemas")
            selected = registrations[name]["agents"]
            run(["node", str(helper), "init", str(project_stage), "--tools", ",".join(selected), "--profile", "core", "--no-animation"], cwd=stage, env=env)
            for path, content in previous.items():
                if not path.is_file() or path.read_bytes() != content:
                    raise InstallError("upstream init changed existing configuration; installation was stopped")
            for native_root in (".agents/skills", ".claude/skills"):
                directory = project_stage / native_root
                if not directory.exists():
                    continue
                for path in directory.rglob("*"):
                    if path.is_file():
                        local = path.relative_to(project_stage).as_posix()
                        # Every byte here belongs to the upstream generator.
                        outputs[join(root, local)] = path.read_bytes()
            if not configs:
                config = project_stage / "openspec/config.yaml"
                if not config.is_file():
                    raise InstallError("OpenSpec did not create its configuration")
                initial[join(root, "openspec/config.yaml")] = config.read_bytes()
    return outputs, initial


@dataclass
class Plan:
    target: Path
    writes: dict[str, bytes]
    removals: list[str]
    directories: list[str]
    dependencies: bool
    manifest: dict
    before: dict[str, bytes | None] = field(default_factory=dict)
    readset: dict = field(default_factory=dict)
    toolchain: dict[str, bytes] = field(default_factory=dict)
    legacy_root: str | None = None
    retained: list[str] = field(default_factory=list)
    before_modes: dict[str, int] = field(default_factory=dict)
    write_modes: dict[str, int] = field(default_factory=dict)
    directory_modes: dict[str, int] = field(default_factory=dict)
    links: dict[str, str] = field(default_factory=dict)
    link_removals: list[str] = field(default_factory=list)
    conversions: list[str] = field(default_factory=list)
    moves: list[dict] = field(default_factory=list)
    coalesced: list[dict] = field(default_factory=list)
    directory_removals: list[str] = field(default_factory=list)

    def summary(self, *, dry_run=False) -> dict:
        summary = {"status": "planned" if dry_run else "installed", "workflow_version": VERSION,
                "openspec_version": OPENSPEC_VERSION, "changed": sorted(self.writes),
                "removed": sorted(self.removals), "create_directories": self.directories,
                "install_toolchain": self.dependencies, "projects": sorted(self.manifest["projects"]),
                "payload_sha256": self.manifest["payload_sha256"],
                "links": self.links, "removed_links": self.link_removals, "conversions": self.conversions,
                "moves": self.moves, "coalesced": self.coalesced,
                "removed_directories": self.directory_removals}
        if self.legacy_root:
            summary["migration"] = {"from": self.legacy_root, "to": HARNESS}
            summary["retained"] = self.retained
        if self.retained:
            summary["retained"] = self.retained
        if dry_run:
            summary["diffs"] = {
                name: "".join(difflib.unified_diff((self.before.get(name) or b"").decode().splitlines(keepends=True),
                                                self.writes.get(name, b"").decode().splitlines(keepends=True),
                                                fromfile="a/" + name, tofile="b/" + name))
                for name in sorted(set(self.writes) | set(self.removals))
            }
            summary["file_hashes"] = {name: digest(value) for name, value in sorted(self.writes.items())}
        return summary


def state_at(descriptor: int, leaf: str, name: str):
    """Read one lexical object via a pinned parent without following its leaf."""
    try:
        info = os.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        try:
            expected_target(name)
        except ValueError as exc:
            raise InstallError(f"installation path is a symlink: {name}") from exc
        return {"kind": "directory_symlink", "target": os.readlink(leaf, dir_fd=descriptor)}
    if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
        raise InstallError(f"unsupported target file type: {name}")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if stat.S_ISDIR(info.st_mode):
        flags |= os.O_DIRECTORY
    fd = os.open(leaf, flags, dir_fd=descriptor)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_mode) != (info.st_dev, info.st_ino, info.st_mode):
            raise InstallError(f"target changed while observing installation: {name}")
        if stat.S_ISDIR(info.st_mode):
            return {"directory": sorted(os.listdir(fd)), "mode": stat.S_IMODE(info.st_mode),
                    "identity": [info.st_dev, info.st_ino]}
        sha = hashlib.sha256()
        while data := os.read(fd, 1024 * 1024):
            sha.update(data)
        after = os.fstat(fd)
        current = os.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
        if (after.st_mtime_ns, after.st_size, after.st_mode, current.st_dev, current.st_ino) != (info.st_mtime_ns, info.st_size, info.st_mode, info.st_dev, info.st_ino):
            raise InstallError(f"target changed while observing installation: {name}")
        return {"file": sha.hexdigest(), "mode": stat.S_IMODE(info.st_mode)}
    finally:
        os.close(fd)


def observe(target: Path, name: str):
    """Fingerprint absent/files/directories and finite link leaves without aliases."""
    relative(name, root=name == ".")
    path = target / name
    if name == "CLAUDE.md" and path.is_symlink() and path.resolve() == (target / "AGENTS.md").resolve():
        return {"symlink": os.readlink(path)}
    try:
        if name == ".":
            descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                return state_at(descriptor, ".", name)
            finally:
                os.close(descriptor)
        with parent_handle(target, name) as descriptor:
            return state_at(descriptor, Path(name).name, name)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InstallError(f"unsafe or changed installation path (symlink or non-directory): {name}") from exc


def remember(target: Path, name: str, readset: dict) -> None:
    for parent in reversed(Path(name).parents):
        relative_name = parent.as_posix()
        if relative_name not in readset:
            readset[relative_name] = observe(target, relative_name)
    if name not in readset:
        readset[name] = observe(target, name)


def check_readset(target: Path, readset: dict) -> None:
    for name, expected in readset.items():
        if observe(target, name) != expected:
            raise InstallError(f"target changed while preparing installation: {name}")


def retained_legacy_paths(target: Path, owned: set[str], readset: dict) -> list[str]:
    """Inventory only owned-tree boundaries, never traverse unowned caches."""
    retained = []

    def visit(name):
        if name not in readset:
            remember(target, name, readset)
        for path in sorted(target_path(target, name).iterdir()):
            relative_name = path.relative_to(target).as_posix()
            if relative_name in owned:
                continue
            if path.is_dir() and not path.is_symlink():
                if any(item.startswith(relative_name + "/") for item in owned):
                    visit(relative_name)
                else:
                    retained.append(relative_name + "/")
            else:
                retained.append(relative_name)

    visit(LEGACY_HARNESS)
    return retained


def validate_migration_bindings(registry: dict, moved: set[str]) -> None:
    """Local executable policy must be deliberately adjusted, never rewritten."""
    legacy_argument = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(LEGACY_HARNESS) + r"(?=$|[^A-Za-z0-9_.-])")
    for project in registry["projects"].values():
        settings = workflow_name(project["root"])
        paths = project["code_roots"] + project.get("environment", {}).get("lockfiles", [])
        for path in paths:
            # Whole-repository scope remains valid; a legacy-specific scope or
            # dependency binding cannot silently follow the renamed payload.
            if path.startswith(LEGACY_HARNESS) and any(overlap(path, name) for name in moved):
                raise InstallError(f"legacy package path in {settings}: {path}; update local scope or lockfile bindings before migration")
        commands = project["checks"] + project.get("environment", {}).get("prepare", [])
        if any(legacy_argument.search(argument) for command in commands for argument in command):
            raise InstallError(f"legacy package command in {settings}; update explicit {LEGACY_HARNESS} arguments before migration")


def dependency_document(path: Path) -> list:
    try:
        return parse_dependency_map(path.read_text(), label=str(path))
    except (ValueError, UnicodeError) as exc:
        raise InstallError(f"invalid dependency map: {path}: {exc}") from exc


def validate_removed_bindings(registry: dict, removed: set[str]) -> None:
    for project in registry["projects"].values():
        settings = workflow_name(project["root"])
        paths = project["code_roots"] + project.get("environment", {}).get("lockfiles", [])
        for path in paths:
            if path not in {".", project["root"]} and any(overlap(path, name) for name in removed):
                raise InstallError(f"removed input path in {settings}: {path}; reconcile local bindings before migration")
        for command in project["checks"] + project.get("environment", {}).get("prepare", []):
            for argument in command:
                if any(re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(name) + r"(?=$|[^A-Za-z0-9_.-])", argument) for name in removed):
                    raise InstallError(f"removed input command in {settings}; reconcile local bindings before migration")


def build_plan(target: Path, source: Path, registry: dict, registrations: dict, old: dict | None, readset=None, *, old_harness=HARNESS) -> Plan:
    readset = dict(readset or {})
    validate_registry(target, registry)
    migrating = old is not None and old_harness == LEGACY_HARNESS
    watched = {MANIFEST, REGISTRY, "AGENTS.md", "CLAUDE.md", f"{HARNESS}/node_modules",
               f"{HARNESS}/node_modules/@fission-ai/openspec/package.json"}
    if old:
        watched.update(old["managed"])
        watched.update(old["upstream"])
        watched.update(old.get("links", {}))
    for project in registry["projects"].values():
        watched.add(project["root"])
        watched.update(project["code_roots"])
        watched.update(project.get("environment", {}).get("lockfiles", []))
        watched.update(join(project["root"], "openspec/" + name) for name in ("config.yaml", "config.yml", "workflow.yaml", "queue.yaml", "dependency-map.yaml", "changes", "schemas"))
        schemas = target_path(target, join(project["root"], "openspec/schemas"))
        if schemas.exists():
            watched.update(path.relative_to(target).as_posix() for path in schemas.rglob("*"))
    for name in watched:
        if name not in readset:
            remember(target, name, readset)
    for name in discovery_links(AGENTS):
        remember(target, name, readset)
    # Capture before verifying ownership or invoking generators. A concurrent
    # edit must not become a newly trusted baseline after ownership was checked.
    verify_owned(target, old)
    check_readset(target, readset)
    legacy_metadata = {f"{LEGACY_HARNESS}/{name}" for name in ("install.json", "projects.yaml")}
    retained = []
    if migrating:
        moved = {name for name in old["managed"] if name.startswith(LEGACY_HARNESS + "/")} | legacy_metadata
        validate_migration_bindings(registry, moved)
        retained = retained_legacy_paths(target, moved, readset)
        if target_path(target, f"{HARNESS}/node_modules").exists():
            raise InstallError("existing canonical dependency directory conflicts with legacy migration")
    payload = package_payload(source)
    modules = adapter_module(source)
    selected_agents = sorted({agent for item in registrations.values() for agent in item["agents"]})
    link_targets = discovery_links(selected_agents)
    generated = modules.outputs(registry, selected_agents)
    managed = dict(payload)
    for name, text in generated.items():
        relative(name)
        if not managed_path(name) or name.startswith(HARNESS + "/"):
            raise InstallError(f"adapter generator exceeded its namespace: {name}")
        if "openspec-" in name or "/opsx/" in name or name.endswith(("config.toml", "settings.json")):
            raise InstallError(f"adapter generator overlaps upstream or user settings: {name}")
        managed[name] = text.encode()
    upstream, initial = render_upstream(source, target, registry, registrations)
    intended = {**managed, **upstream, **initial}
    # New destinations also enter the read set before any conflict decision.
    for name in intended:
        if name not in readset:
            remember(target, name, readset)
    for name, contents in {**managed, **upstream}.items():
        path = target_path(target, name)
        owned = old is not None and (name in old["managed"] or name in old["upstream"])
        if path.exists() and not path.is_file():
            raise InstallError(f"installation would replace a non-file: {name}")
        if path.is_file() and not owned and path.read_bytes() != contents:
            raise InstallError(f"existing file conflicts with installation: {name}; preserve its customizations outside managed files first")
    current_registry = target_path(target, REGISTRY)
    index = {"schema_version": 3, "projects": {name: {"root": project["root"]}
             for name, project in registry["projects"].items()}}
    if not current_registry.exists() or read_yaml(current_registry) != index:
        intended[REGISTRY] = yaml.safe_dump(index, sort_keys=False).encode()
    migration_removals = []
    moves = []
    coalesced = []
    migration_modes = {}
    indexed = read_yaml(target_path(target, f"{old_harness}/projects.yaml")) if target_path(target, f"{old_harness}/projects.yaml").is_file() else None
    indexed_version = indexed["schema_version"] if indexed else None
    for project in registry["projects"].values():
        root = project["root"]
        settings = workflow_settings(project)
        destination = workflow_name(root)
        legacy = workflow_name(root, 2)
        local = read_workflow(target, root, readset=readset)
        prior = read_workflow(target, root, readset=readset, schema_version=2)
        if local is not None and local != settings or prior is not None and prior != settings:
            raise InstallError(f"existing workflow configuration differs: {destination}; edit it explicitly and use update")
        if local is None:
            if prior is not None:
                intended[destination] = target_path(target, legacy).read_bytes()
                migration_modes[destination] = readset[legacy]["mode"]
            else:
                intended[destination] = yaml.safe_dump({"schema_version": 1, **settings}, sort_keys=False).encode()
        if prior is not None:
            migration_removals.append(legacy)
            (coalesced if local is not None else moves).append({"from": legacy, "to": destination})
        old_map = join(root, "openspec/queue.yaml")
        new_map = join(root, "openspec/dependency-map.yaml")
        maps = {}
        for name in (old_map, new_map):
            if name not in readset:
                remember(target, name, readset)
            path = target_path(target, name)
            if path.exists():
                maps[name] = dependency_document(path)
        if indexed and root in {p["root"] for p in indexed["projects"].values()}:
            authority = new_map if indexed_version == 3 else old_map
            if authority not in maps:
                raise InstallError(f"missing indexed dependency map: {authority}")
        if old_map in maps and new_map in maps and maps[old_map] != maps[new_map]:
            raise InstallError(f"dependency map conflicts with legacy queue: {new_map}")
        if new_map not in maps:
            if old_map in maps:
                intended[new_map] = target_path(target, old_map).read_bytes()
                migration_modes[new_map] = readset[old_map]["mode"]
            else:
                changes = target_path(target, join(root, "openspec/changes"))
                if changes.exists() and any(p.is_dir() and p.name != "archive" for p in changes.iterdir()):
                    raise InstallError(f"existing changes require an explicit dependency queue: {new_map}")
                intended[new_map] = b"queue: []\n"
        if old_map in maps:
            migration_removals.append(old_map)
            (coalesced if new_map in maps else moves).append({"from": old_map, "to": new_map})
    validate_removed_bindings(registry, set(migration_removals) | {name for name in (old or {}).get("managed", {}) if name not in managed and "/skills/sdw-" in name})
    bodies = {}
    for name in ("AGENTS.md", "CLAUDE.md"):
        if name == "CLAUDE.md" and "claude" not in selected_agents and name not in (old or {}).get("blocks", {}):
            continue
        path = target / name
        if name == "CLAUDE.md" and path.is_symlink() and path.resolve() == (target / "AGENTS.md").resolve():
            continue
        path = target_path(target, name)
        previous = path.read_text() if path.exists() else ""
        existing = block(previous)
        if existing and (old is None or name not in old["blocks"]):
            raise InstallError(f"unowned workflow block in {name}")
        merged = merge_block(previous, modules.entrypoint(registry))
        intended[name] = merged.encode()
        bodies[name] = digest(block(merged).encode())
    payload_hash = digest(encoded({name: digest(value) for name, value in sorted(payload.items())}))
    registrations = {name: {"agents": record["agents"], "root": registry["projects"][name]["root"]} for name, record in registrations.items()}
    if any(not upstream_path(name, registrations) for name in upstream):
        raise InstallError("upstream generator emitted a file outside its namespace")
    manifest = {
        "schema_version": 2, "workflow_version": VERSION, "openspec_version": OPENSPEC_VERSION,
        "payload_sha256": payload_hash,
        "registry_sha256": digest(encoded(registry)),
        "managed": {name: digest(value) for name, value in sorted(managed.items())},
        "upstream": {name: digest(value) for name, value in sorted(upstream.items())},
        "blocks": bodies, "projects": registrations,
        "links": {name: {"kind": "directory_symlink", "target": target} for name, target in link_targets.items()},
    }
    intended[MANIFEST] = encoded(manifest)
    removals = sorted((set(old["managed"]) | set(old["upstream"])) - set(managed) - set(upstream)) if old else []
    removals = sorted(set(removals) | set(migration_removals))
    conversions = []
    directory_removals = []
    for name, literal in link_targets.items():
        if name not in readset:
            remember(target, name, readset)
        state = readset[name]
        owned_link = (old or {}).get("links", {}).get(name)
        if state is None:
            continue
        if owned_link is not None:
            continue
        child = name + "/SKILL.md"
        if (not isinstance(state, dict) or state.get("directory") != ["SKILL.md"]
                or child not in (old or {}).get("managed", {}) or child not in removals):
            raise InstallError(f"unowned or nonempty discovery directory conflicts with link conversion: {name}")
        conversions.append(name)
    for name in sorted(set(discovery_links(AGENTS)) - set(link_targets)):
        child = name + "/SKILL.md"
        if child in removals and child in (old or {}).get("managed", {}):
            state = readset[name]
            if not isinstance(state, dict) or state.get("directory") != ["SKILL.md"]:
                raise InstallError(f"nonempty legacy discovery directory conflicts with removal: {name}")
            directory_removals.append(name)
    link_changes = {name: literal for name, literal in link_targets.items() if not (old or {}).get("links", {}).get(name)}
    link_removals = sorted(set((old or {}).get("links", {})) - set(link_targets))
    if migrating:
        removals = sorted(set(removals) | legacy_metadata)
        legacy_ignore = f"{LEGACY_HARNESS}/.gitignore"
        if retained and legacy_ignore in removals:
            removals.remove(legacy_ignore)
            retained.append(legacy_ignore)
    for name in removals:
        target_path(target, name)
    directories = sorted({join(p["root"], "openspec/" + leaf) for p in registry["projects"].values() for leaf in ("specs", "changes") if not target_path(target, join(p["root"], "openspec/" + leaf)).exists()})
    before, writes = {}, {}
    for name, value in intended.items():
        path = target_path(target, name)
        prior = path.read_bytes() if path.is_file() else None
        if name not in readset:
            remember(target, name, readset)
        if prior != value:
            writes[name] = value
            before[name] = prior
    for name in removals:
        before[name] = target_path(target, name).read_bytes()
    before_modes = {name: stat.S_IMODE(target_path(target, name).stat().st_mode)
                    for name, content in before.items() if content is not None}
    write_modes = dict(migration_modes)
    directory_modes = {}
    if migrating:
        owned_directories = {LEGACY_HARNESS}
        for name in moved:
            owned_directories.update(parent.as_posix() for parent in Path(name).parents
                                     if parent.as_posix().startswith(LEGACY_HARNESS + "/"))
        for name in writes:
            if before[name] is None and name.startswith(HARNESS + "/"):
                previous = LEGACY_HARNESS + name[len(HARNESS):]
                if previous in moved:
                    write_modes[name] = stat.S_IMODE(target_path(target, previous).stat().st_mode)
            if name.startswith(HARNESS + "/"):
                for parent in Path(name).parents:
                    canonical = parent.as_posix()
                    if canonical != HARNESS and not canonical.startswith(HARNESS + "/"):
                        break
                    previous = LEGACY_HARNESS + canonical[len(HARNESS):]
                    if previous not in owned_directories:
                        continue
                    for directory in (previous, canonical):
                        if directory not in readset:
                            readset[directory] = observe(target, directory)
                    destination = target_path(target, canonical)
                    if destination.exists() and not destination.is_dir():
                        raise InstallError(f"existing package directory conflicts with migration: {canonical}")
                    if not destination.exists():
                        directory_modes[canonical] = readset[previous]["mode"]
    dependency_change = not installed_openspec(target) or any(name in writes for name in (f"{HARNESS}/package.json", f"{HARNESS}/package-lock.json"))
    check_readset(target, readset)
    toolchain = {name: payload[f"{HARNESS}/{name}"] for name in ("package.json", "package-lock.json")}
    return Plan(target, writes, removals, directories, dependency_change, manifest, before, readset, toolchain,
                LEGACY_HARNESS if migrating else None, sorted(retained), before_modes, write_modes,
                directory_modes, link_changes, link_removals, conversions, moves, coalesced, directory_removals)


def prepare_dependencies(source: Path, temporary: Path) -> Path:
    package = temporary / "toolchain"
    package.mkdir()
    for name in ("package.json", "package-lock.json"):
        shutil.copyfile(source / HARNESS / name, package / name)
    environment = isolated_environment(temporary / "npm-user")
    environment["npm_config_cache"] = str(temporary / "npm-cache")
    run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=package, env=environment)
    installed = package / "node_modules/@fission-ai/openspec/package.json"
    if not installed.is_file() or json.loads(installed.read_text()).get("version") != OPENSPEC_VERSION:
        raise InstallError("prepared OpenSpec toolchain does not match the pinned version")
    return package / "node_modules"


def atomic_write(path: Path, content: bytes, *, mode: int | None = None) -> None:
    """A failed write never truncates the previous destination."""
    if mode is None:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    _atomic_write(path, content, mode)


_WRITE_HANDLES = {}
_WRITE_GUARDS = {}


def _atomic_write(path: Path, content: bytes, mode: int) -> None:
    """Publish through a pinned no-follow parent, including during rollback."""
    owned = path not in _WRITE_HANDLES
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) if owned else _WRITE_HANDLES[path]
    temporary = ".sdw-write-" + uuid.uuid4().hex
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=descriptor)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        if path in _WRITE_GUARDS:
            _WRITE_GUARDS[path](descriptor)
        os.replace(temporary, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
    finally:
        try:
            os.unlink(temporary, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        if owned:
            os.close(descriptor)


@contextmanager
def parent_handle(root: Path, name: str):
    """Walk real directories with openat; a swapped ancestor cannot redirect a write."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in Path(name).parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def copy_tree_at(source: Path, parent: int, leaf: str) -> None:
    """Copy the prepared opaque dependency tree through pinned destination handles."""
    os.mkdir(leaf, dir_fd=parent)
    descriptor = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        for child in source.iterdir():
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode):
                os.symlink(os.readlink(child), child.name, dir_fd=descriptor)
            elif stat.S_ISDIR(info.st_mode):
                copy_tree_at(child, descriptor, child.name)
            elif stat.S_ISREG(info.st_mode):
                fd = os.open(child.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, stat.S_IMODE(info.st_mode), dir_fd=descriptor)
                with child.open("rb") as src, os.fdopen(fd, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                    os.fchmod(dst.fileno(), stat.S_IMODE(info.st_mode))
            else:
                raise InstallError("prepared dependencies contain an unsupported file type")
        os.fchmod(descriptor, stat.S_IMODE(source.stat().st_mode))
    finally:
        os.close(descriptor)


def opaque_state_at(parent: int, leaf: str):
    """Typed inert identity for the prepared dependency tree, including .bin links."""
    info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        return {"link": os.readlink(leaf, dir_fd=parent)}
    fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if stat.S_ISDIR(info.st_mode) else 0), dir_fd=parent)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise InstallError("dependency tree changed during observation")
        if stat.S_ISDIR(info.st_mode):
            return {"directory": {name: opaque_state_at(fd, name) for name in sorted(os.listdir(fd))},
                    "mode": mode, "identity": [info.st_dev, info.st_ino]}
        if not stat.S_ISREG(info.st_mode):
            raise InstallError("unsupported dependency-tree object")
        sha = hashlib.sha256()
        while data := os.read(fd, 1024 * 1024):
            sha.update(data)
        after = os.fstat(fd)
        if (after.st_mtime_ns, after.st_size, after.st_mode) != (info.st_mtime_ns, info.st_size, info.st_mode):
            raise InstallError("dependency file changed during observation")
        return {"file": sha.hexdigest(), "mode": mode}
    finally:
        os.close(fd)


def remove_tree_at(parent: int, leaf: str, expected) -> None:
    """Remove only the verified original poststate through pinned handles."""
    if opaque_state_at(parent, leaf) != expected:
        raise InstallError("dependency tree changed after publication")
    if "directory" not in expected:
        os.unlink(leaf, dir_fd=parent)
        return
    fd = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        for name, state in expected["directory"].items():
            remove_tree_at(fd, name, state)
        info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        if [info.st_dev, info.st_ino] != expected["identity"]:
            raise InstallError("dependency directory changed during removal")
        os.rmdir(leaf, dir_fd=parent)
    finally:
        os.close(fd)


def apply_plan(plan: Plan, source: Path) -> None:
    """Recheck every typed mutation; rollback only uncontested recorded poststates."""
    with tempfile.TemporaryDirectory(prefix="sdw-install-") as temporary:
        temporary = Path(temporary)
        pinned_source = temporary / "distribution"
        (pinned_source / HARNESS).mkdir(parents=True)
        for name, content in plan.toolchain.items():
            (pinned_source / HARNESS / name).write_bytes(content)
        dependencies = prepare_dependencies(pinned_source, temporary) if plan.dependencies else None
        guard_active_worktree(plan.target)
        check_readset(plan.target, plan.readset)
        expected = dict(plan.readset)
        applied = []
        old_dependencies = None
        new_dependencies = None
        dependency_handle = None
        dependency_poststate = None
        old_dependency_state = None
        recovery = []

        def recheck():
            check_readset(plan.target, expected)

        def parent_entry(name, present):
            parent = Path(name).parent.as_posix()
            state = expected[parent]
            entries = set(state["directory"])
            if present:
                entries.add(Path(name).name)
            else:
                entries.discard(Path(name).name)
            expected[parent] = {**state, "directory": sorted(entries)}

        def ensure_directory(name):
            if name == ".":
                return
            if name not in expected:
                # Its parent was observed before any child operation.
                remember(plan.target, name, expected)
            state = expected[name]
            if state is not None:
                if "directory" not in state:
                    raise InstallError(f"installation parent is not a real directory: {name}")
                return
            ensure_directory(Path(name).parent.as_posix())
            recheck()
            with parent_handle(plan.target, name) as fd:
                os.mkdir(Path(name).name, plan.directory_modes.get(name, 0o777), dir_fd=fd)
                if name in plan.directory_modes:
                    os.chmod(Path(name).name, plan.directory_modes[name], dir_fd=fd, follow_symlinks=False)
                mode = stat.S_IMODE(os.stat(Path(name).name, dir_fd=fd, follow_symlinks=False).st_mode)
            info = (plan.target / name).lstat()
            after = {"directory": [], "mode": mode, "identity": [info.st_dev, info.st_ino]}
            applied.append((name, None, None, after))
            expected[name] = after
            parent_entry(name, True)

        def publication_guard(name, before, descriptor):
            """Revalidate the lexical parent and leaf after replacement staging."""
            try:
                identity = expected[Path(name).parent.as_posix()]["identity"]
                pinned = os.fstat(descriptor)
                with parent_handle(plan.target, name) as current:
                    info = os.fstat(current)
                    if ([info.st_dev, info.st_ino] != identity
                            or [pinned.st_dev, pinned.st_ino] != identity):
                        raise InstallError(f"target parent changed before publication: {name}")
                if state_at(descriptor, Path(name).name, name) != before:
                    raise InstallError(f"target changed before publication: {name}")
            except (OSError, ValueError):
                recovery.append(name)
                raise

        def mutate(name, kind, *, content=None, literal=None):
            ensure_directory(Path(name).parent.as_posix())
            recheck()
            before = expected.get(name)
            prior = plan.before.get(name)
            path = plan.target / name
            with parent_handle(plan.target, name) as fd:
                info = os.fstat(fd)
                if [info.st_dev, info.st_ino] != expected[Path(name).parent.as_posix()]["identity"]:
                    raise InstallError(f"target parent changed while preparing installation: {name}")
                if state_at(fd, Path(name).name, name) != before:
                    raise InstallError(f"target changed before installation operation: {name}")
                if kind == "write":
                    mode = plan.write_modes.get(name, before.get("mode", 0o644) if before else 0o644)
                    _WRITE_HANDLES[path] = fd
                    _WRITE_GUARDS[path] = lambda descriptor: publication_guard(name, before, descriptor)
                    try:
                        atomic_write(path, content, mode=mode)
                    finally:
                        _WRITE_HANDLES.pop(path, None)
                        _WRITE_GUARDS.pop(path, None)
                    after = {"file": digest(content), "mode": mode}
                elif kind == "unlink":
                    os.unlink(Path(name).name, dir_fd=fd)
                    after = None
                elif kind == "rmdir":
                    os.rmdir(Path(name).name, dir_fd=fd)
                    after = None
                elif kind == "link":
                    temporary_name = ".sdw-link-" + uuid.uuid4().hex
                    try:
                        os.symlink(literal, temporary_name, dir_fd=fd)
                        publication_guard(name, before, fd)
                        os.replace(temporary_name, Path(name).name, src_dir_fd=fd, dst_dir_fd=fd)
                    finally:
                        try:
                            os.unlink(temporary_name, dir_fd=fd)
                        except FileNotFoundError:
                            pass
                    after = {"kind": "directory_symlink", "target": literal}
                else:
                    raise InstallError("unknown installation operation")
            applied.append((name, before, prior, after))
            expected[name] = after
            if kind == "link":
                for descendant in list(expected):
                    if descendant.startswith(name + "/"):
                        del expected[descendant]
            parent_entry(name, after is not None)

        try:
            for name in plan.directories:
                ensure_directory(name)
            # Canonical payload and consumer authorities precede structural discovery changes.
            for name in sorted(set(plan.writes) - {MANIFEST, REGISTRY}):
                mutate(name, "write", content=plan.writes[name])
            for name in plan.removals:
                mutate(name, "unlink")
            for name in plan.conversions + plan.directory_removals:
                mutate(name, "rmdir")
            for name in plan.link_removals:
                mutate(name, "unlink")
            for name, literal in plan.links.items():
                mutate(name, "link", literal=literal)
            if dependencies is not None:
                recheck()
                destination = target_path(plan.target, f"{HARNESS}/node_modules")
                ensure_directory(HARNESS)
                # Dependency preparation has no target writes. Keep the parent pinned
                # through staging and rename; copytree receives its verified real path.
                with parent_handle(plan.target, f"{HARNESS}/node_modules") as fd:
                    dependency_handle = os.dup(fd)
                    info = os.fstat(fd)
                    if [info.st_dev, info.st_ino] != expected[HARNESS]["identity"]:
                        raise InstallError("dependency parent changed before publication")
                    new_dependencies = destination.parent / (".sdw-deps-" + uuid.uuid4().hex)
                    copy_tree_at(dependencies, fd, new_dependencies.name)
                    dependency_poststate = opaque_state_at(fd, new_dependencies.name)
                    staged_name = new_dependencies.relative_to(plan.target).as_posix()
                    parent_entry(staged_name, True)
                    recheck()
                    if state_at(fd, "node_modules", f"{HARNESS}/node_modules") != expected[f"{HARNESS}/node_modules"]:
                        raise InstallError("dependency destination changed before publication")
                    if expected[f"{HARNESS}/node_modules"] is not None:
                        old_dependency_state = opaque_state_at(fd, "node_modules")
                        old_dependencies = destination.parent / (".sdw-old-deps-" + uuid.uuid4().hex)
                        os.rename("node_modules", old_dependencies.name, src_dir_fd=fd, dst_dir_fd=fd)
                    os.rename(new_dependencies.name, "node_modules", src_dir_fd=fd, dst_dir_fd=fd)
                    new_dependencies = destination
                    parent_entry(staged_name, False)
                # Only the dependency subtree and its parent's known temporary entries changed.
                expected[f"{HARNESS}/node_modules"] = observe(plan.target, f"{HARNESS}/node_modules")
                for name in list(expected):
                    if name.startswith(f"{HARNESS}/node_modules/"):
                        expected[name] = observe(plan.target, name)
                parent_entry(f"{HARNESS}/node_modules", True)
                if old_dependencies is not None:
                    parent_entry(old_dependencies.relative_to(plan.target).as_posix(), True)
            if REGISTRY in plan.writes:
                mutate(REGISTRY, "write", content=plan.writes[REGISTRY])
            if MANIFEST in plan.writes:
                mutate(MANIFEST, "write", content=plan.writes[MANIFEST])
        except BaseException as failure:
            # Preserve a concurrently changed dependency tree rather than deleting it.
            if dependency_handle is not None:
                try:
                    if new_dependencies is not None:
                        if dependency_poststate is None:
                            recovery.append(new_dependencies.relative_to(plan.target).as_posix())
                        else:
                            remove_tree_at(dependency_handle, new_dependencies.name, dependency_poststate)
                    if old_dependencies is not None:
                        if opaque_state_at(dependency_handle, old_dependencies.name) != old_dependency_state:
                            raise InstallError("old dependency tree changed during installation")
                        try:
                            os.stat("node_modules", dir_fd=dependency_handle, follow_symlinks=False)
                        except FileNotFoundError:
                            os.rename(old_dependencies.name, "node_modules", src_dir_fd=dependency_handle, dst_dir_fd=dependency_handle)
                        else:
                            raise InstallError("dependency destination changed during rollback")
                except (OSError, ValueError):
                    recovery.append(f"{HARNESS}/node_modules")
                    if old_dependencies is not None:
                        recovery.append(old_dependencies.relative_to(plan.target).as_posix())
                finally:
                    os.close(dependency_handle)
                    dependency_handle = None
            for name, before, prior, after in reversed(applied):
                try:
                    current = observe(plan.target, name)
                    if current != after:
                        recovery.append(name)
                        continue
                    with parent_handle(plan.target, name) as fd:
                        # Observation and mutation must concern the same real parent,
                        # including directories restored earlier in reverse traversal.
                        publication_guard(name, after, fd)
                        leaf = Path(name).name
                        if before is None:
                            if after is not None:
                                if "directory" in after:
                                    os.rmdir(leaf, dir_fd=fd)
                                else:
                                    os.unlink(leaf, dir_fd=fd)
                        elif "directory" in before:
                            os.mkdir(leaf, before["mode"], dir_fd=fd)
                            os.chmod(leaf, before["mode"], dir_fd=fd, follow_symlinks=False)
                            expected[name] = state_at(fd, leaf, name)
                        elif "file" in before:
                            path = plan.target / name
                            _WRITE_HANDLES[path] = fd
                            _WRITE_GUARDS[path] = lambda descriptor: publication_guard(name, after, descriptor)
                            try:
                                _atomic_write(path, prior, before["mode"])
                            finally:
                                _WRITE_HANDLES.pop(path, None)
                                _WRITE_GUARDS.pop(path, None)
                        else:
                            os.symlink(before["target"], leaf, dir_fd=fd)
                except (OSError, ValueError):
                    recovery.append(name)
            if recovery:
                raise InstallError("installation failed; concurrent changes preserved; recovery required: " + ", ".join(sorted(set(recovery)))) from failure
            raise
        else:
            if dependency_handle is not None:
                try:
                    if old_dependencies is not None:
                        remove_tree_at(dependency_handle, old_dependencies.name, old_dependency_state)
                except (OSError, ValueError):
                    plan.retained.append(old_dependencies.relative_to(plan.target).as_posix())
                finally:
                    os.close(dependency_handle)
            if plan.legacy_root:
                parents = set()
                legacy = plan.target / plan.legacy_root
                for name in plan.removals:
                    path = (plan.target / name).parent
                    while path == legacy or path.is_relative_to(legacy):
                        parents.add(path)
                        path = path.parent
                for path in sorted(parents, key=lambda p: len(p.parts), reverse=True):
                    try:
                        if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                            with parent_handle(plan.target, path.relative_to(plan.target).as_posix()) as fd:
                                os.rmdir(path.name, dir_fd=fd)
                    except OSError:
                        continue


def installation(target: Path, *, project: str | None = None, spec_root=".", scopes=None, checks=None, agents=None, lockfiles=None, dry_run=False, source=SOURCE, update=False) -> dict:
    target, source = Path(target).expanduser().resolve(), Path(source).resolve()
    if not target.is_dir():
        raise InstallError("target must be an existing repository directory")
    if target == source:
        raise InstallError("install into a consumer repository, not the source distribution")
    guard_active_worktree(target)
    authority_paths = [name for harness in (HARNESS, LEGACY_HARNESS)
                       for name in (harness, f"{harness}/install.json", f"{harness}/projects.yaml")]
    initial_readset = {}
    for name in authority_paths:
        remember(target, name, initial_readset)
    old_harness = installation_layout(target)
    old = load_manifest(target, harness=old_harness)
    if update and old is None:
        raise InstallError("target has no workflow installation to update")
    registry = load_registry(target, readset=initial_readset, harness=old_harness, migration=True)
    validate_registry(target, registry)
    registrations = dict(old["projects"]) if old else {}
    if not update:
        spec_root = relative(spec_root, root=True)
        if project is not None and (not isinstance(project, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", project)):
            raise InstallError("--project requires a lowercase compatibility identifier")
        matching = [name for name, item in registry["projects"].items() if item["root"] == spec_root]
        if matching and project is not None and project != matching[0]:
            raise InstallError("OpenSpec root already has a different stable project identity; omit --project")
        if project in registry["projects"] and registry["projects"][project]["root"] != spec_root:
            raise InstallError("project identity already belongs to a different OpenSpec root")
        project = matching[0] if matching else project or project_identifier(spec_root, registry["projects"])
        previous = registry["projects"].get(project)
        existing = previous
        settings_path = workflow_name(spec_root)
        if previous is not None:
            schema = read_yaml(target_path(target, f"{old_harness}/projects.yaml"))["schema_version"]
            settings_path = workflow_name(spec_root, schema) if schema >= 2 else f"{old_harness}/projects.yaml"
        if existing is None:
            local = read_workflow(target, spec_root, readset=initial_readset)
            legacy_local = read_workflow(target, spec_root, readset=initial_readset, schema_version=2)
            if local is not None and legacy_local is not None and local != legacy_local:
                raise InstallError("workflow configuration conflicts with migration destination")
            if local is None and legacy_local is not None:
                settings_path = workflow_name(spec_root, 2)
            local = local if local is not None else legacy_local
            if local is not None:
                existing = {"root": spec_root, "queue": join(spec_root, "openspec/dependency-map.yaml"), **local}
        default = {"root": spec_root, "queue": join(spec_root, "openspec/dependency-map.yaml"),
                   "code_roots": [spec_root], "checks": [],
                   "environment": {"lockfiles": [], "prepare": []}, "evidence_exclude": []}
        configuration = {**(existing or default)}
        if scopes is not None:
            configuration["code_roots"] = sorted(set(scopes))
        if checks is not None:
            configuration["checks"] = checks
        if lockfiles is not None:
            configuration["environment"] = {**configuration["environment"], "lockfiles": sorted(set(lockfiles))}
        if not configuration["checks"]:
            raise InstallError(f"provide --check commands or checks in {settings_path}")
        if existing is not None and existing != configuration:
            raise InstallError(f"project already has different local configuration; edit {settings_path} explicitly and use update")
        prior_agents = registrations.get(project, {}).get("agents", ["codex", "claude"])
        selected_agents = sorted(set(prior_agents if agents is None else agents))
        if not selected_agents or not set(selected_agents) <= AGENTS:
            raise InstallError("supported agent integrations are codex and claude")
        registry["projects"][project] = configuration
        registrations[project] = {"agents": selected_agents, "root": configuration["root"]}
    if set(registrations) != set(registry["projects"]):
        raise InstallError("every registered domain needs an explicit installation record")
    for item in registry["projects"].values():
        item["queue"] = join(item["root"], "openspec/dependency-map.yaml")
    plan = build_plan(target, source, registry, registrations, old, initial_readset, old_harness=old_harness)
    if not dry_run:
        apply_plan(plan, source)
    return plan.summary(dry_run=dry_run)


def doctor(target: Path) -> dict:
    target = Path(target).expanduser().resolve()
    git_common_dir(target)
    harness = installation_layout(target)
    manifest = load_manifest(target, harness=harness)
    if manifest is None:
        raise InstallError("target has no workflow installation")
    verify_owned(target, manifest)
    registry = load_registry(target, harness=harness)
    validate_registry(target, registry)
    if digest(encoded(registry)) != manifest["registry_sha256"]:
        # Version-1 manifests hashed the inline document before filling optional
        # defaults. Accept that exact historical authority until migration; v2
        # must always bind expanded settings, including every companion file.
        recorded = read_yaml(target_path(target, f"{harness}/projects.yaml"))
        if recorded["schema_version"] != 1 or digest(encoded(recorded)) != manifest["registry_sha256"]:
            raise InstallError("local project configuration changed; run update to refresh installed routing")
    if set(registry["projects"]) != set(manifest["projects"]):
        raise InstallError("registered domains differ from installed integrations; run an explicit installation")
    if not installed_openspec(target, harness):
        raise InstallError("pinned OpenSpec toolchain is missing or has a different version; run update")
    for name, project in registry["projects"].items():
        project_config(target, project["root"], required=True)
        if not target_path(target, project["queue"]).is_file():
            raise InstallError(f"missing dependency queue for {name}")
        dependency_document(target_path(target, project["queue"]))
        alternate = join(project["root"], "openspec/queue.yaml" if project["queue"].endswith("dependency-map.yaml") else "openspec/dependency-map.yaml")
        if target_path(target, alternate).exists():
            raise InstallError(f"ambiguous dependency map: {alternate}")
        verify_project_root(target, project, harness)
    return {"status": "valid", "workflow_version": manifest["workflow_version"],
            "openspec_version": manifest["openspec_version"], "projects": sorted(registry["projects"]),
            "verified": ["managed files", "upstream files", "instruction blocks", "scope registration", "OpenSpec version"],
            "limitations": ["Does not establish application behavior, review quality, account model availability, or filesystem confinement."]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install", help="connect a local OpenSpec root and its code scope")
    install.add_argument("--target", type=Path, required=True)
    install.add_argument("--project", help="optional compatibility identifier; existing identities are preserved")
    install.add_argument("--spec-root", default=".", help="directory containing openspec/, relative to --target (default: .)")
    install.add_argument("--scope", action="append", dest="scopes", help="source path relative to --target; repeat for several paths")
    install.add_argument("--check", action="append", help="JSON argv command; required unless workflow.yaml already supplies checks")
    install.add_argument("--agent", action="append", choices=sorted(AGENTS), dest="agents")
    install.add_argument("--lockfile", action="append", dest="lockfiles")
    install.add_argument("--dry-run", action="store_true")
    update = commands.add_parser("update", help="apply this distribution version, preserving local configuration")
    update.add_argument("--target", type=Path, required=True)
    update.add_argument("--dry-run", action="store_true")
    check = commands.add_parser("doctor", help="check installed ownership and configuration without changing files")
    check.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor(args.target)
        elif args.command == "update":
            result = installation(args.target, update=True, dry_run=args.dry_run)
        else:
            checks = [_argv(json.loads(value)) for value in args.check] if args.check is not None else None
            result = installation(args.target, project=args.project, spec_root=args.spec_root, scopes=args.scopes,
                                  checks=checks, agents=args.agents, lockfiles=args.lockfiles, dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
        return 0
    except (InstallError, OSError, ValueError, yaml.YAMLError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
