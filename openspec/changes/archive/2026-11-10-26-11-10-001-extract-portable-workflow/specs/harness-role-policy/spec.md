## ADDED Requirements

### Requirement: One catalog for shipped role profiles

The harness SHALL define its `plans-v1` roles, boundaries, model/effort routes,
context targets and attempt allowances in one catalog. It SHALL provide the
shipped `budget`, `balanced` and `smart` profiles with `balanced` as default.
Generated native roles SHALL derive from that catalog rather than a second
independently maintained route table.

#### Scenario: SDW-R01 Inspect a native role

- **WHEN** a supported agent loads a generated `sdw-*` role
- **THEN** the role identifies its responsibility and reads the canonical shared procedure
- **AND** its discovery route corresponds to the catalog default
- **AND** selecting the role or skill does not claim to switch a running lead's model or change global settings.

### Requirement: Explicit bounded assignments

Assignments SHALL bind project/change, role, applicable stage, input revision,
exact owned files, expected coverage, tools, budget and stopping condition.
The shipped profiles SHALL allow at most two coordinated workers per run and no
nested delegation. A shared ledger SHALL account for its other runs; separate
ledgers SHALL NOT be described as a host-wide quota. Human authority SHALL
remain outside model output contracts.

#### Scenario: SDW-R02 Dispatch a writer alongside a reviewer

- **WHEN** a role requests an assignment outside its permitted write mode or owned paths
- **THEN** admission rejects it before launch
- **AND** incompatible ownership or unavailable coordinated capacity blocks dispatch
- **AND** the limit is stated for the supported coordination domain, not all processes on a machine.

### Requirement: Complementary independent review rounds

Each counted design or implementation review round SHALL contain two independent
lenses against the same frozen revision. Design lenses SHALL cover contracts
and feasibility risks; implementation lenses SHALL cover behavior/tests and
runtime safety. Review identities SHALL be distinct from authors and other
independent assignments.

#### Scenario: SDW-R03 One review lens is missing

- **WHEN** only one required reviewer returns a complete result
- **THEN** the pair does not count as a complete clean round
- **AND** retained findings remain available without inventing a missing clean result
- **AND** findings requiring adjudication retain their original identities and dispositions.

### Requirement: Durable attempts and post-fix capacity

Attempt counters SHALL survive retries, provider changes and session resume.
Failed admitted launches SHALL count. Both lenses SHALL consume one shared
round, and the selected profile's clean-round minimum SHALL apply to unchanged
accepted inputs. A repair SHALL reserve enough capacity for subsequent required
clean review; exhaustion SHALL produce incomplete work.

#### Scenario: SDW-R04 A repair cannot fit in the remaining allowance

- **WHEN** a confirmed finding needs a repair and more later review capacity than remains
- **THEN** the harness stops before that repair and requests a bounded extension
- **AND** changing the plan or restarting does not reset consumed counters
- **AND** the extension identifies the blocker, used and added allowances, routes, estimates or unknown costs, and stopping condition.

### Requirement: Verified requested settings and context capacity

Before launch the harness SHALL verify required client/account capabilities,
model and effort support, conflicting overrides and effective context capacity.
Requested settings SHALL be recorded separately from runtime-reported settings.
Unknown metadata SHALL remain unknown. Context targets SHALL include room for
tool growth and reserve rather than claim to enlarge provider windows.

#### Scenario: SDW-R05 A required route is unavailable

- **WHEN** the account or client cannot verify a requested route or sufficient context capacity
- **THEN** the assignment is blocked before dispatch
- **AND** the harness does not silently downgrade, substitute models or use extra paid resources
- **AND** partitioning work preserves required coverage and does not truncate findings to obtain success.

### Requirement: Original evidence and honest qualification

The harness SHALL retain complete original prompts, results, requested routes,
reported usage and exact reviewed inputs independently of concise summaries.
Missing, malformed, partial or stale originals SHALL NOT establish acceptance.
Structural parity and synthetic transport tests SHALL NOT be described as paid
model-quality, billing or provider-equivalence measurements.

#### Scenario: SDW-R06 A transport succeeds with an incomplete result

- **WHEN** native transport returns successfully but required structured evidence is incomplete
- **THEN** the phase remains incomplete with known originals preserved
- **AND** unknown actual settings and cost remain unknown
- **AND** the final report distinguishes validated record consistency from review quality or production behavior.

### Requirement: Explicit bounded escalation

Escalation SHALL require a named unresolved question, attempted approaches,
evidence, exact allowed files, one-call maximum and stopping condition. A matching
human authorization receipt SHALL be required before launch. Escalation SHALL
NOT silently expand the underlying assignment or continue the pipeline.

#### Scenario: SDW-R07 A worker cannot resolve a question

- **WHEN** a role requests escalation without a matching bounded receipt
- **THEN** the harness blocks that launch and preserves the unresolved question
- **AND** authorized escalation receives only its recorded files and one-call allowance.

### Requirement: Verified checkpoint and continuation

Before a planned handoff or compaction, the harness SHALL preserve a checkpoint
binding project/change, worktree/base/head, source and original-result hashes,
ownership, decisions, open findings, checks and next action. Resume SHALL verify
those references and retain the original consumed attempts and usage history.

#### Scenario: SDW-R08 Continue after a session handoff

- **WHEN** a new session resumes a recorded checkpoint
- **THEN** missing or changed references and mismatched ownership prevent unverified continuation
- **AND** valid continuation keeps prior counters and unresolved findings rather than starting an apparently fresh run.
