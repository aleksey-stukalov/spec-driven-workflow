# Spec-driven workflow

A reusable development process built on OpenSpec. It connects a bounded task,
specification, independent review, implementation, verification and handoff.
Apply it to a whole Git repository or to selected parts of an existing one.

For an agent, start with [BOOTSTRAP.md](BOOTSTRAP.md). It explains how to inspect
a target repository, choose its scope and install this workflow without replacing
its existing development rules or settings.

## Install into a project

Use a reviewed release or commit of this repository. Run these commands from its
checkout. Python 3.12+, uv, Node 20.19+ and npm are required. The workflow's
dependencies stay separate from the target application's dependencies.

```sh
uv sync --locked
npm --prefix _agentic_harness ci --ignore-scripts

uv run --locked python tools/workflow.py install \
  --target /path/to/project \
  --project api \
  --spec-root services/api \
  --scope services/api \
  --scope tests/api \
  --check '["npm", "--prefix", "services/api", "test"]' \
  --agent codex --agent claude \
  --dry-run
```

Inspect the planned changes, then repeat without `--dry-run` to install. Replace
the example scope and check with the target project's actual paths and commands.
For a whole repository, use `--spec-root . --scope .`. Supply additional
`--check` arguments for other required checks. Declare application dependency
locks with `--lockfile`; projects without a lock file can omit it.

The OpenSpec root and source scope are separate. One project can cover several
source directories. Two independently developed components can have separate
registered projects with non-nested OpenSpec roots. Ambiguous overlapping scopes
are rejected. See
[scope and routing](docs/scope.md).

```sh
uv run --locked python tools/workflow.py doctor --target /path/to/project
uv run --locked python tools/workflow.py update --target /path/to/project --dry-run
```

An update uses the workflow checkout from which the command is run. Review its
version and changes first. Local edits to package-managed files are conflicts;
project configuration and product specifications remain locally owned.

## Use the installed workflow

The installer adds `sdw-run`, `sdw-harden` and `sdw-review` skills for selected
agents, role definitions under the `sdw-` namespace, a scoped instruction block,
and the `_agentic_harness/` runtime. It does not replace global model settings.

From the target repository's Git worktree root:

```sh
uv run --locked --project _agentic_harness python \
  _agentic_harness/tools/harness.py project api

uv run --locked --project _agentic_harness python \
  _agentic_harness/tools/harness.py openspec api -- list --json
```

The agent follows the [policy map](_agentic_harness/policies/README.md) and
[execution procedure](_agentic_harness/procedures/execute.md). The runtime is a
set of explicit phase tools, not an unattended task runner. The agent prepares
and verifies the requests, selected project, authorizations and original evidence.
Read-only discovery does not claim work or start the next task.

```mermaid
flowchart LR
  Task[Bounded task] --> Design[Specification and design]
  Design --> DR[Independent design review]
  DR --> Code[Implementation and tests]
  Code --> IR[Independent implementation review]
  IR --> Verify[Verify final files and evidence]
  Verify --> Archive[Sync and archive completed change]
  Archive --> Handoff[Authorized handoff]
```

`budget`, `balanced` and `smart` are explicit profiles in
[plans.yaml](_agentic_harness/plans.yaml). Their model choices and limits are
configuration, not measured claims of equivalent quality or savings. Verify
provider availability before launching a run. Native model calls and GitHub
publication require the applicable task authority.

## OpenSpec ownership

OpenSpec 1.14.3 generates its own `openspec-*` skills and any selected `opsx-*`
commands. This workflow does not modify or shadow those files. Its own policy,
roles and skills have separate ownership. Upstream updates must leave them intact.
Product specs, changes and project context belong to the target project.

The original GitBob importer skills already matched clean OpenSpec output. The
custom root wrappers are replaced by the `sdw-*` entrypoints in this extraction.
See the [extraction inventory](docs/extraction.md) and [provenance](NOTICE.md).

## Develop this package

```sh
uv sync --locked
npm --prefix _agentic_harness ci --ignore-scripts
uv run --locked pytest
```

The tests cover runtime accounting and recovery, project scope, retained source,
installer behavior and real pinned OpenSpec generation. Native-provider and
GitHub transport tests use substitutes; they do not prove live account capability,
model quality or billing. Coordination is local to one clone's shared Git
directory. A scoped instruction or assignment is not an operating-system sandbox.

The verified contracts live under [openspec/specs/](openspec/specs/). The
[archived extraction and verification](openspec/changes/archive/2026-11-10-26-11-10-001-extract-portable-workflow/verification.md)
record the delivered scope and checks. GitBob's migration is a separate follow-up;
this repository does not alter its checkout, active runs or existing evidence.
