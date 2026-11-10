# Spec Delta

## MODIFIED Requirements

### Requirement: Canonical package ownership

The workflow SHALL keep its runtime, policies, procedures, role contracts,
plan catalog and canonical SDW skills under `agentic_harness/`. An installation
manifest SHALL record package version, payload identity, and typed ownership of
installed files, discovery links and instruction blocks. Project-owned settings
and product specifications SHALL remain distinct from package-managed content.

#### Scenario: SDW-C01 Identify the installed process

- **WHEN** a developer inspects an installed workflow
- **THEN** the manifest identifies its workflow version and managed content
- **AND** the internal index identifies OpenSpec homes without duplicating local settings or process rules
- **AND** an integrity check reports changed or missing managed content, including link types and exact link targets
- **AND** settings under `agentic_harness/config/` remain consumer-owned and are excluded from the distributed package payload.

### Requirement: Explicit logical project registration

The workflow SHALL register one logical project with one OpenSpec home, one
dependency map, one or more code roots and explicit checks. The repository root
`.` SHALL be supported for a home or scope, while exact file locators SHALL
reject it. Registration paths SHALL be canonical, repository-relative and free
of traversal or symlink aliases. Unknown or ambiguous selection SHALL fail.

#### Scenario: SDW-C02 Select a domain spanning folders

- **WHEN** a project owns `apps/api/` and `tests/api/` with an explicitly chosen OpenSpec home
- **THEN** both code roots resolve to that project's single specification authority
- **AND** a project may be selected by its OpenSpec directory or unambiguous local context; unknown or ambiguous selection fails
- **AND** the installer rejects conflicting homes or overlapping project scopes before mutation
- **AND** root-level integration files do not silently make all application code part of the scope.

### Requirement: Safe and repeatable adoption

The installer SHALL prepare a complete installation plan and detect collisions
before writing target content. A dry-run SHALL leave the target unchanged.
Repeated installation with unchanged inputs SHALL introduce no further content
or path-type changes. Existing instructions SHALL be preserved outside the
package's marked blocks; agent settings SHALL NOT be replaced wholesale.

#### Scenario: SDW-C05 Adopt a repository with local instructions

- **WHEN** a repository already has instructions, agent settings and an OpenSpec configuration
- **THEN** adoption preserves those settings and product artifacts
- **AND** package guidance is confined to its owned blocks and namespaced files
- **AND** a repeat invocation produces no content or path-type changes
- **AND** a collision or malformed ownership block is reported without overwriting local work.

### Requirement: Reviewed updates and integrity checks

An update SHALL use recorded ownership to detect edited or missing managed
files and links and SHALL expose its planned changes. It SHALL preserve local
workflow settings and instruction text outside owned blocks. Its configuration
digest SHALL cover expanded executable settings. A read-only integrity check
SHALL identify invalid bindings, drift and unavailable required tooling.

#### Scenario: SDW-C06 A consumer edits an installed policy

- **WHEN** an update finds a package-managed policy that differs from its recorded digest
- **THEN** the update stops with a conflict instead of replacing that policy
- **AND** the local edit remains available for deliberate reconciliation
- **AND** an edit outside an owned instruction block is preserved and does not become package ownership.

#### Scenario: SDW-C17 A discovery link changes after installation

- **WHEN** a managed discovery link is missing, replaced by a file or directory, or has different literal link text
- **THEN** doctor reports drift and update refuses to silently repair or adopt it
- **AND** a different relative spelling that resolves to the same target is still drift
- **AND** a change to the canonical skill body is checked against its own managed-file identity.

### Requirement: Compatible migration of local workflow settings

The installer SHALL migrate legacy inline or OpenSpec-local settings to the
harness configuration layout as one reviewable plan. It SHALL preserve stable
IDs, executable settings, native configuration, schema files and historical
records. Conflicting or missing indexed authority SHALL block before writes.
Equivalent destinations SHALL retain their bytes and modes; reads and mutations
SHALL retain concurrent-edit detection and rollback.

#### Scenario: SDW-C08 Update a legacy installation

- **WHEN** an idle installation with inline settings or `openspec/workflow.yaml` is updated
- **THEN** the planned diff moves its settings to the selected home's deterministic harness configuration path
- **AND** internal identity, commands, scope, locks, exclusions and Git-root-relative semantics are preserved
- **AND** a sole legacy settings file moves without rewriting its bytes or permissions
- **AND** inline settings are serialized only when no equivalent settings file already exists
- **AND** old index formats remain readable under their original layout before migration
- **AND** repeated installation with the same saved settings creates no further changes.

#### Scenario: SDW-C09 Preserve evidence authority through migration

- **WHEN** a workflow uses local settings for checks or evidence exclusions
- **THEN** final acceptance requires the selected settings file in the reviewed source
- **AND** deleted original files retain exclusions read from the same immutable Git base, using that base's index schema and package path
- **AND** missing, invalid or ambiguous historical authority prevents private content capture
- **AND** editing current settings does not rewrite a past run's identity or evidence.

#### Scenario: SDW-C18 Conflicting settings coexist

- **WHEN** an installation has incompatible inline, legacy-file or harness-file settings for one home
- **THEN** the installer reports the conflicting paths and preserves every copy without mutation
- **AND** normal runtime selection does not choose between legacy and new files even when their settings are equivalent
- **AND** only an explicit installer plan may coalesce equivalent copies, retaining the destination's original bytes and permissions.

## REMOVED Requirements

### Requirement: OpenSpec-local executable configuration

**Reason**: Executable SDW settings belong to the harness integration rather than
the native OpenSpec namespace.

**Migration**: Move each home's `openspec/workflow.yaml` to its deterministic
`agentic_harness/config/` path through the reviewed installer; preserve settings,
stable IDs and native OpenSpec configuration. The replacement requirement is
Harness-owned executable configuration.

## ADDED Requirements

### Requirement: Harness-owned executable configuration

Project-owned settings SHALL live at `agentic_harness/config/workflow.yaml` for
home `.` and `agentic_harness/config/<home>/workflow.yaml` for other homes. Index
schema 3 SHALL contain stable IDs mapped only to roots. Settings paths and
commands SHALL remain Git-root-relative. Native context, rules and schema
selection SHALL remain in OpenSpec configuration. Installation SHALL NOT require
a user-chosen ID.

#### Scenario: SDW-C11 Configure checks for the selected home

- **WHEN** a developer installs the workflow without supplying a registration name
- **THEN** the installer retains or creates a stable internal identity for the selected home
- **AND** source scope, checks, environment and exclusions live in that home's harness settings file
- **AND** the internal index contains roots rather than another copy of executable settings
- **AND** ordinary selection still uses the home directory, including homes with spaces in their paths.

#### Scenario: SDW-C19 Independent homes retain independent settings

- **WHEN** `services/api` and `services/web` are separately adopted homes
- **THEN** their files are `agentic_harness/config/services/api/workflow.yaml` and `agentic_harness/config/services/web/workflow.yaml`
- **AND** source and test paths may lie outside each home's directory while retaining existing overlap checks
- **AND** selecting the API home grants eligibility only to its exact settings file, its metadata and its adopted source scope
- **AND** it does not grant blanket write eligibility to `agentic_harness/` or the other home's settings.

#### Scenario: SDW-C20 An indexed current configuration is missing

- **WHEN** schema 3 selects a home whose harness settings or dependency map is missing, malformed or aliased
- **THEN** runtime selection and doctor fail with the expected authority path
- **AND** they do not fall back to `openspec/workflow.yaml`, `queue.yaml`, another home or inferred defaults
- **AND** the installer does not recreate missing indexed authority from unrelated settings.

### Requirement: Canonical skills with native discovery links

The three `sdw-run`, `sdw-harden` and `sdw-review` skill bodies SHALL have one
canonical copy under `agentic_harness/skills/<name>/SKILL.md`. Selected providers
SHALL discover them through directory symlinks at `.agents/skills/<name>` or
`.claude/skills/<name>`, with literal target `../../agentic_harness/skills/<name>`.
Canonical payload files SHALL be regular files. Other symlink paths SHALL NOT
gain permission from this exception.

#### Scenario: SDW-C21 Install skills for selected providers

- **WHEN** a repository installs with only Codex selected, or with both Codex and Claude selected
- **THEN** the canonical skill files are installed once and discovery links are installed only for selected providers
- **AND** reading a skill through its canonical or discovery path returns the same body and working Markdown references
- **AND** no generated `openspec-*` skill or `opsx-*` command is changed or replaced by an SDW link
- **AND** discovery ancestors and canonical target ancestors are real directories, and the targets remain inside the worktree without alias traversal.

#### Scenario: SDW-C22 Unsupported link creation fails visibly

- **WHEN** the target filesystem or permissions prevent creation of the required directory symlinks
- **THEN** installation fails with an actionable diagnostic and rolls back applied changes
- **AND** it does not substitute duplicated skills or relax path checks.

### Requirement: Transactional discovery-link migration

An update SHALL replace legacy copied skills with approved discovery links only
after verifying the recorded ownership and complete directory contents. Plans
SHALL distinguish regular files, directories and links, recheck their observed
identities before mutation, and restore changed bytes, types and modes on
failure. Concurrent or unowned content SHALL remain intact.

#### Scenario: SDW-C23 Migrate verified copied skills

- **WHEN** a prior installation contains verified managed `SKILL.md` copies in otherwise empty real discovery directories
- **THEN** dry-run shows the file removal, directory-to-link conversion, canonical skill creation, settings move and dependency-map rename without mutation
- **AND** update replaces each selected provider's directory with the exact approved link
- **AND** a failure after any applied step restores the original file bytes, directory types and file/directory permissions
- **AND** a repeated update has no changes.

#### Scenario: SDW-C24 Preserve an unsafe or concurrently changed discovery path

- **WHEN** a discovery directory contains a modified managed file, unowned child, unexpected nested directory, unsafe link or a newly added concurrent entry
- **THEN** installation reports the conflict without deleting or following that content
- **AND** equivalent-looking absolute links, alternate relative targets, aliased ancestors and dangling or external targets are rejected
- **AND** rollback does not overwrite a concurrent edit that no longer matches the installer's own applied state
- **AND** unrelated links and the existing narrow `CLAUDE.md` to `AGENTS.md` preservation behavior keep their prior rules.
