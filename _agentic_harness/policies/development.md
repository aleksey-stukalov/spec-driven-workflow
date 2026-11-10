# Development scope and lifecycle

This policy connects one bounded request, its specification, implementation and
verification. Follow the [OpenSpec policy](openspec.md) for specification state
and the [execution policy](execution.md) for agent runs.

## Intake, tickets and authorization

Record the problem, intended outcome, acceptance criteria, project, affected
paths, dependencies and applicable authorization before implementation. Select
one bounded ticket and keep its description consistent with the owning change.
The execution runtime requires a verified ticket observation for code writers;
do not invent a ticket or remote observation to satisfy that gate.

The supplied remote adapter targets GitHub. Repository identity comes from the
target project and its remote, never from the workflow's source repository.
Other trackers need a separately implemented and verified adapter.

Planning, review, implementation, publication, merge and cleanup are distinct
actions. Use authority already provided for the scope; do not ask for it again.
A planning or setup request does not authorize implementation of product
behavior. Installing this package does not authorize posting issues, comments
or pull requests. Observe the target project's decision-recording rules.

## Worktrees and reviewable changes

Implement in an owned worktree from the agreed base revision. Use the target
repository's branch and commit conventions, with a ticket reference. Keep each
commit and pull request coherent. Include no unrelated local changes.

One pull request covers one independently reviewable implementation scope. Its
description links the ticket and owning OpenSpec change and records relevant
checks, review evidence and limitations. Publish only within the granted scope.
Merge additionally requires merge authority and verification of the current
head; readiness or permission to open a pull request does not imply it.

## Change selection and queue

Resolve the registered project's `queue` from the repository root. Preserve one
queue and one specification authority for that project. Queue entries retain
stable identifiers and dependencies; their order is explicit in the queue, not
in filenames or numeric identifiers.

The current runtime accepts change IDs shaped as
`YY-MM-DD-NNN-short-description`. Keep existing IDs and creation metadata stable.
Do not rename or renumber changes to reorder work. Keep archived entries as
history and keep queue dependencies consistent with proposals.

An explicitly selected change takes precedence over default selection, while
its prerequisites still apply. When implementation is authorized without a
named change, inspect the first unfinished eligible queue item. Queue inspection
and selection are read-only; ownership requires a separate claim. Report a
selected blocked dependency instead of silently substituting another task.

Missing design or tasks, an empty checklist, an archived label or a merged pull
request cannot establish delivery. Check actual artifacts, completed work and
verification evidence. Handoff of one task does not start the next queue item.

## Complete the same change

The implementation pull request also owns its truthful specification lifecycle.
After implementation and verification, mark delivered tasks, synchronize the
implemented deltas and archive completed work with the pinned OpenSpec CLI.
Update affected links, navigation, queue state and project context in that
change. Do not create a later cleanup pull request merely to declare already
delivered behavior complete.

Keep incomplete or partially delivered changes active. If work is split,
record the new ownership and acceptance boundaries without duplicate normative
specifications. Historical work and evidence keep their original meaning.
