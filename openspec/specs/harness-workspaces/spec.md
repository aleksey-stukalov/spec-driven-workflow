# harness-workspaces Specification

## Purpose
Coordinate owned workspaces, environment recovery and cleanup while preserving unrelated work and retained evidence.

## Requirements

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

Writer admission SHALL check canonical exact assignments against current intake
authority and registered project areas. Only approved SDW discovery links SHALL
be assignable as link leaves; paths through them SHALL remain forbidden.
Concurrent writers SHALL have exclusive paths. Read-only review SHALL use a
frozen retained tree with outputs outside it. These controls SHALL be described
as assignment and workspace controls, not operating-system isolation.

#### Scenario: SDW-W04 A writer claims a neighboring component

- **WHEN** an assigned file lies outside the registered or authorized scope
- **THEN** dispatch rejects the assignment before launch
- **AND** a shared dependency's readability does not imply write ownership
- **AND** required planning and integration edits have explicit authorized ownership.

#### Scenario: SDW-W08 Assign a discovery link without aliasing its target

- **WHEN** an authorized writer is assigned `.agents/skills/sdw-run` as an approved link leaf
- **THEN** admission and coordination retain that lexical path as its ownership identity
- **AND** changing `agentic_harness/skills/sdw-run/SKILL.md` requires its own explicit assignment
- **AND** assigning `.agents/skills/sdw-run/SKILL.md` through an existing link is rejected
- **AND** link replacement and legacy-child conversion assignments cannot run concurrently against the same discovery subtree
- **AND** a component's settings-path eligibility does not authorize edits to shared skills.

### Requirement: Complete retained source and configurable exclusions

Review bundles SHALL preserve named public source bytes, executable modes,
intended untracked files, approved discovery-link identities and deleted
originals against the pinned base. Destinations SHALL be fresh and outside the
worktree. Known secret and metadata paths, ignored content and unapproved aliases
SHALL be rejected. Project exclusions SHALL come from explicit bindings rather
than generic application directory names. Link capture SHALL NOT follow links.

#### Scenario: SDW-W05 Review legitimate code under a data directory

- **WHEN** a project names ordinary tracked source under `data/` or `runtime/`
- **THEN** the directory name alone does not exclude it from review
- **AND** secret rules and declared evidence exclusions still apply
- **AND** tampered bytes, changed modes, missing deleted originals or an unapproved aliased source invalidate evidence.

#### Scenario: SDW-W09 Retain an approved discovery link

- **WHEN** a source capture explicitly includes an approved discovery link and its canonical `SKILL.md`
- **THEN** its revision binds the lexical link path, symlink type, exact relative link text and canonical skill bytes separately
- **AND** the retained bundle stores link text as inert regular data rather than a traversable filesystem link
- **AND** reviewers receive enough metadata to distinguish link records from regular source
- **AND** verification rejects changed link text, changed type, missing canonical skill coverage, undeclared retained entries or changed canonical bytes
- **AND** capture or verification rejects unsafe live ancestors and racing replacement instead of publishing inconsistent evidence.

#### Scenario: SDW-W10 Preserve a copied skill displaced by a directory link

- **WHEN** the pinned base has `.agents/skills/sdw-run/SKILL.md` as a regular file and the current tree replaces its parent directory with the approved discovery link
- **THEN** changed-source inventory includes the new link leaf and the old copied file as a deleted original
- **AND** original bytes and mode come from the immutable base without reading through the live parent link
- **AND** the canonical skill's existence through that link does not hide the deletion
- **AND** final review covers the canonical file, new link identity and displaced original.

#### Scenario: SDW-W11 Retain deleted links

- **WHEN** an approved discovery link is deleted
- **THEN** evidence preserves its original literal target and symlink type from the pinned base
- **AND** no deleted link is followed to obtain target bytes
- **AND** arbitrary historical symlinks remain unsupported review source.

#### Scenario: SDW-W12 Historical exclusions remain authoritative

- **WHEN** a deleted original comes from a base using index schema 1, 2 or 3, including the supported old `_agentic_harness` layout
- **THEN** privacy exclusions come from that base's exact index and corresponding settings files plus current exclusions
- **AND** current schema-3 settings do not substitute for missing or invalid historical files
- **AND** conflicting historical settings authorities fail closed
- **AND** existing schema-2 and schema-3 retained bundles keep their original interpretation and revision identities.

#### Scenario: SDW-W13 Reject unsupported same-leaf type replacement

- **WHEN** capture or changed-source inventory finds a regular-file-to-link or link-to-regular-file replacement at the same lexical path
- **THEN** it fails with an actionable unsupported type-transition error
- **AND** it does not omit the original, follow the link or accept the replacement as an ordinary file edit
- **AND** the supported copied-directory migration remains a deleted child file and a distinct new link leaf.

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
