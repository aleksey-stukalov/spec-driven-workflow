# harness-change-lifecycle Specification

## Purpose
Keep bounded work traceable through planning, implementation, independent verification and truthful specification archival.

## Requirements

### Requirement: Bounded intake and action authority

The harness SHALL record the outcome, acceptance criteria, project/change,
scope, dependencies and applicable authorization before execution. Planning,
review, implementation, publication, merge and cleanup SHALL remain distinct
actions. Existing valid authority SHALL be reused within its stated scope.

#### Scenario: SDW-L01 A request is limited to planning

- **WHEN** the user authorizes local specification work without implementation or remote publication
- **THEN** the harness permits only the applicable planning stages
- **AND** queue entries and historical tickets do not grant additional authority
- **AND** independent authorized work may continue while an unresolved scope question blocks dependent actions.

### Requirement: Verified bounded implementation ticket

The execution runtime SHALL require a verified ticket for code-writing
assignments. The ticket SHALL describe the problem, bounded scope, acceptance,
owning OpenSpec artifacts and dependencies. Ticket creation or modification
SHALL require applicable remote-write authority; historical issues SHALL NOT be
silently repurposed.

#### Scenario: SDW-L02 Implementation has no current ticket

- **WHEN** a code-writing assignment lacks a verified ticket for its current scope
- **THEN** admission fails before launching the writer
- **AND** the lead may retain a concrete ticket draft locally pending publication authority
- **AND** a branch name or historical issue reference does not substitute for the required observation.

### Requirement: Canonical queue and qualified selection

Each project SHALL maintain an ordered queue of stable full change IDs and
dependencies. Selection SHALL validate the queue and prerequisites at the pinned
base. Explicit selection SHALL override ordering but not dependencies, readiness
or authority. Listing and selection SHALL NOT claim or execute work.

#### Scenario: SDW-L03 The next eligible change is incomplete

- **WHEN** the first unfinished dependency-satisfied change lacks required planning or has an execution blocker
- **THEN** selection reports that blocker without silently choosing a later change
- **AND** malformed, duplicate, cyclic or improperly ordered dependencies prevent execution selection
- **AND** an archive in another unmerged worktree does not satisfy a dependency at the pinned base
- **AND** reordering queue entries does not rename their stable IDs.

### Requirement: Truthful planning and specification completion

The harness SHALL distinguish artifact existence, planning readiness,
implementation verification and accepted delivery. New behavior SHALL have
capability deltas and concrete scenarios. Only implemented and verified work
SHALL be synchronized into the baseline and archived in its implementation
change, with affected references updated.

#### Scenario: SDW-L04 Artifact status claims completion without evidence

- **WHEN** design or tasks are missing, tasks are empty, or checked tasks lack required verification
- **THEN** the change remains incomplete
- **AND** an OpenSpec artifact status, archived label or merged partial implementation does not prove delivery
- **AND** unfinished behavior stays in an active change rather than being promoted to the baseline.

### Requirement: Explicit non-behavioral maintenance

The harness SHALL support `skip_specs: true` for maintenance without capability
changes. This mode SHALL require completed tasks, passing checks and independent
evidence while rejecting capability deltas or changes to main-spec behavior.
It SHALL NOT be used to omit requirements for new behavior.

#### Scenario: SDW-L05 Complete a pure refactor

- **WHEN** a maintenance change explicitly declares `skip_specs: true` and changes no capability contract
- **THEN** acceptance does not require invented capability deltas
- **AND** proposal, design, tasks and all relevant code remain in the verification scope
- **AND** deltas, changed baseline behavior or incomplete checks prevent this completion route.

### Requirement: Independent final-revision acceptance

Design and implementation acceptance SHALL require complete independent review
of the final relevant inputs and passing required checks. Authors SHALL NOT
review themselves. A disputed major or blocker finding SHALL remain blocking;
fixes or material edits SHALL invalidate affected acceptance and require fresh
independent review within the authorized budget.

#### Scenario: SDW-L06 A repair follows review

- **WHEN** a fixer changes code, tests, design or lifecycle artifacts after review
- **THEN** the affected checks and review inputs are reconciled to the final content
- **AND** both required independent review lenses cover that content before acceptance
- **AND** missing reports, incomplete coverage, serious disputes or exhausted capacity produce incomplete results instead of success.

### Requirement: Reviewable GitHub handoff and decision records

The GitHub workflow SHALL keep one coherent PR per bounded implementation scope,
with accurate ticket, change, base, verification and limitation references.
Material human decisions SHALL be reflected in the owning artifacts and in
authorized ticket or PR updates. Publication SHALL preserve existing action
authority and SHALL NOT imply merge permission.

#### Scenario: SDW-L07 Prepare a reviewable result without publication authority

- **WHEN** a coherent checked implementation slice or material decision is ready to share
- **THEN** the lead prepares the concrete PR or comment content
- **AND** without applicable publication authority it remains local
- **AND** routine polling and worker launches do not become external progress messages.

### Requirement: Reconcile uncertain external mutations

The harness SHALL journal external mutations by operation identity, target,
payload hash and observed result. An uncertain operation SHALL be reconciled
against remote state before retry. Unknown completion SHALL neither be reported
as success nor cause blind duplicate creation.

#### Scenario: SDW-L08 GitHub accepts a request but its response is lost

- **WHEN** an authorized issue, PR, comment or state-changing request has an uncertain outcome
- **THEN** the original operation and authorization remain recorded
- **AND** matching remote state is bound to the existing operation when verified
- **AND** unresolved or conflicting remote state blocks replay without fabricating a receipt.

### Requirement: Separate readiness, merge and continuation

Readiness SHALL require final-source checks, complete independent evidence and
the truthful same-change OpenSpec lifecycle. Merge SHALL additionally require
applicable authority and a recheck of the current target and head. Neither
handoff nor merge SHALL automatically claim another task or remove worktrees.

#### Scenario: SDW-L09 Hand off a verified unmerged change

- **WHEN** final verification passes but merge authority is absent
- **THEN** the result is handed off for review and remains unmerged
- **AND** it does not satisfy another task's accepted-base dependency
- **AND** queue continuation and cleanup remain separately bounded actions.
