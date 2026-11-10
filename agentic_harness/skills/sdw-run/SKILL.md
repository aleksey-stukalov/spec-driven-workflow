---
name: sdw-run
description: "Run one authorized spec-driven development change in an adopted OpenSpec project, including specification, implementation, independent review and handoff."
---

Resolve the Git worktree root and read applicable repository instructions. Read the [policy map](../../../agentic_harness/policies/README.md), [execution procedure](../../../agentic_harness/procedures/execute.md) and [phase procedure](../../../agentic_harness/procedures/pipeline.md). Read the links explicitly.

Select the OpenSpec directory that owns the requested change and file scope. Run from the worktree root:

```sh
uv run --locked --project agentic_harness python agentic_harness/tools/harness.py project --at SPEC_ROOT
```

Replace SPEC_ROOT with the repository-relative directory containing the intended `openspec/`; use `.` for the repository root. Read its native `config.yaml` (or existing `config.yml`) and the harness settings path returned by this command. The harness settings document holds source scope, checks and environment settings; all its paths are relative to the Git worktree root. Source and test folders can be elsewhere. Use the returned `id` in machine requests and keep that binding for the run.

Without `--at`, the command selects the nearest adopted OpenSpec root from the current directory, or the sole configured project when no local home is found. A nearer unadopted home or ambiguous selection stops the command. Resolve the requested scope before choosing another directory.

Use the pinned CLI in that selected project through:

```sh
uv run --locked --project agentic_harness python agentic_harness/tools/harness.py openspec --at SPEC_ROOT -- list --json
```

Read OpenSpec's returned context and instructions. When following an unchanged upstream skill, route each `openspec` command through this wrapper and preserve its arguments. Do not edit or shadow the generated `openspec-*` skills. Native OpenSpec commands alone do not run this workflow's acceptance gates. A nested OpenSpec root and these instructions do not create a filesystem sandbox.

Use the selected plan's durable ledger and dispatcher for counted assignments. Verify required native capabilities before launch; retain unavailable metadata as unknown and honor existing model preferences and authorized resource limits. Keep task authority, exact owned paths, independent reviews and original results bound to the selected change. Do not start another queued change automatically.
