# Spec Delta

## MODIFIED Requirements

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
