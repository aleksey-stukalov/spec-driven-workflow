# Installed development workflow

Open the generated [visual handbook](index.html) in a browser to read the process
diagram and current profile tables offline. Markdown and the catalog remain the
maintained sources. Rebuild the page from the Git worktree root with:

```sh
uv run --locked --project agentic_harness python agentic_harness/tools/build.py
uv run --locked --project agentic_harness python agentic_harness/tools/build.py --check
```

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

Each adopted OpenSpec home has native configuration and separate harness settings:

- `openspec/config.yaml` (or an existing `config.yml`) selects the native schema
  and supplies project context, artifact rules and supported operation guidance.
- `agentic_harness/config/workflow.yaml` supplies the root home's source scopes, executable
  checks, environment preparation, lockfiles and evidence exclusions. Paths are
  relative to the Git worktree root; checks also run from that root. For a home
  at `services/api`, use `agentic_harness/config/services/api/workflow.yaml`.
- `openspec/dependency-map.yaml` stays beside the changes and preserves the
  ordered `queue` list and its prerequisite rules.

`projects.yaml` is the internal index of stable project identifiers and OpenSpec
directories. Runs record those identifiers. The installer maintains the index;
choose a directory when starting work.
Legacy inline settings and OpenSpec-local settings remain readable under their
original index schemas until a reviewed update migrates them. The installer
records its version, managed file hashes and exact discovery link targets in
`install.json`. Application settings and specifications stay project-owned.

The maintained `sdw-*` skills are under `skills/`. Selected agent discovery
directories contain relative links to those directories. Each skill's Markdown
references work from both its canonical and discovery locations. OpenSpec owns
its own generated skills; they remain ordinary upstream-managed files.

Run the entrypoint from the consumer repository's Git worktree root:

```sh
uv run --locked --project agentic_harness python \
  agentic_harness/tools/harness.py project
```

For a component, append `--at services/api`, replacing that path with the
directory containing its `openspec/`. Without `--at`, the command uses the
nearest adopted OpenSpec home from the current directory, or the sole configured
project if no local home is found. Ambiguity or a nearer unadopted home stops
selection. Keep the returned `id` in the run's machine requests and evidence.

The OpenSpec CLI is installed locally with
`npm --prefix agentic_harness ci --ignore-scripts`. Route it through
`harness.py openspec --at services/api -- COMMAND`, or omit `--at` under the same
selection rules. OpenSpec owns its generated files; our skills use `sdw-*` and
retain the execution, independent review and acceptance gates.
