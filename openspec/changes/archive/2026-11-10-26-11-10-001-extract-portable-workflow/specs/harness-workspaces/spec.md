## ADDED Requirements

### Requirement: Host-local atomic execution claims

The harness SHALL keep mutable execution claims outside versioned planning
documents in the repository's resolved Git common directory. Linked worktrees
SHALL share atomic ownership for a project-qualified change. Claims SHALL bind
repository, project/change, run/session, worktree/base and authority. The
guarantee SHALL exclude independent clones and other machines.

#### Scenario: SDW-W01 Two linked worktrees claim the same change

- **WHEN** two sessions concurrently request ownership of one qualified change
- **THEN** only one obtains implementation ownership
- **AND** the other receives a blocking claim state without launching another writer
- **AND** claim completion or release preserves history without starting the next task.

### Requirement: Owned isolated worktrees

Implementation SHALL use a recorded worktree and immutable base under an allowed
parent. Creation or adoption SHALL verify repository identity, branch, revision,
ownership and source state. The harness SHALL preserve unrelated work and SHALL
NOT silently stash, reset or clean an unowned checkout to make adoption succeed.

#### Scenario: SDW-W02 A proposed workspace contains unrelated edits

- **WHEN** adoption finds a dirty or mismatched workspace
- **THEN** it refuses adoption and reports the required reconciliation
- **AND** existing files, branches and other worktrees remain unchanged.

### Requirement: Declared environment inputs and explicit rebind

Environment bindings SHALL record declared lockfile paths and their content
fingerprints, including absence as a distinct value. An empty lockfile list
SHALL be valid. Preparation commands SHALL be explicit project configuration;
recording them SHALL NOT execute them. Changes to declared input contents SHALL
require verified preparation evidence and an explicit rebind under the recorded
policy. A changed environment policy SHALL require a new explicitly scoped run.

#### Scenario: SDW-W03 A previously absent lockfile appears

- **WHEN** a declared lockfile is created, deleted or modified after workspace binding
- **THEN** the old environment binding no longer matches
- **AND** resume requires reconciled preparation and externally retained original evidence
- **AND** changing the declared policy cannot be authorized by an input-content rebind
- **AND** a JavaScript or Java project is not required to create a Python lockfile.

### Requirement: Exact assignment scope and frozen review inputs

Writer admission SHALL check canonical exact file assignments against current
intake authority and registered project areas. Concurrent writers SHALL have
exclusive paths. Read-only review SHALL use a frozen retained tree with outputs
outside it. These controls SHALL be described as assignment and workspace
controls, not operating-system isolation for each source directory.

#### Scenario: SDW-W04 A writer claims a neighboring component

- **WHEN** an assigned file lies outside the registered or authorized scope
- **THEN** dispatch rejects the assignment before launch
- **AND** a shared dependency's readability does not imply write ownership
- **AND** required planning and integration edits have explicit authorized ownership.

### Requirement: Complete retained source and configurable exclusions

Review bundles SHALL preserve named public source bytes, executable modes,
intended untracked files and deleted originals against the pinned base. Bundle
destinations SHALL be fresh and outside the worktree. Known secret and metadata
paths, ignored content and aliases SHALL be rejected. Project-specific exclusions SHALL come
from explicit bindings rather than generic application directory names.

#### Scenario: SDW-W05 Review legitimate code under a data directory

- **WHEN** a project names ordinary tracked source under `data/` or `runtime/`
- **THEN** the directory name alone does not exclude it from review
- **AND** secret rules and declared evidence exclusions still apply
- **AND** tampered bytes, changed modes, missing deleted originals or an aliased source invalidate evidence.

### Requirement: Recover uncertain execution before reuse

Interrupted or uncertain native operations SHALL retain their original identity,
counter debit, evidence and coordination reservation until outcome reconciliation.
Resume SHALL inspect attempted writer edits and current inputs before reuse.
Missing results SHALL remain unavailable instead of being replaced by summaries
or silently replayed mutations.

#### Scenario: SDW-W06 A worker may still be running after transport loss

- **WHEN** a launch has an uncertain outcome
- **THEN** its occupied capacity is retained until verified recovery establishes the outcome
- **AND** sibling attempts settle before dependent edits resume
- **AND** recovery reconciles usage once and does not reset counters or blindly relaunch the assignment.

### Requirement: Dependency-aware bounded cleanup

Cleanup SHALL inventory the exact owned worktrees and registered process,
environment and evidence dependencies. It SHALL require applicable cleanup
authority and recheck protections before normal non-forced Git removal. Branch
deletion SHALL remain a separate action. The guarantee SHALL cover registered
dependencies, not undiscovered external processes.

#### Scenario: SDW-W07 A retained dependency protects a worktree

- **WHEN** cleanup finds dirty work, an active assignment or a registered live dependency
- **THEN** the protected worktree is retained with the reason reported
- **AND** authorized removal of another eligible worktree preserves external evidence
- **AND** completion of a PR or run does not authorize forced removal or branch deletion.
