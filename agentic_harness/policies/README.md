# Workflow instruction map

Read this map after the target repository's applicable instructions and the
selected project registration. Links are references, not automatic imports.
Resolve Markdown links relative to their containing file and operational paths
from the assigned repository or worktree root. Report a missing required file
before starting work that depends on it.

## Read by task

| Task | Required reading |
| --- | --- |
| Any adopted workflow work | [Repository boundaries](repository.md) and [development lifecycle](development.md) |
| Specification or design work | [OpenSpec policy](openspec.md) and [design hardening](../procedures/harden-change.md) |
| Agent dispatch, review, recovery or evidence | [Execution policy](execution.md), [plan profiles](plans.md) and [execution procedure](../procedures/execute.md) |
| One complete implementation change | [Pipeline](../procedures/pipeline.md), plus its linked phase procedures |
| Independent implementation review | [Review procedure](../procedures/review-impl.md) |
| One worker assignment | [Runtime role contract](../roles/runtime.md), plus the assigned phase |

Read the selected project's existing `openspec/config.yaml` or
`openspec/config.yml`, applicable capability specifications, owning change and
declared project instructions. Exactly one config filename is supported; preserve
the existing choice. Product facts,
build commands and domain constraints belong to that project; this package does
not supply them.

## Entry points and authority

`sdw-run`, `sdw-harden` and `sdw-review` are package-owned entry points. They select
a registered project and require these shared policies. They do not replace
OpenSpec-generated skills or grant permission to implement, publish or merge.

Canonical skill bodies live under `agentic_harness/skills/`. Individual relative
directory links expose them in selected agent discovery locations. Read their
referenced policies explicitly; link discovery alone does not load the process.

Installation adds explicit routing to existing repository instructions. It must
preserve unrelated instructions and agent settings. Read the routed documents;
do not assume that discovering a skill has loaded every policy or selected the
correct OpenSpec root.

The installed version supplies common process rules. Project registration binds
scope, specification home, checks and environment preparation. User instructions
and applicable host or repository constraints still apply. Resolve a conflict
explicitly; never silently replace the target project's rules.
