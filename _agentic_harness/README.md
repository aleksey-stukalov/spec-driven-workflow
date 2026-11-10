# Installed development workflow

Start with the [policy map](policies/README.md). It identifies the required
instructions for the current phase. The [execution procedure](procedures/execute.md)
connects project selection, original evidence, isolated workspaces and durable
review accounting.

- [Development lifecycle](policies/development.md)
- [OpenSpec ownership and completion](policies/openspec.md)
- [Plan profiles](policies/plans.md) and [machine-readable catalog](plans.yaml)
- [Complete pipeline](procedures/pipeline.md)
- [Design hardening](procedures/harden-change.md)
- [Implementation review](procedures/review-impl.md)
- [Worker role contract](roles/runtime.md)

`projects.yaml` is local project configuration. It binds code roots, an OpenSpec
home, checks and environment locks. The installer records its version and managed
file hashes in `install.json`. Application specifications and those project
bindings are not replaced with the package author's project data.

Run the entrypoint from the consumer repository's Git worktree root:

```sh
uv run --locked --project _agentic_harness python \
  _agentic_harness/tools/harness.py project PROJECT
```

The OpenSpec CLI is installed locally with
`npm --prefix _agentic_harness ci --ignore-scripts`. Route it through
`harness.py openspec PROJECT -- COMMAND` so the selected project and tool version
remain explicit. OpenSpec owns its generated files; our skills use `sdw-*`.
