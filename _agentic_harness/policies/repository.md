# Repository boundaries

This package governs development within explicitly adopted scopes. It does not
define the target application's architecture, language, data model or runtime.
Read the target repository's instructions and relevant source before proposing
behavior or claiming a capability exists.

## Scope and ownership

Select the OpenSpec directory that owns the requested work. Its
`openspec/workflow.yaml` lists adopted source areas in `code_roots`, while
`openspec/config.yaml` (or the existing `config.yml`) holds native project
context and rules. Paths in workflow settings are relative to the Git worktree
root. One OpenSpec home may cover several source and test directories.
These boundaries are not a filesystem sandbox.
Do not infer write permission from a dependency, a shared parent directory or
the ability to read a file.

Use the selected `id` returned by `harness.py project` in intake, coordination,
dispatch and evidence records. The internal `projects.yaml` index retains that
identity across updates. Directory selection happens before a run; a later
working-directory change must not rebind an admitted request. Legacy inline
settings remain readable until the installer migrates them in a reviewed update.

Each task has a bounded intake scope. Each writer owns exact files within that
scope and the registered areas: adopted code roots and the selected project's
`openspec/` metadata. Shared configuration changes must be named explicitly. Inspect
the full diff before acceptance to catch unassigned additions, deletions and
renames. Preserve unrelated edits and other contributors' work.

Use a dedicated worktree for implementation. Keep the shared checkout and other
worktrees intact. Never reset, stash, clean or remove another task's work as an
automatic recovery step. Use normal, non-forced removal only after checking
ownership, dirty state, active assignments and retained dependencies.

## Project checks and environments

`openspec/workflow.yaml` supplies required checks as argument arrays, not shell
fragments. Checks run from the Git worktree root. Use the project's documented
setup and declared lockfiles. Do not assume that every target uses Python, uv,
npm, or a particular application test
command because the workflow itself uses Python and Node.

Prepare the assigned worktree without changing the project's intended dependency
versions. An intentional dependency-lock change requires environment preparation
and a recorded rebind before execution continues. Preserve the previous
fingerprint and preparation evidence; a new digest alone is not preparation.
Changing which lockfiles or preparation commands are declared changes the
environment policy itself and requires a newly scoped run, not a byte rebind.

Run checks appropriate to changed behavior and the project's requirements. Fix
relevant failures. Do not repeat successful checks on unchanged inputs solely to
consume a quota. Framework documentation-rendering checks belong to framework
development unless a target explicitly registers them.

## Data and external actions

Keep credentials, private exports and operational state out of committed
examples and retained review source. Use synthetic fixtures where practical.
Declare project-specific evidence exclusions in `openspec/workflow.yaml`.
Do not assume that ordinary directories named `data`, `runtime`, `inputs` or
`out` contain private material
in every project. Inspect selected source before capture.

Evidence exclusions are enforced across registered projects so a dependency
read respects its owner's privacy policy. Deleted originals also retain the
pinned base's exclusions; removing an exclusion does not expose a deleted file.

Preserve live data, manual decisions and external state. Tests and command help
do not authorize a live import, deployment, destructive migration or paid model
experiment. Follow existing applicable authorization, and obtain missing
authorization only for the action that needs it.

Report verified facts, assumptions, incomplete checks and unavailable evidence
separately. A passing structural validator does not prove runtime quality,
complete review, model equivalence or production readiness.
