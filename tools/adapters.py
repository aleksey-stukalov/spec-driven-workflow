"""Generate only the workflow's namespaced agent integrations.

OpenSpec owns openspec-* and opsx-*; this module never renders those files or
host-wide settings. The installer owns merging the small entrypoint block.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import tomlkit
import yaml

SOURCE = Path(__file__).resolve().parents[1]
SKILLS = {
    "sdw-run": (
        "Run one authorized spec-driven development change in a registered project, "
        "including specification, implementation, independent review and handoff.",
        "pipeline.md",
    ),
    "sdw-harden": (
        "Prepare or independently review the specification and design of a selected "
        "change using the registered workflow. Use for design hardening before implementation.",
        "harden-change.md",
    ),
    "sdw-review": (
        "Review an implementation against its selected specification, tests and runtime "
        "risks using the registered workflow's independent review procedure.",
        "review-impl.md",
    ),
}


def _projects(registry: dict) -> dict:
    projects = registry.get("projects", {})
    if not isinstance(projects, dict) or not projects:
        raise ValueError("agent adapters require registered projects")
    for name in projects:
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name):
            raise ValueError("unsafe project identifier")
    return projects


def entrypoint(registry: dict) -> str:
    """The installer places this body in its marked, narrowly owned block."""
    projects = _projects(registry)
    rows = []
    for name, project in sorted(projects.items()):
        roots = ", ".join(f"`{p}`" for p in project["code_roots"])
        rows.append(f"- `{name}`: code scope {roots}; OpenSpec project root `{project['root']}`.")
    return (
        "## Spec-driven workflow\n\n"
        "Apply this workflow to changes in the registered scopes below. For work outside "
        "those scopes, keep the project's existing process. Registration is not permission "
        "to modify every listed file. Read the applicable existing repository instructions.\n\n"
        + "\n".join(rows)
        + "\n\nBefore a scoped change, read "
        "[`_agentic_harness/policies/README.md`](_agentic_harness/policies/README.md) "
        "and select the project from "
        "[`_agentic_harness/projects.yaml`](_agentic_harness/projects.yaml). "
        "Resolve these links from the Git worktree root. These are required reads, "
        "not automatic imports. Use `sdw-run`, `sdw-harden`, or `sdw-review` for the "
        "applicable phase. Resolve cross-scope work explicitly before making changes.\n\n"
        "OpenSpec's generated skills remain unchanged. Route its commands through "
        "`uv run --locked --project _agentic_harness python "
        "_agentic_harness/tools/harness.py openspec PROJECT -- COMMAND`; "
        "the wrapper selects the registered project and pinned CLI. "
        "Do not infer the specification root from the shell's working directory.\n"
    )


def _link(path: str, target: str) -> str:
    return os.path.relpath(target, Path(path).parent).replace(os.sep, "/")


def _skill(path: str, name: str, description: str, procedure: str) -> str:
    reading = _link(path, "_agentic_harness/policies/README.md")
    execution = _link(path, "_agentic_harness/procedures/execute.md")
    phase = _link(path, "_agentic_harness/procedures/" + procedure)
    return (
        f"---\nname: {name}\ndescription: {json.dumps(description)}\n---\n\n"
        "Resolve the Git worktree root and read applicable repository instructions. "
        f"Read the [policy map]({reading}), [execution procedure]({execution}) "
        f"and [phase procedure]({phase}). Read the links explicitly.\n\n"
        "Select the registered project using the requested change and file scope. "
        "Run from the worktree root:\n\n"
        "```sh\nuv run --locked --project _agentic_harness python "
        "_agentic_harness/tools/harness.py project PROJECT\n```\n\n"
        "The sole registered project can be selected by omitting PROJECT. "
        "When several projects could apply, resolve the scope before proceeding. "
        "The registry's project root is the OpenSpec authority; code roots can be elsewhere.\n\n"
        "Use the pinned CLI in that selected project through:\n\n"
        "```sh\nuv run --locked --project _agentic_harness python "
        "_agentic_harness/tools/harness.py openspec PROJECT -- list --json\n```\n\n"
        "Read OpenSpec's returned context and instructions. When following an unchanged "
        "upstream skill, route each `openspec` command through this wrapper and preserve "
        "its arguments. Do not edit or shadow the generated `openspec-*` skills. "
        "A nested OpenSpec root and these instructions do not create a filesystem sandbox.\n\n"
        "Use the selected plan's durable ledger and dispatcher for counted assignments. "
        "Verify required native capabilities before launch; retain unavailable metadata "
        "as unknown and honor existing model preferences and authorized resource limits. "
        "Keep task authority, exact owned paths, independent reviews and original results "
        "bound to the selected change. Do not start another queued change automatically.\n"
    )


def outputs(registry: dict, agents: list[str]) -> dict[str, str]:
    """Return repo-relative owned files. No writes or shared-settings replacement."""
    _projects(registry)
    if not agents or set(agents) - {"codex", "claude"}:
        raise ValueError("supported agent integrations are codex and claude")
    result = {}
    for agent in sorted(set(agents)):
        base = ".agents" if agent == "codex" else ".claude"
        for name, (description, procedure) in SKILLS.items():
            path = f"{base}/skills/{name}/SKILL.md"
            result[path] = _skill(path, name, description, procedure)

    # Validate in the source distribution's own import context. A caller may
    # already have another installed runtime in sys.modules or on sys.path.
    loader = (
        "import json,sys; from pathlib import Path; "
        "sys.path.insert(0,str(Path(sys.argv[1])/'_agentic_harness/tools')); "
        "from plan_runtime import load_catalog; "
        "print(json.dumps(load_catalog(Path(sys.argv[1])/'_agentic_harness/plans.yaml')))"
    )
    checked = subprocess.run([sys.executable, "-c", loader, str(SOURCE)],
                             capture_output=True, text=True)
    if checked.returncode:
        raise ValueError("invalid workflow plan catalog: " + checked.stderr.strip())
    catalog = json.loads(checked.stdout)
    default = catalog["plans"][catalog["default"]]["steps"]
    for step in catalog["steps"]:
        if step["id"] == "human":
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]*", step["id"]):
            raise ValueError("unsafe role identifier")
        name = "sdw-" + step["id"].replace("_", "-")
        instructions = (
            "Read applicable AGENTS.md from the assigned Git worktree. Read "
            "_agentic_harness/policies/README.md, _agentic_harness/policies/plans.md, "
            "_agentic_harness/procedures/execute.md and _agentic_harness/roles/runtime.md. "
            "Resolve these paths from the worktree root.\n"
            f"Role: {step['label']}. Boundary: {step['boundary']}\n"
            "Use the registered project, explicit task authority and exact owned paths. "
            "Use the run ledger's selected route; these discovery defaults describe the "
            "catalog default only. Never change a live session's model, reset counters, "
            "delegate again or review your own work."
        )
        route = default[step["id"]]["routes"]
        if "codex" in agents:
            result[f".codex/agents/{name}.toml"] = tomlkit.dumps({
                "name": name,
                "description": step["label"],
                "model": route["codex"]["model"],
                "model_reasoning_effort": route["codex"]["effort"],
                "developer_instructions": instructions,
            })
        if "claude" in agents:
            header = {
                "name": name,
                "description": step["label"],
                "model": route["claude"]["model"],
                "effort": route["claude"]["effort"],
            }
            if step["permitted_writes"] == "read_only":
                header["tools"] = "Read, Glob, Grep"
            result[f".claude/agents/{name}.md"] = (
                "---\n" + yaml.safe_dump(header, sort_keys=False) + "---\n\n" + instructions + "\n"
            )
    return result
