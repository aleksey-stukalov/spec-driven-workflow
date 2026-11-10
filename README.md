# Spec-driven workflow

A reusable development process built on OpenSpec. It connects a bounded task,
specification, independent review, implementation, verification and handoff.
Apply it to a whole Git repository or to selected parts of an existing one.

For a visual guide, open the generated [HTML handbook](agentic_harness/index.html)
in a browser. It includes the development flow and current role/profile tables.
The page works offline and is built from the maintained package sources.

For an agent, start with [BOOTSTRAP.md](BOOTSTRAP.md). It explains how to inspect
a target repository, choose its scope and install this workflow without replacing
its existing development rules or settings.

## Install into a project

Run the installer from a checkout of **this workflow repository**. The `--target`
option points to **your existing Git repository**, which will receive the workflow.
Use a reviewed release or commit. Python 3.12+, uv, Node 20.19+ and npm are required.

First, install the workflow's own dependencies in its checkout:

```sh
uv sync --locked
npm --prefix agentic_harness ci --ignore-scripts
```

Choose one of the following installation options.

### Apply to the whole repository

Replace `/path/to/your-repository` with the path to your Git repository. This
example assumes that its tests run with `npm test`; replace `--check` with your
project's actual validation command, as explained below.

```sh
uv run --locked python tools/workflow.py install \
  --target /path/to/your-repository \
  --check '["npm", "test"]' \
  --agent codex --agent claude \
  --dry-run
```

Inspect the planned changes, then repeat without `--dry-run` to install.
The installer creates or reuses `openspec/` at the repository root and applies
the process to the whole repository. No configuration name is required.
The directory containing `openspec/` is called its OpenSpec home.

| Option | Meaning |
| --- | --- |
| `--target /path/to/your-repository` | The Git repository receiving the workflow. |
| `--spec-root backend` | Put or reuse `openspec/` inside `backend/`. Omit this option to use the repository root. |
| `--scope backend` | Apply the process to this path. Repeat the option for related source and test paths. For a new installation, the default is the directory selected by `--spec-root`. |
| `--check '["npm", "test"]'` | Save a required validation command to run from the target repository's root during development. |
| `--agent codex --agent claude` | Install integrations for these agents. Include only the ones you use. |
| `--dry-run` | Preview the changes without modifying the target repository. |

The paths in `--spec-root`, `--scope` and `--lockfile` are relative to `--target`.
Here, `.` means the target repository's root, even though the installer runs from
the workflow checkout.

Write each check as a JSON list: the executable followed by its arguments.
For example:

| Your project's command | Installer option |
| --- | --- |
| `npm test` | `--check '["npm", "test"]'` |
| `uv run --locked pytest` | `--check '["uv", "run", "--locked", "pytest"]'` |
| `./gradlew test` | `--check '["./gradlew", "test"]'` |

Repeat `--check` for additional required checks. Installation records these
commands; run them to verify the target project as part of adoption. If the
project has dependency lockfiles, declare their paths with `--lockfile`, for
example `--lockfile package-lock.json`.

On a repeat installation for the same OpenSpec home, omitted settings are read
from the saved configuration. A new installation needs real check commands,
supplied by `--check` or the selected home's existing harness configuration.

### Apply to selected folders

Suppose your repository contains `backend/`, `tests/backend/` and `frontend/`.
Keep one `openspec/` at the repository root and select the backend and its tests:

```sh
uv run --locked python tools/workflow.py install \
  --target /path/to/your-repository \
  --scope backend \
  --scope tests/backend \
  --check '["npm", "--prefix", "backend", "test"]' \
  --agent codex --agent claude \
  --dry-run
```

This example puts specifications in `openspec/` and applies the process to
`backend/` and `tests/backend/`. It assumes the backend uses `npm test`; replace
the check if your project uses another command. The source scope excludes
`frontend/`. Installation also adds shared workflow files and scoped agent
instructions at the repository root.

If the backend already has its own `backend/openspec/`, use that home by adding
`--spec-root backend` to the initial installation command. These are alternative
layouts; choose the existing home before installing. One OpenSpec home can cover
several source directories. Independently developed components can use separate,
non-nested homes with non-overlapping scopes. See [scope and routing](docs/scope.md).

### Configure the project

Keep OpenSpec data and harness configuration in their respective directories:

| File | What belongs there |
| --- | --- |
| `openspec/config.yaml` or `config.yml` | OpenSpec's schema, project context, document rules and operation guidance. Existing content is preserved. |
| `agentic_harness/config/workflow.yaml` | Source paths, executable checks, environment preparation and evidence exclusions for a root OpenSpec home. |
| `openspec/dependency-map.yaml` | This workflow's ordered changes and dependencies, kept beside the changes they describe. |
| `agentic_harness/` | The installed process and execution tools, shared across OpenSpec homes in the repository. |

For a component home such as `backend/openspec/`, its harness settings live in
`agentic_harness/config/backend/workflow.yaml` and its dependency map lives in
`backend/openspec/dependency-map.yaml`. The path follows the OpenSpec home; no
configuration name is required. `harness.py project --at backend` reports the
selected settings path in its `workflow` field.

For the selected-folder example, the installer creates settings like these:

```yaml
# agentic_harness/config/workflow.yaml
schema_version: 1
code_roots: [backend, tests/backend]
checks:
  - [npm, --prefix, backend, test]
environment:
  lockfiles: []
  prepare: []
evidence_exclude: []
```

All paths in this file are relative to the Git worktree root, including when the
file lives in `agentic_harness/config/backend/`. Checks and preparation commands run from that
same root. Declare real dependency locks and any required preparation commands;
the empty lists above do not imply that the application needs none.

The harness configuration and dependency map are SDW additions. Native OpenSpec
configuration supplies project context and rules. Configuration under
`agentic_harness/config/` belongs to the consumer project and is preserved during
package updates. Edit the appropriate file, then run `update --dry-run`
and apply the update to refresh routing and integrity records. Do not edit the
package's policy files to configure an application.

The installer maintains `agentic_harness/projects.yaml` as an internal index of
OpenSpec homes. Its stable identifiers connect run history and evidence. Normal
setup and selection use paths; old `--project NAME` arguments remain supported
for compatibility. Do not rename those identifiers or maintain a second copy of
the settings in the index.

### Check or update an installation

Run these commands from the workflow checkout:

```sh
uv run --locked python tools/workflow.py doctor --target /path/to/your-repository
uv run --locked python tools/workflow.py update --target /path/to/your-repository --dry-run
```

An update uses the workflow checkout from which the command is run. Review its
version and changes first. Local edits to package-managed files are conflicts;
project configuration and product specifications remain locally owned.

For installations under `_agentic_harness/`, the update migrates verified
package-owned files and the internal index to `agentic_harness/` and refreshes
the owned instructions. Use the installer for this move so ownership, conflicts
and rollback are checked. Afterward, use the new path in your own shell commands
or scripts. Unowned files, old dependency caches and virtual environments remain
at their original paths; the legacy ignore file is retained when needed to keep
those leftovers ignored. The update reports retained content instead of deleting it.

If local commands, scope paths or dependency locks still refer to managed files
under the old directory, migration stops for reconciliation. Resolve those
references in the project's workflow settings and retry the dry-run. Preserve
old-path evidence exclusions that protect files remaining in the legacy directory.

The update also moves settings from legacy `openspec/workflow.yaml` files or
inline registrations to `agentic_harness/config/`, renames each `queue.yaml` to
`dependency-map.yaml`, and retains existing internal identifiers. It preserves
file contents and permissions when moving existing settings and maps. The map
keeps its ordered `queue` list and dependency rules; only the filename changes.
Equivalent old/new files can be explicitly coalesced by the installer; conflicting
files require reconciliation. Normal runtime selection rejects duplicate authority.

The three `sdw-*` skill bodies live once under `agentic_harness/skills/`. Selected
agent discovery directories contain relative directory symlinks to them. Updates
replace verified old copies only when each old directory contains its owned
`SKILL.md` and nothing else. Edited copies, extra files or directories, and
unexpected links are reported as conflicts. A filesystem unable to create the
links fails installation; the tool does not silently substitute duplicate copies.
If an installation fails, it restores uncontested prior state and reports any
concurrent edits that require recovery. Inspect `--dry-run` before applying.
Active runs retain their original worktree, runtime and evidence; they are not
migrated in place.

## Use the installed workflow

The installer links `sdw-run`, `sdw-harden` and `sdw-review` skills for selected
agents, adds role definitions under the `sdw-` namespace, a scoped instruction block,
and the `agentic_harness/` runtime. It does not replace global model settings.

For example, `.agents/skills/sdw-run` and `.claude/skills/sdw-run` point to
`../../agentic_harness/skills/sdw-run`. Each link names one skill, preserving
other agent skills and OpenSpec-generated integrations. Relative links stay
within the current checkout when the repository is cloned or used in a worktree.

From the target repository's Git worktree root, inspect the selected OpenSpec
home and list its changes:

```sh
uv run --locked --project agentic_harness python \
  agentic_harness/tools/harness.py project

uv run --locked --project agentic_harness python \
  agentic_harness/tools/harness.py openspec -- list --json
```

Here `uv --project agentic_harness` selects the tools' Python environment.
It is a uv option, not a workflow name.

When several homes exist, select one by directory:

```sh
uv run --locked --project agentic_harness python \
  agentic_harness/tools/harness.py project --at backend

uv run --locked --project agentic_harness python \
  agentic_harness/tools/harness.py openspec --at backend -- list --json
```

`--at` is relative to the Git worktree root. Without it, selection uses the
nearest OpenSpec home above the current directory. If no home is found, the
sole installed home can be selected automatically. An ambiguous choice or a
nearer OpenSpec home that has not adopted this workflow stops the command.

The agent follows the [policy map](agentic_harness/policies/README.md) and
[execution procedure](agentic_harness/procedures/execute.md). The runtime is a
set of explicit phase tools, not an unattended task runner. The agent prepares
and verifies the requests, selected project, authorizations and original evidence.
Read-only discovery does not claim work or start the next task.
Use the `sdw-*` skills to run this process. Ordinary OpenSpec commands remain
available, but running `/opsx:apply` alone does not invoke this workflow's
independent reviews, accounting or final acceptance checks.

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
[plans.yaml](agentic_harness/plans.yaml). Their model choices and limits are
configuration, not measured claims of equivalent quality or savings. Verify
provider availability before launching a run. Native model calls and GitHub
publication require the applicable task authority.

## OpenSpec ownership

OpenSpec 1.14.3 generates its own `openspec-*` skills and any selected `opsx-*`
commands. This workflow does not modify or shadow those files. Its own policy,
roles and skills have separate ownership. Upstream updates must leave them intact.
Product specs, changes and project context belong to the target project.

OpenSpec's built-in `spec-driven` schema already provides the proposal, design,
specifications and tasks used by this workflow. No custom schema is required.
Existing custom schemas are preserved, but execution requires compatible
`proposal.md`, `design.md`, `tasks.md` and `specs/<capability>/spec.md` artifacts.
Preserving a schema does not establish support for arbitrary artifact layouts.

The original GitBob importer skills already matched clean OpenSpec output. The
custom root wrappers are replaced by the `sdw-*` entrypoints in this extraction.
See the [extraction inventory](docs/extraction.md) and [provenance](NOTICE.md).

## Develop this package

```sh
uv sync --locked
npm --prefix agentic_harness ci --ignore-scripts
uv run --locked pytest
```

### Build the visual handbook

Edit the Markdown policies and procedures, `plans.yaml`, or the handbook's
graph and templates. Rebuild the generated page with:

```sh
uv run --locked python agentic_harness/tools/build.py
uv run --locked python agentic_harness/tools/build.py --check
```

The builder writes only `agentic_harness/index.html`. Its `--check` mode is
read-only and fails if the page is missing or outdated; CI runs that check.
The page, generator and required inputs are also included in consumer installs.
Neither build mode changes agent settings or OpenSpec-generated integrations.

For presentation changes, verify the diagram in an isolated offline
Chrome/Chromium browser, then inspect desktop and narrow screenshots:

```sh
uv run --locked python agentic_harness/tools/check_render.py
```

This browser check verifies the handbook's presentation. It is not automatically
added to a consumer's product checks.

The tests cover runtime accounting and recovery, project scope, retained source,
installer behavior and real pinned OpenSpec generation. Native-provider and
GitHub transport tests use substitutes; they do not prove live account capability,
model quality or billing. Coordination is local to one clone's shared Git
directory. A scoped instruction or assignment is not an operating-system sandbox.

The verified contracts live under [openspec/specs/](openspec/specs/). The
[archived extraction and verification](openspec/changes/archive/2026-11-10-26-11-10-001-extract-portable-workflow/verification.md)
record the delivered scope and checks. GitBob's migration is a separate follow-up;
this repository does not alter its checkout, active runs or existing evidence.
