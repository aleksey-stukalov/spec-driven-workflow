"""Generate only the workflow's namespaced agent integrations.

OpenSpec owns openspec-* and opsx-*; this module never renders those files or
host-wide settings. The installer owns merging the small entrypoint block.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

import tomlkit
import yaml

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "agentic_harness/tools"))
from projects import workflow_path
from skill_links import discovery_links
SKILLS = {
    "sdw-run": (
        "Run one authorized spec-driven development change in an adopted OpenSpec project, "
        "including specification, implementation, independent review and handoff.",
        "pipeline.md",
    ),
    "sdw-harden": (
        "Prepare or independently review the specification and design of a selected "
        "change using this workflow. Use for design hardening before implementation.",
        "harden-change.md",
    ),
    "sdw-review": (
        "Review an implementation against its selected specification, tests and runtime "
        "risks using this workflow's independent review procedure.",
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
    for project in sorted(projects.values(), key=lambda item: item["root"]):
        roots = ", ".join(f"`{p}`" for p in project["code_roots"])
        settings = workflow_path(project["root"])
        rows.append(
            f"- OpenSpec root `{project['root']}`: code scope {roots}; "
            f"settings [workflow.yaml]({quote(settings, safe='/')})."
        )
    return (
        "## Spec-driven workflow\n\n"
        "Apply this workflow to changes in the adopted scopes below. For work outside "
        "those scopes, keep the project's existing process. Adoption is not permission "
        "to modify every listed file. Read the applicable existing repository instructions.\n\n"
        + "\n".join(rows)
        + "\n\nBefore a scoped change, read "
        "[`agentic_harness/policies/README.md`](agentic_harness/policies/README.md) "
        "and select the intended OpenSpec directory. Read its native `config.yaml` "
        "(or existing `config.yml`) and workflow settings above. "
        "Resolve these links from the Git worktree root. These are required reads, "
        "not automatic imports. Use `sdw-run`, `sdw-harden`, or `sdw-review` for the "
        "applicable phase. Resolve cross-scope work explicitly before making changes.\n\n"
        "OpenSpec's generated skills remain unchanged. Route its commands through "
        "`uv run --locked --project agentic_harness python "
        "agentic_harness/tools/harness.py openspec --at SPEC_ROOT -- COMMAND` "
        "from the worktree root. `SPEC_ROOT` is the repository-relative directory "
        "containing the intended `openspec/`, such as `.` or `services/api`. "
        "The wrapper reports the selected root and pins the CLI. "
        "Use the `id` returned by `harness.py project --at SPEC_ROOT` in runtime "
        "requests and retain it throughout the run; no installation name needs to be invented.\n"
    )


def links(agents: list[str]) -> dict[str, str]:
    """Explicit discovery link plan, separate from regular role outputs."""
    return discovery_links(agents)


def outputs(registry: dict, agents: list[str]) -> dict[str, str]:
    """Return repo-relative owned files. No writes or shared-settings replacement."""
    _projects(registry)
    if not agents or set(agents) - {"codex", "claude"}:
        raise ValueError("supported agent integrations are codex and claude")
    result = {}
    # Validate in the source distribution's own import context. A caller may
    # already have another installed runtime in sys.modules or on sys.path.
    loader = (
        "import json,sys; from pathlib import Path; "
        "sys.path.insert(0,str(Path(sys.argv[1])/'agentic_harness/tools')); "
        "from plan_runtime import load_catalog; "
        "print(json.dumps(load_catalog(Path(sys.argv[1])/'agentic_harness/plans.yaml')))"
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
            "agentic_harness/policies/README.md, agentic_harness/policies/plans.md, "
            "agentic_harness/procedures/execute.md and agentic_harness/roles/runtime.md. "
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
