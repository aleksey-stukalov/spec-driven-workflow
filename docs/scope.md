# Applying the workflow to part of a repository

Choose where the specifications live and which source paths use the process.
For example, one `openspec/` at the repository root can cover `backend/` and
`tests/backend/` while `frontend/` keeps its existing process. No configuration
name is needed.

An OpenSpec home is the directory containing `openspec/`. It may describe the
whole repository, one source directory, or several disjoint directories that
share a change lifecycle. The local `openspec/workflow.yaml` records those paths
and their checks.

## Separate the boundaries

| Boundary | Meaning |
| --- | --- |
| Repository root | Git history, worktrees, shared integration and host-local coordination |
| OpenSpec home | Directory containing `openspec/`; `.` means the repository root |
| `workflow.yaml`'s `code_roots` | Explicit source areas adopted by the process; several paths can share one OpenSpec home |
| Workflow metadata | The selected project's `openspec/` tree, including its specification and queue |
| Shared installation files | Package runtime, namespaced skills and narrowly owned instruction blocks |
| Task scope | Paths authorized for one bounded request |
| Writer ownership | Exact files assigned exclusively to one writer |
| Read and test context | Relevant dependencies and checks needed to understand or verify the change |

These boundaries are related, but they are not interchangeable. An OpenSpec home
can sit at repository root while its project covers only a service and its tests.
A dependency may need to be read without becoming writable. A repository-wide
test may be necessary for a local change without expanding implementation scope.

## Whole repository and selected areas

For whole-repository adoption, keep OpenSpec at the repository root and use
`code_roots: [.]` deliberately. These are the defaults for a new installation.
Secret, ignored and unsafe paths remain unsuitable for retained evidence.
Task and assignment scope
must still be bounded; whole-repository adoption is not unlimited task authority.

For partial adoption, list the actual source and test roots. For example,
`backend` and `tests/backend` may share the root-level `openspec/`. Set
`--scope backend --scope tests/backend` during installation. Configure checks that
validate this behavior and its affected shared interfaces.

Preserve existing OpenSpec homes during adoption. If the backend already has
`backend/openspec/`, choose it with `--spec-root backend`. Use separate homes for
components with independent change lifecycles and clear ownership. A physical
source folder does not need its own separate specification home.

This version does not install independent workflows in nested OpenSpec homes,
even if their code roots are disjoint. A home at the repository root cannot
coexist with another installed home inside a component. Use one root-level home
covering the selected folders or separate non-overlapping homes. This is a
package constraint; OpenSpec itself supports nested-root discovery.

## Configure beside the specifications

The two configuration files have distinct responsibilities:

- `openspec/config.yaml` (or `config.yml`) is native OpenSpec configuration. Use
  it for the schema, project facts, artifact rules and operation guidance.
- `openspec/workflow.yaml` supplies this workflow's executable settings: adopted
  source paths, required checks, environment preparation, dependency locks and
  evidence exclusions.

For example, a backend using npm might have:

```yaml
schema_version: 1
code_roots: [backend, tests/backend]
checks:
  - [npm, --prefix, backend, test]
environment:
  lockfiles: [backend/package-lock.json]
  prepare:
    - [npm, --prefix, backend, ci, --ignore-scripts]
evidence_exclude: []
```

Use the target's actual commands and lockfiles. Every configured path is relative
to the Git worktree root, even if this file is in `backend/openspec/`. Checks and
preparation run from the worktree root. Commands are executable-and-argument
arrays; shell expressions are not expanded. Evidence exclusions identify private
paths that must not enter retained review source, including dependency reads.

After editing these settings, run `update --dry-run` from the workflow checkout,
inspect the plan and apply the update. The installer preserves local settings
and refreshes the generated routing and integrity records. Missing or invalid
settings block execution.

`agentic_harness/projects.yaml` is an internal index of stable identifiers to
OpenSpec homes. Older installations stored all settings there. Update migrates
those settings into the companion files without renaming identifiers, which are
still used by claims, run history and evidence. A conflicting pre-existing
companion prevents migration. Do not keep two editable copies of the settings
or rename the internal identifiers.

## Select by directory

From the Git worktree root, inspect the selection with:

```sh
uv run --locked --project agentic_harness python \
  agentic_harness/tools/harness.py project
```

The wrapper finds the nearest OpenSpec home above the current directory and
uses that home's installed workflow settings. If no home is found, one installed
home can be selected automatically. Several homes require a directory selection
when the current directory cannot distinguish them. A nearer native OpenSpec home
that has not adopted this workflow is an error; the wrapper does not skip it to
select a parent or another component.

For a component with `backend/openspec/`, select its home explicitly when invoking
from the worktree root or working on related tests elsewhere:

```sh
uv run --locked --project agentic_harness python \
  agentic_harness/tools/harness.py project --at backend

uv run --locked --project agentic_harness python \
  agentic_harness/tools/harness.py openspec --at backend -- list --json
```

`--at` accepts an existing directory relative to the Git worktree root. It
selects the OpenSpec home; it does not change `code_roots`, task scope or writer
permissions. `uv --project agentic_harness` selects the Python environment for
the tools and is unrelated to workflow identity. Old positional project names
remain available for compatibility.

After selection, machine requests use the stable `id` returned by `project`.
Changing the shell directory cannot change the identity of an admitted run.
The wrapper invokes the pinned OpenSpec CLI from the selected home and preserves
the command's arguments. Continue to enter the full process through `sdw-*`;
native `/opsx` commands alone do not run the workflow's independent reviews or
final acceptance checks.

## Shared files and overlapping work

Adoption can require shared routing in `AGENTS.md` or `CLAUDE.md` and namespaced
skills under agent discovery directories. These are installation changes, not
an automatic grant for ordinary product changes to rewrite all root settings.
The install record distinguishes package-managed files from project-owned
configuration and generated OpenSpec files.

Name a shared build file, dependency lock, schema or CI configuration explicitly
when a task needs to change it. Include the relevant owner, tests and approval
in the task's scope. A matching parent directory is not sufficient justification
for expanding a narrowly requested change.

Overlapping scopes of independent OpenSpec homes are rejected. If one change spans
multiple homes, resolve its owning changes, specification updates and writer
ownership before dispatch. Do not silently choose a home based on the first
touched file or assume an overlap means both
components can write concurrently. Each bounded run selects one OpenSpec home.
Split independently owned work or explicitly reconcile the configured scope;
do not broaden it implicitly.

## What isolation means here

Worktrees isolate Git working copies. The dispatcher checks declared writer
paths against task and project boundaries and coordinates exclusive ownership.
Final review must inspect the full diff, including new, deleted and renamed
paths. Neither a nested instruction file nor an OpenSpec root is an operating
system sandbox or a guarantee that arbitrary commands cannot write elsewhere.

The coordination database is shared by linked worktrees in one Git common
directory on one host. It does not prevent concurrent work in another clone or
machine. Use the repository's normal remote coordination for those cases.

## Checks for an adoption

Verify the selected OpenSpec root from both repository and component entry
points. Confirm that existing specifications, instructions and unrelated agent
settings remain intact. Inspect the installation diff and repeat installation
to establish that unchanged inputs produce no further edits.

Exercise one bounded change against the adopted paths, including relevant
shared interfaces. Confirm that outside paths are not silently admitted and
that final evidence covers all actual changes. Record the installed package
version and update it through a reviewable change. Package upgrades do not
reclassify historical runs or replace product specifications.

The [extraction inventory](extraction.md) explains what comes from the source
workflow. The executable rules start at the
[policy map](../agentic_harness/policies/README.md).
