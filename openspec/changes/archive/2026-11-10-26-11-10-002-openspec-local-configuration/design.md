# Design

## Native configuration and workflow settings

`openspec/config.yaml` or `config.yml` remains native, project-owned OpenSpec
configuration. Existing bytes, schema choices and templates are preserved.
The built-in spec-driven artifacts already provide proposal, design, tasks and
capability deltas. A new review artifact would not enforce independent review,
so this change retains the native schema and the SDW execution engine.

Each adopted OpenSpec home has `openspec/workflow.yaml` with `schema_version: 1`,
`code_roots`, required argv `checks`, optional `environment` and
`evidence_exclude`. Paths remain relative to the Git worktree root; checks run
there. The queue stays at `openspec/queue.yaml`. These are SDW extensions, not
new native OpenSpec fields. No executable settings are copied into native config.

The internal `_agentic_harness/projects.yaml` becomes a version-2 index from
stable IDs to OpenSpec roots. It does not duplicate settings. Runtime readers
normalize this index and its companion files to the existing internal model.
Legacy version-1 inline registrations remain readable until explicitly updated.

## Selection and stable identity

Install chooses an existing ID by OpenSpec root or generates one for a new root.
`--project` remains an optional compatibility override. Ordinary commands need
no name. `harness.py project --at PATH` and `openspec --at PATH -- COMMAND` select
by a canonical existing repository-relative directory. Without a selector,
front-end commands use the nearest local OpenSpec home; a nearer unadopted home
is an error. When no such home is available, one registered workflow can be
selected automatically. Multiple candidates require an explicit directory.

Admitted runtime requests still carry resolved immutable IDs. Cwd changes never
retarget a ledger, claim, assignment or retained source. Non-overlap checks and
explicit task/write boundaries remain unchanged. A directory is not a sandbox.

The wrapper rejects native external-store selectors and store configuration
pointers before execution. They would otherwise override its selected working
directory while diagnostics still named the local home. Read-only references
remain native configuration; they do not select a different write destination.

## Migration and ownership

Install/update produces one plan for index and companion changes, native
generation, package files and instruction blocks. Migration preserves IDs,
checks, scope, exclusions and preparation settings. Existing equivalent companion
bytes are preserved; conflicts stop before writes. Missing version-2 companion
files fail rather than causing default settings to replace lost configuration.

Observe configuration before reading it and recheck before mutation. The
manifest settings digest covers expanded settings, so a change to checks or
scope cannot bypass drift detection by leaving the index unchanged. Existing
transaction rollback and active-run protection apply to migration as well.

## Evidence and acceptance

Final acceptance requires the actual companion carrying checks in its reviewed
source set, in addition to the index, native config and lifecycle artifacts.
Pinned-base privacy reads version-2 companions from that same immutable commit;
deleting a file or changing today's exclusions cannot reveal historical private
content. Malformed or missing pinned authority fails closed.

## Compatibility and limits

Do not silently migrate active runs, rekey historical records or change review
limits. Old positional ID commands still work. Native generated skills stay
unchanged. SDW entrypoints continue to orchestrate independent reviews and
verified checks; native `/opsx` commands alone do not claim SDW acceptance.
Custom schema files are preserved, but execution still requires the existing
proposal/design/tasks and capability-delta layout. Arbitrary schema layouts,
external stores and nested independent workflow roots are separate work.

## Verification

Cover unnamed install and repeat no-op; root and selected-folder adoption;
legacy loading and exact migration; disagreement, missing authority and
concurrent edits; directory selection and unregistered nearer roots; historical
privacy and omitted final check authority. Run the full suite and pinned strict
OpenSpec validation. Rehearse actual generation and migration in temporary Git
repositories, preserving native config and unrelated settings.
