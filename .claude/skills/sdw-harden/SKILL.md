---
name: sdw-harden
description: "Prepare or independently review the specification and design of a selected change using the registered workflow. Use for design hardening before implementation."
---

Resolve the Git worktree root and read applicable repository instructions. Read the [policy map](../../../_agentic_harness/policies/README.md), [execution procedure](../../../_agentic_harness/procedures/execute.md) and [phase procedure](../../../_agentic_harness/procedures/harden-change.md). Read the links explicitly.

Select the registered project using the requested change and file scope. Run from the worktree root:

```sh
uv run --locked --project _agentic_harness python _agentic_harness/tools/harness.py project PROJECT
```

The sole registered project can be selected by omitting PROJECT. When several projects could apply, resolve the scope before proceeding. The registry's project root is the OpenSpec authority; code roots can be elsewhere.

Use the pinned CLI in that selected project through:

```sh
uv run --locked --project _agentic_harness python _agentic_harness/tools/harness.py openspec PROJECT -- list --json
```

Read OpenSpec's returned context and instructions. When following an unchanged upstream skill, route each `openspec` command through this wrapper and preserve its arguments. Do not edit or shadow the generated `openspec-*` skills. A nested OpenSpec root and these instructions do not create a filesystem sandbox.

Use the selected plan's durable ledger and dispatcher for counted assignments. Verify required native capabilities before launch; retain unavailable metadata as unknown and honor existing model preferences and authorized resource limits. Keep task authority, exact owned paths, independent reviews and original results bound to the selected change. Do not start another queued change automatically.
