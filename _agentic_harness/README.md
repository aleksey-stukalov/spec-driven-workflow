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

Each adopted OpenSpec home keeps project settings beside its specifications:

- `openspec/config.yaml` (or an existing `config.yml`) selects the native schema
  and supplies project context, artifact rules and supported operation guidance.
- `openspec/workflow.yaml` supplies this workflow's source scopes, executable
  checks, environment preparation, lockfiles and evidence exclusions. Paths are
  relative to the Git worktree root; checks also run from that root.

`projects.yaml` is the internal index of stable project identifiers and OpenSpec
directories. Runs record those identifiers. The installer maintains the index;
choose a directory when starting work.
Legacy installations can still read their inline settings until a reviewed
update moves them beside OpenSpec. The installer records its version and managed
file hashes in `install.json`. Application settings and specifications stay
project-owned.

Run the entrypoint from the consumer repository's Git worktree root:

```sh
uv run --locked --project _agentic_harness python \
  _agentic_harness/tools/harness.py project
```

For a component, append `--at services/api`, replacing that path with the
directory containing its `openspec/`. Without `--at`, the command uses the
nearest adopted OpenSpec home from the current directory, or the sole configured
project if no local home is found. Ambiguity or a nearer unadopted home stops
selection. Keep the returned `id` in the run's machine requests and evidence.

The OpenSpec CLI is installed locally with
`npm --prefix _agentic_harness ci --ignore-scripts`. Route it through
`harness.py openspec --at services/api -- COMMAND`, or omit `--at` under the same
selection rules. OpenSpec owns its generated files; our skills use `sdw-*` and
retain the execution, independent review and acceptance gates.
