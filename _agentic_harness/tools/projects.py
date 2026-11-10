"""Directory-selected OpenSpec configuration and repository-relative boundaries."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key, value in node.value:
        name = loader.construct_object(key, deep=deep)
        if name in result:
            raise ValueError(f"duplicate configuration key: {name}")
        result[name] = loader.construct_object(value, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _read_yaml(path: Path):
    try:
        return yaml.load(path.read_text(), Loader=UniqueLoader)
    except (yaml.YAMLError, UnicodeError) as exc:
        raise ValueError(f"invalid YAML configuration: {path}") from exc


def relative_path(root: Path, value: str, *, exists=False) -> Path:
    """Resolve one canonical non-root path without following aliases."""
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise ValueError("expected a repository-relative path")
    rel = Path(value)
    if rel.is_absolute() or any(p in {"", ".", ".."} for p in value.split("/")):
        raise ValueError(f"unsafe path: {value}")
    path = root / rel
    parents = [root.joinpath(*rel.parts[:n]) for n in range(1, len(rel.parts) + 1)]
    if not path.resolve().is_relative_to(root.resolve()) or any(p.is_symlink() for p in parents):
        raise ValueError(f"aliased path: {value}")
    if exists and not path.exists():
        raise ValueError(f"missing registered path: {value}")
    return path


def relative_root(root: Path, value: str, *, exists=False) -> Path:
    """Resolve a configured root; only this API permits the repository itself."""
    if value == ".":
        if exists and not root.is_dir():
            raise ValueError("missing repository root")
        return root
    return relative_path(root, value, exists=exists)


def scope_contains(scope: str, path: str) -> bool:
    """Compare canonical repository paths, with explicit whole-repository scope."""
    for value in (scope, path):
        if (not isinstance(value, str) or not value or "\\" in value or "\0" in value
                or Path(value).is_absolute()
                or (value != "." and any(part in {"", ".", ".."} for part in value.split("/")))):
            raise ValueError("scope containment requires canonical repository-relative paths")
    return scope == "." or path == scope or path.startswith(scope + "/")


def editable_areas(project: dict) -> list[str]:
    """Domain source and its own OpenSpec metadata are distinct owned areas."""
    metadata = (Path(project["root"]) / "openspec").as_posix()
    return list(dict.fromkeys([*project["code_roots"], metadata]))


def config_path(root: Path, project: dict) -> Path:
    """Keep the user's supported filename; two competing configs are invalid."""
    home = relative_root(root, project["root"])
    candidates = [home / "openspec" / name for name in ("config.yaml", "config.yml")]
    present = [path for path in candidates if os.path.lexists(path)]
    if len(present) != 1 or not present[0].is_file():
        raise ValueError("conflicting/missing OpenSpec authority: require exactly one config.yaml or config.yml")
    relative_path(root, present[0].relative_to(root).as_posix(), exists=True)
    configuration = _read_yaml(present[0])
    if not isinstance(configuration, dict):
        raise ValueError("OpenSpec configuration must be a mapping")
    if configuration.get("store"):
        raise ValueError("external OpenSpec stores are unsupported; use a local OpenSpec home")
    return present[0]


def _argv_commands(value, label, *, empty=False):
    if (not isinstance(value, list) or (not value and not empty)
            or any(not isinstance(cmd, list) or not cmd
                   or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in cmd)
                   for cmd in value)):
        raise ValueError(f"{label} must be argv arrays")
    return value


def _paths(root, value, label, *, roots=False):
    if (not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"invalid {label}")
    for item in value:
        (relative_root if roots else relative_path)(root, item)
    return list(value)


def _index(root: Path) -> dict:
    path = relative_path(root, "_agentic_harness/projects.yaml", exists=True)
    data = _read_yaml(path)
    if (not isinstance(data, dict) or set(data) != {"schema_version", "projects"}
            or type(data["schema_version"]) is not int or data["schema_version"] not in (1, 2)):
        raise ValueError("projects.yaml: expected schema_version 1 or 2 and projects")
    if not isinstance(data["projects"], dict) or not data["projects"]:
        raise ValueError("projects.yaml: empty project registration")
    return data


def _workflow_path(project_root: str) -> str:
    return (Path(project_root) / "openspec/workflow.yaml").as_posix()


def _workflow(root: Path, project_root: str) -> dict:
    path = relative_path(root, _workflow_path(project_root), exists=True)
    data = _read_yaml(path)
    required = {"schema_version", "code_roots", "checks"}
    optional = {"environment", "evidence_exclude"}
    if (not isinstance(data, dict) or not required <= set(data)
            or set(data) - required - optional
            or type(data["schema_version"]) is not int or data["schema_version"] != 1):
        raise ValueError(f"invalid workflow configuration: {path.relative_to(root)}")
    return {key: value for key, value in data.items() if key != "schema_version"}


def _normalize_settings(root: Path, project: dict, name: str) -> dict:
    project = dict(project)
    if not project["code_roots"]:
        raise ValueError(f"invalid code roots: {name}")
    project["code_roots"] = _paths(root, project["code_roots"], "code roots", roots=True)
    _argv_commands(project["checks"], "checks")
    environment = project.get("environment", {})
    if not isinstance(environment, dict) or set(environment) - {"lockfiles", "prepare"}:
        raise ValueError(f"invalid environment: {name}")
    project["environment"] = {
        "lockfiles": _paths(root, environment.get("lockfiles", []), "environment lockfiles"),
        "prepare": _argv_commands(environment.get("prepare", []), "environment prepare", empty=True),
    }
    project["evidence_exclude"] = _paths(root, project.get("evidence_exclude", []), "evidence exclusions", roots=True)
    return project


def configuration_paths(root: Path, selected: dict) -> list[str]:
    """List the local files that declare scope, checks and environment policy."""
    data = _index(root)
    name = selected["id"]
    binding = data["projects"].get(name)
    if not isinstance(binding, dict) or binding.get("root") != selected["root"]:
        raise ValueError("selected project differs from current configuration")
    paths = ["_agentic_harness/projects.yaml"]
    if data["schema_version"] == 2:
        companion = _workflow_path(selected["root"])
        relative_path(root, companion, exists=True)
        paths.append(companion)
    return paths


def registry(root: Path = ROOT) -> dict:
    data = _index(root)
    projects = {}
    seen = set()
    for name, binding in data["projects"].items():
        required = {"root"} if data["schema_version"] == 2 else {"root", "queue", "code_roots", "checks"}
        optional = set() if data["schema_version"] == 2 else {"environment", "evidence_exclude"}
        if (not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", name)
                or not isinstance(binding, dict) or not required <= set(binding)
                or set(binding) - required - optional):
            raise ValueError(f"invalid project: {name}")
        relative_root(root, binding["root"], exists=True)
        if data["schema_version"] == 2:
            project = {"root": binding["root"],
                       "queue": (Path(binding["root"]) / "openspec/queue.yaml").as_posix(),
                       **_workflow(root, binding["root"])}
        else:
            project = dict(binding)
        project_root = relative_root(root, project["root"], exists=True)
        queue = relative_path(root, project["queue"], exists=True)
        if (not project_root.is_dir() or not queue.is_file() or project_root in seen
                or queue.parent != project_root / "openspec"):
            raise ValueError(f"conflicting/missing OpenSpec authority: {name}")
        seen.add(project_root)
        config_path(root, project)
        project = _normalize_settings(root, project, name)
        if data["schema_version"] == 1 and os.path.lexists(root / _workflow_path(project["root"])):
            companion = _normalize_settings(root, _workflow(root, project["root"]), name)
            settings = {key: value for key, value in project.items() if key not in {"root", "queue"}}
            if companion != settings:
                raise ValueError(f"conflicting legacy and local workflow configuration: {name}")
        projects[name] = project
    entries = list(projects.items())
    for index, (name, project) in enumerate(entries):
        for other_name, other in entries[index + 1:]:
            if (scope_contains(project["root"], other["root"])
                    or scope_contains(other["root"], project["root"])):
                raise ValueError(f"overlapping project roots: {name}, {other_name}")
            for left in editable_areas(project):
                for right in editable_areas(other):
                    if scope_contains(left, right) or scope_contains(right, left):
                        raise ValueError(f"overlapping project areas: {name} ({left}), {other_name} ({right})")
    return projects


def _nearest_home(root: Path, directory: Path) -> str | None:
    """Follow native local-root selection, bounded by this Git worktree."""
    while True:
        metadata = directory / "openspec"
        if metadata.is_symlink():
            raise ValueError(f"aliased OpenSpec authority: {metadata}")
        if metadata.is_dir() and (
                any((metadata / name).is_dir() for name in ("specs", "changes"))
                or any(os.path.lexists(metadata / name) for name in ("config.yaml", "config.yml"))):
            return directory.relative_to(root).as_posix()
        if directory == root:
            return None
        directory = directory.parent


def resolve(project: str | None = None, root: Path = ROOT, *, at: str | None = None,
            cwd: Path | None = None) -> dict:
    root = Path(root).resolve()
    projects = registry(root)
    if project is not None and at is not None:
        raise ValueError("select an OpenSpec directory with --at or a legacy project ID, not both")
    if project is None:
        if at is not None:
            directory = relative_root(root, at, exists=True)
            if not directory.is_dir():
                raise ValueError("--at requires an existing repository-relative directory")
        else:
            directory = Path.cwd() if cwd is None else Path(cwd).absolute()
            if directory.is_relative_to(root):
                directory = relative_root(root, directory.relative_to(root).as_posix(), exists=True)
                if not directory.is_dir():
                    raise ValueError("working directory is not a directory")
            else:
                directory = None
        home = _nearest_home(root, directory) if directory is not None else None
        if home is not None:
            matches = [name for name, value in projects.items() if value["root"] == home]
            if not matches:
                raise ValueError(f"nearest OpenSpec home is not adopted by this workflow: {home}; select an adopted home with --at")
            project = matches[0]
        elif at is not None:
            raise ValueError(f"no OpenSpec home found at or above --at {at} within this repository")
    if project is None:
        if len(projects) != 1:
            raise ValueError("multiple registered projects; select an OpenSpec directory with --at")
        project = next(iter(projects))
    if project not in projects:
        raise ValueError(f"unknown OpenSpec project: {project}")
    return {"id": project, **projects[project]}


def openspec(project: str | None, arguments: list[str], root: Path = ROOT, *, at: str | None = None) -> int:
    if any(argument.split("=", 1)[0] in {"--store", "--store-path"} for argument in arguments):
        raise ValueError("external OpenSpec store selectors cannot override the selected local home")
    selected = resolve(project, root, at=at)
    binary = root / "_agentic_harness/node_modules/.bin/openspec"
    if not binary.is_file():
        raise ValueError("install the pinned toolchain: npm --prefix _agentic_harness ci --ignore-scripts")
    package = json.loads((root / "_agentic_harness/package.json").read_text())
    version = (package.get("dependencies", {}) | package.get("devDependencies", {}))["@fission-ai/openspec"]
    print(json.dumps({"project": selected["id"], "openspec_root": str((root / selected["root"]).resolve()), "toolchain": "@fission-ai/openspec@" + version}), file=__import__('sys').stderr)
    launcher = root / "_agentic_harness/tools/openspec.mjs"
    if not launcher.is_file():
        raise ValueError("pinned OpenSpec launcher is missing")
    return subprocess.run(["node", str(launcher), *arguments], cwd=root / selected["root"], env={**os.environ, "OPENSPEC_TELEMETRY": "0"}).returncode
