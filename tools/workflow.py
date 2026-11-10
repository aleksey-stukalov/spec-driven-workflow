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
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

import yaml

SOURCE = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"
OPENSPEC_VERSION = "1.14.3"
HARNESS = "_agentic_harness"
MANIFEST = f"{HARNESS}/install.json"
REGISTRY = f"{HARNESS}/projects.yaml"
START = "<!-- spec-driven-workflow:start -->"
END = "<!-- spec-driven-workflow:end -->"
PAYLOAD_DIRECTORIES = ("tools", "policies", "procedures", "roles", "templates")
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


def read_yaml(path: Path):
    try:
        return yaml.load(path.read_text(), Loader=UniqueLoader)
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


def load_manifest(target: Path) -> dict | None:
    path = target_path(target, MANIFEST)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError) as exc:
        raise InstallError("invalid workflow installation manifest") from exc
    required = {"schema_version", "workflow_version", "openspec_version", "payload_sha256", "registry_sha256", "managed", "upstream", "blocks", "projects"}
    if not isinstance(value, dict) or not required <= set(value) or value["schema_version"] != 1:
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
            if group == "managed" and not managed_path(name):
                raise InstallError(f"manifest claims a non-package file: {name}")
            if group == "upstream" and not upstream_path(name, value["projects"]):
                raise InstallError(f"manifest claims a non-OpenSpec file: {name}")
            if group == "blocks" and name not in {"AGENTS.md", "CLAUDE.md"}:
                raise InstallError(f"manifest claims an unsupported instruction file: {name}")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise InstallError("invalid installed file digest")
    if not isinstance(value["registry_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["registry_sha256"]):
        raise InstallError("invalid installed registry binding")
    return value


def managed_path(name: str) -> bool:
    if name in {f"{HARNESS}/{part}" for part in PAYLOAD_FILES}:
        return True
    if any(name.startswith(f"{HARNESS}/{directory}/") for directory in PAYLOAD_DIRECTORIES):
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
    for name, expected in manifest["blocks"].items():
        path = target_path(target, name)
        current = block(path.read_text()) if path.is_file() else None
        if current is None or digest(current.encode()) != expected:
            raise InstallError(f"locally changed or missing workflow block: {name}")


def workflow_name(root: str) -> str:
    return join(relative(root, root=True), "openspec/workflow.yaml")


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


def read_workflow(target: Path, root: str, *, readset=None, required=False) -> dict | None:
    name = workflow_name(root)
    if readset is not None and name not in readset:
        readset[name] = observe(target, name)
    path = target_path(target, name)
    if not path.exists():
        if required:
            raise InstallError(f"missing workflow configuration: {name}")
        return None
    if not path.is_file():
        raise InstallError(f"workflow configuration is not a regular file: {name}")
    value = read_yaml(path)
    required_fields = {"schema_version", "code_roots", "checks"}
    if (not isinstance(value, dict) or not required_fields <= set(value)
            or set(value) - required_fields - {"environment", "evidence_exclude"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1):
        raise InstallError(f"unsupported workflow configuration: {name}")
    return workflow_settings(value)


def load_registry(target: Path, *, readset=None) -> dict:
    """Expand either index version into the runtime's stable project structure."""
    if readset is not None and REGISTRY not in readset:
        readset[REGISTRY] = observe(target, REGISTRY)
    path = target_path(target, REGISTRY)
    if not path.exists():
        return {"schema_version": 1, "projects": {}}
    value = read_yaml(path)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "projects"}
            or type(value["schema_version"]) is not int or value["schema_version"] not in {1, 2}
            or not isinstance(value["projects"], dict)):
        raise InstallError("unsupported projects.yaml; existing configuration was preserved")
    projects = {}
    for name, project in value["projects"].items():
        if not isinstance(project, dict) or "root" not in project:
            raise InstallError(f"incomplete project registration: {name}")
        root = relative(project["root"], root=True)
        local = read_workflow(target, root, readset=readset, required=value["schema_version"] == 2)
        if value["schema_version"] == 2:
            if set(project) != {"root"}:
                raise InstallError("version 2 projects.yaml contains only OpenSpec roots; edit openspec/workflow.yaml")
            projects[name] = {"root": root, "queue": join(root, "openspec/queue.yaml"), **local}
        else:
            required_fields = {"root", "queue", "code_roots", "checks"}
            if not required_fields <= set(project) or set(project) - required_fields - {"environment", "evidence_exclude"}:
                raise InstallError(f"invalid legacy project configuration: {name}")
            settings = workflow_settings(project)
            if local is not None and local != settings:
                raise InstallError(f"workflow configuration conflicts with legacy projects.yaml: {workflow_name(root)}")
            projects[name] = {"root": root, "queue": project["queue"], **settings}
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
        if project["queue"] != join(root, "openspec/queue.yaml"):
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
        for area in dict.fromkeys([*areas, metadata]):
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


def installed_openspec(target: Path) -> bool:
    package = target_path(target, f"{HARNESS}/node_modules/@fission-ai/openspec/package.json")
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


def verify_project_root(target: Path, project: dict) -> None:
    """Ask the pinned CLI to resolve the authority, without relying on cwd guesses."""
    root = target_path(target, project["root"], root=True)
    with tempfile.TemporaryDirectory(prefix="sdw-doctor-") as temporary:
        environment = isolated_environment(Path(temporary) / "user")
        output = run(["node", str(target / HARNESS / "tools/openspec.mjs"), "list", "--json"], cwd=root, env=environment)
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

    def summary(self, *, dry_run=False) -> dict:
        summary = {"status": "planned" if dry_run else "installed", "workflow_version": VERSION,
                "openspec_version": OPENSPEC_VERSION, "changed": sorted(self.writes),
                "removed": sorted(self.removals), "create_directories": self.directories,
                "install_toolchain": self.dependencies, "projects": sorted(self.manifest["projects"]),
                "payload_sha256": self.manifest["payload_sha256"]}
        if dry_run:
            summary["diffs"] = {
                name: "".join(difflib.unified_diff((self.before.get(name) or b"").decode().splitlines(keepends=True),
                                                self.writes.get(name, b"").decode().splitlines(keepends=True),
                                                fromfile="a/" + name, tofile="b/" + name))
                for name in sorted(set(self.writes) | set(self.removals))
            }
            summary["file_hashes"] = {name: digest(value) for name, value in sorted(self.writes.items())}
        return summary


def observe(target: Path, name: str):
    """Fingerprint files and directory entries used to prepare an installation."""
    path = target / name
    if name == "CLAUDE.md" and path.is_symlink() and path.resolve() == (target / "AGENTS.md").resolve():
        return {"symlink": os.readlink(path)}
    path = target_path(target, name, root=name == ".")
    if path.is_file():
        return {"file": digest(path.read_bytes())}
    if path.is_dir():
        return {"directory": sorted(p.name for p in path.iterdir())}
    if path.exists():
        raise InstallError(f"unsupported target file type: {name}")
    return None


def check_readset(target: Path, readset: dict) -> None:
    for name, expected in readset.items():
        if observe(target, name) != expected:
            raise InstallError(f"target changed while preparing installation: {name}")


def build_plan(target: Path, source: Path, registry: dict, registrations: dict, old: dict | None, readset=None) -> Plan:
    readset = dict(readset or {})
    validate_registry(target, registry)
    watched = {MANIFEST, REGISTRY, "AGENTS.md", "CLAUDE.md", f"{HARNESS}/node_modules/@fission-ai/openspec/package.json"}
    if old:
        watched.update(old["managed"])
        watched.update(old["upstream"])
    for project in registry["projects"].values():
        watched.add(project["root"])
        watched.update(project["code_roots"])
        watched.update(project.get("environment", {}).get("lockfiles", []))
        watched.update(join(project["root"], "openspec/" + name) for name in ("config.yaml", "config.yml", "workflow.yaml", "queue.yaml", "changes", "schemas"))
        schemas = target_path(target, join(project["root"], "openspec/schemas"))
        if schemas.exists():
            watched.update(path.relative_to(target).as_posix() for path in schemas.rglob("*"))
    for name in watched:
        if name not in readset:
            readset[name] = observe(target, name)
    # Capture before verifying ownership or invoking generators. A concurrent
    # edit must not become a newly trusted baseline after ownership was checked.
    verify_owned(target, old)
    check_readset(target, readset)
    payload = package_payload(source)
    modules = adapter_module(source)
    selected_agents = sorted({agent for item in registrations.values() for agent in item["agents"]})
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
            readset[name] = observe(target, name)
    for name, contents in {**managed, **upstream}.items():
        path = target_path(target, name)
        owned = old is not None and (name in old["managed"] or name in old["upstream"])
        if path.exists() and not path.is_file():
            raise InstallError(f"installation would replace a non-file: {name}")
        if path.is_file() and not owned and path.read_bytes() != contents:
            raise InstallError(f"existing file conflicts with installation: {name}; preserve its customizations outside managed files first")
    current_registry = target_path(target, REGISTRY)
    index = {"schema_version": 2, "projects": {name: {"root": project["root"]}
             for name, project in registry["projects"].items()}}
    if not current_registry.exists() or read_yaml(current_registry) != index:
        intended[REGISTRY] = yaml.safe_dump(index, sort_keys=False).encode()
    for project in registry["projects"].values():
        local = read_workflow(target, project["root"], readset=readset)
        settings = workflow_settings(project)
        if local is None:
            intended[workflow_name(project["root"])] = yaml.safe_dump(
                {"schema_version": 1, **settings}, sort_keys=False).encode()
        elif local != settings:
            raise InstallError(f"existing workflow configuration differs: {workflow_name(project['root'])}; edit it explicitly and use update")
        queue = target_path(target, project["queue"])
        if not queue.exists():
            changes = target_path(target, join(project["root"], "openspec/changes"))
            if changes.exists() and any(p.is_dir() and p.name != "archive" for p in changes.iterdir()):
                raise InstallError(f"existing changes require an explicit dependency queue: {project['queue']}")
            intended[project["queue"]] = b"queue: []\n"
    bodies = {}
    for name in ("AGENTS.md", "CLAUDE.md"):
        if name == "CLAUDE.md" and "claude" not in selected_agents:
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
        "schema_version": 1, "workflow_version": VERSION, "openspec_version": OPENSPEC_VERSION,
        "payload_sha256": payload_hash,
        "registry_sha256": digest(encoded(registry)),
        "managed": {name: digest(value) for name, value in sorted(managed.items())},
        "upstream": {name: digest(value) for name, value in sorted(upstream.items())},
        "blocks": bodies, "projects": registrations,
    }
    intended[MANIFEST] = encoded(manifest)
    removals = sorted((set(old["managed"]) | set(old["upstream"])) - set(managed) - set(upstream)) if old else []
    for name in removals:
        target_path(target, name)
    directories = sorted({join(p["root"], "openspec/" + leaf) for p in registry["projects"].values() for leaf in ("specs", "changes") if not target_path(target, join(p["root"], "openspec/" + leaf)).exists()})
    before, writes = {}, {}
    for name, value in intended.items():
        path = target_path(target, name)
        prior = path.read_bytes() if path.is_file() else None
        if name not in readset:
            readset[name] = observe(target, name)
        if prior != value:
            writes[name] = value
            before[name] = prior
    for name in removals:
        before[name] = target_path(target, name).read_bytes()
    dependency_change = not installed_openspec(target) or any(name in writes for name in (f"{HARNESS}/package.json", f"{HARNESS}/package-lock.json"))
    check_readset(target, readset)
    toolchain = {name: payload[f"{HARNESS}/{name}"] for name in ("package.json", "package-lock.json")}
    return Plan(target, writes, removals, directories, dependency_change, manifest, before, readset, toolchain)


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


def atomic_write(path: Path, content: bytes) -> None:
    """A failed write never truncates the previous destination."""
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    descriptor, temporary = tempfile.mkstemp(prefix=".sdw-write-", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_plan(plan: Plan, source: Path) -> None:
    """Prepare network-dependent work first, then apply with rollback on error."""
    with tempfile.TemporaryDirectory(prefix="sdw-install-") as temporary:
        temporary = Path(temporary)
        pinned_source = temporary / "distribution"
        (pinned_source / HARNESS).mkdir(parents=True)
        for name, content in plan.toolchain.items():
            (pinned_source / HARNESS / name).write_bytes(content)
        dependencies = prepare_dependencies(pinned_source, temporary) if plan.dependencies else None
        guard_active_worktree(plan.target)
        check_readset(plan.target, plan.readset)
        # Recheck the read set after external commands; another writer may have edited it.
        for name, expected in plan.before.items():
            path = target_path(plan.target, name)
            current = path.read_bytes() if path.is_file() else None
            if current != expected:
                raise InstallError(f"target changed while preparing installation: {name}")
        old_dependencies = None
        new_dependencies = None
        changed = []
        created_directories = []
        try:
            for name in plan.directories:
                path = target_path(plan.target, name)
                path.mkdir(parents=True, exist_ok=True)
                created_directories.append(path)
            for name in sorted(set(plan.writes) - {MANIFEST}):
                path = target_path(plan.target, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(path, plan.writes[name])
                changed.append(name)
            for name in plan.removals:
                target_path(plan.target, name).unlink()
                changed.append(name)
            if dependencies is not None:
                destination = target_path(plan.target, f"{HARNESS}/node_modules")
                destination.parent.mkdir(parents=True, exist_ok=True)
                new_dependencies = Path(tempfile.mkdtemp(prefix=".sdw-deps-", dir=destination.parent))
                new_dependencies.rmdir()
                shutil.copytree(dependencies, new_dependencies, symlinks=True)
                if destination.exists():
                    old_dependencies = Path(tempfile.mkdtemp(prefix=".sdw-old-deps-", dir=destination.parent))
                    old_dependencies.rmdir()
                    destination.rename(old_dependencies)
                new_dependencies.rename(destination)
                new_dependencies = destination
            if MANIFEST in plan.writes:
                path = target_path(plan.target, MANIFEST)
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(path, plan.writes[MANIFEST])
                changed.append(MANIFEST)
        except BaseException:
            for name in reversed(changed):
                path = target_path(plan.target, name)
                prior = plan.before[name]
                if prior is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, prior)
            if new_dependencies is not None and new_dependencies.exists():
                shutil.rmtree(new_dependencies)
            if old_dependencies is not None:
                old_dependencies.rename(plan.target / HARNESS / "node_modules")
            for path in reversed(created_directories):
                if path.exists() and not any(path.iterdir()):
                    path.rmdir()
            raise
        else:
            if old_dependencies is not None:
                shutil.rmtree(old_dependencies)


def installation(target: Path, *, project: str | None = None, spec_root=".", scopes=None, checks=None, agents=None, lockfiles=None, dry_run=False, source=SOURCE, update=False) -> dict:
    target, source = Path(target).expanduser().resolve(), Path(source).resolve()
    if not target.is_dir():
        raise InstallError("target must be an existing repository directory")
    if target == source:
        raise InstallError("install into a consumer repository, not the source distribution")
    guard_active_worktree(target)
    initial_readset = {name: observe(target, name) for name in (MANIFEST, REGISTRY)}
    old = load_manifest(target)
    if update and old is None:
        raise InstallError("target has no workflow installation to update")
    registry = load_registry(target, readset=initial_readset)
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
        if existing is None:
            local = read_workflow(target, spec_root, readset=initial_readset)
            if local is not None:
                existing = {"root": spec_root, "queue": join(spec_root, "openspec/queue.yaml"), **local}
        default = {"root": spec_root, "queue": join(spec_root, "openspec/queue.yaml"),
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
            raise InstallError("provide --check commands or checks in openspec/workflow.yaml")
        if existing is not None and existing != configuration:
            raise InstallError("project already has different local configuration; edit openspec/workflow.yaml explicitly and use update")
        prior_agents = registrations.get(project, {}).get("agents", ["codex", "claude"])
        selected_agents = sorted(set(prior_agents if agents is None else agents))
        if not selected_agents or not set(selected_agents) <= AGENTS:
            raise InstallError("supported agent integrations are codex and claude")
        registry["projects"][project] = configuration
        registrations[project] = {"agents": selected_agents, "root": configuration["root"]}
    if set(registrations) != set(registry["projects"]):
        raise InstallError("every registered domain needs an explicit installation record")
    plan = build_plan(target, source, registry, registrations, old, initial_readset)
    if not dry_run:
        apply_plan(plan, source)
    return plan.summary(dry_run=dry_run)


def doctor(target: Path) -> dict:
    target = Path(target).expanduser().resolve()
    git_common_dir(target)
    manifest = load_manifest(target)
    if manifest is None:
        raise InstallError("target has no workflow installation")
    verify_owned(target, manifest)
    registry = load_registry(target)
    validate_registry(target, registry)
    if digest(encoded(registry)) != manifest["registry_sha256"]:
        # Version-1 manifests hashed the inline document before filling optional
        # defaults. Accept that exact historical authority until migration; v2
        # must always bind expanded settings, including every companion file.
        recorded = read_yaml(target_path(target, REGISTRY))
        if recorded["schema_version"] != 1 or digest(encoded(recorded)) != manifest["registry_sha256"]:
            raise InstallError("local project configuration changed; run update to refresh installed routing")
    if set(registry["projects"]) != set(manifest["projects"]):
        raise InstallError("registered domains differ from installed integrations; run an explicit installation")
    if not installed_openspec(target):
        raise InstallError("pinned OpenSpec toolchain is missing or has a different version; run update")
    for name, project in registry["projects"].items():
        project_config(target, project["root"], required=True)
        if not target_path(target, project["queue"]).is_file():
            raise InstallError(f"missing dependency queue for {name}")
        verify_project_root(target, project)
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
