# harness-configuration Specification

## Purpose
Define repeatable installation, file ownership, project bindings and pinned toolchain behavior for the portable workflow.

## Requirements

### Requirement: Canonical package ownership

The workflow SHALL keep its runtime, policies, procedures, role contracts and
plan catalog under `_agentic_harness/`. An installation manifest SHALL record
the package version, payload identity and ownership of installed files and
instruction blocks. Local project bindings and product specifications SHALL
remain distinct from package-managed content.

#### Scenario: SDW-C01 Identify the installed process

- **WHEN** a developer inspects an installed workflow
- **THEN** the manifest identifies its workflow version and managed content
- **AND** the internal index identifies OpenSpec homes without duplicating local settings or process rules
- **AND** an integrity check reports changed or missing managed content.

### Requirement: Explicit logical project registration

The workflow SHALL register one logical project with one OpenSpec home, one
queue, one or more code roots and explicit checks. The repository root `.` SHALL
be supported for a home or scope, while exact file locators SHALL reject it.
Paths SHALL be canonical, repository-relative and free of traversal or symlink
aliases. Unknown or ambiguous selection SHALL fail.

#### Scenario: SDW-C02 Select a domain spanning folders

- **WHEN** a project owns `apps/api/` and `tests/api/` with an explicitly chosen OpenSpec home
- **THEN** both code roots resolve to that project's single specification authority
- **AND** a project may be selected by its OpenSpec directory or unambiguous local context; unknown or ambiguous selection fails
- **AND** the installer rejects conflicting homes or overlapping project scopes before mutation
- **AND** root-level integration files do not silently make all application code part of the scope.

### Requirement: Unmodified pinned OpenSpec integration

The workflow SHALL use the published OpenSpec 1.14.3 toolchain and supported
configuration interfaces. OpenSpec SHALL own its generated skills and commands.
Workflow-specific roles and skills SHALL use the `sdw-*` namespace. The workflow
SHALL NOT patch upstream-generated bodies or shadow their names with wrappers.

#### Scenario: SDW-C03 Refresh upstream integration

- **WHEN** a project is initialized and its OpenSpec integrations are updated with the pinned CLI
- **THEN** upstream-owned generated files match clean generation for the same selected settings
- **AND** the `sdw-*` integrations remain separate and available
- **AND** existing product specifications and project context remain unchanged
- **AND** generation does not change the user's global OpenSpec configuration
- **AND** differing pre-existing files at claimed integration paths produce a conflict before adoption.

### Requirement: Explicit OpenSpec command routing

The workflow SHALL route supported OpenSpec commands through the package-local
pinned toolchain from the selected project directory and preserve their arguments.
It SHALL reject store selectors or configuration pointers that override that
local home. It SHALL NOT create another specification home to avoid a missing
root or retarget admitted records when the working directory changes.

#### Scenario: SDW-C04 Invoke a component from the repository root

- **WHEN** a component directory is selected while the shell is at the repository root
- **THEN** the wrapper selects that component's OpenSpec home and reports the selection
- **AND** missing registered artifacts or an unavailable pinned toolchain prevent the operation
- **AND** unchanged upstream skill instructions use the same selected command route.

#### Scenario: SDW-C10 A native selector would bypass local routing

- **WHEN** a caller supplies an external-store selector or the selected native configuration points to a store
- **THEN** the local wrapper stops before invoking OpenSpec
- **AND** the error identifies the unsupported routing rather than reporting the local home as the destination.

### Requirement: Safe and repeatable adoption

The installer SHALL prepare a complete installation plan and detect collisions
before writing target content. A dry-run SHALL leave the target unchanged.
Repeated installation with unchanged inputs SHALL introduce no further content
changes. Existing instructions SHALL be preserved outside the package's marked
blocks; agent settings SHALL NOT be replaced wholesale.

#### Scenario: SDW-C05 Adopt a repository with local instructions

- **WHEN** a repository already has instructions, agent settings and an OpenSpec configuration
- **THEN** adoption preserves those settings and product artifacts
- **AND** package guidance is confined to its owned blocks and namespaced files
- **AND** a repeat invocation produces no content changes
- **AND** a collision or malformed ownership block is reported without overwriting local work.

### Requirement: Reviewed updates and integrity checks

An update SHALL use recorded ownership to detect edited or missing managed
files and SHALL expose its planned changes. It SHALL preserve local workflow
settings and instruction text outside owned blocks. Its configuration digest
SHALL cover expanded executable settings, including companion files. A read-only integrity
check SHALL identify invalid bindings, drift and unavailable required tooling.

#### Scenario: SDW-C06 A consumer edits an installed policy

- **WHEN** an update finds a package-managed policy that differs from its recorded digest
- **THEN** the update stops with a conflict instead of replacing that policy
- **AND** the local edit remains available for deliberate reconciliation
- **AND** an edit outside an owned instruction block is preserved and does not become package ownership.

### Requirement: Development dependencies and historical runs stay separate

Workflow dependencies SHALL be installed separately from the target application's
dependency files. Target preparation and checks SHALL come from explicit local
bindings, without requiring a particular application language. Updating the
package SHALL NOT reinterpret an existing run under a different policy; an
operator SHALL retain the original worktree, runtime and evidence for resume.

#### Scenario: SDW-C07 Adopt a non-Python application

- **WHEN** a JavaScript project without `uv.lock` adopts the workflow
- **THEN** the workflow's Python and Node dependencies stay in its tooling area
- **AND** its application dependency files and scripts are preserved
- **AND** new runs use the selected installed version while historical runs retain their original environment and evidence semantics.

### Requirement: Compatible migration of local workflow settings

The installer SHALL migrate legacy inline registrations into local companion
files and an internal index as one reviewable plan. It SHALL preserve stable IDs,
all executable settings, native OpenSpec configuration and schema files, and
historical execution records. Equivalent existing companion files SHALL retain
their bytes; conflicting or missing indexed authority SHALL block before writes.
Reads and mutations SHALL retain concurrent-edit detection and rollback.

#### Scenario: SDW-C08 Update a legacy installation

- **WHEN** an idle legacy installation is updated
- **THEN** the planned diff moves its settings beside its existing OpenSpec home
- **AND** the internal identity, commands, scope, locks and exclusions are preserved
- **AND** the old inline format remains readable before migration
- **AND** repeated installation with the same saved settings creates no further changes.

#### Scenario: SDW-C09 Preserve evidence authority through migration

- **WHEN** a workflow uses companion settings for checks or evidence exclusions
- **THEN** final acceptance requires that companion in the reviewed source
- **AND** deleted original files retain exclusions read from the same immutable Git base
- **AND** missing or invalid historical authority prevents private content capture
- **AND** editing current settings does not rewrite a past run's identity or evidence.

### Requirement: OpenSpec-local executable configuration

Project-owned executable settings SHALL live in `openspec/workflow.yaml` beside
native OpenSpec configuration. The internal index SHALL retain stable IDs and
OpenSpec roots without duplicating these settings. Installation SHALL NOT require
a user-chosen ID. Native context, rules and schema selection SHALL remain in
OpenSpec's supported configuration.

#### Scenario: SDW-C11 Configure checks beside specifications

- **WHEN** a developer installs the workflow without supplying a registration name
- **THEN** the installer retains or creates a stable internal identity for the selected home
- **AND** source scope, checks, environment and exclusions live in that home's companion file
- **AND** the internal index contains roots rather than another copy of executable settings.

### Requirement: Directory-based workflow selection

Front-end commands SHALL support explicit directory selection and nearest local
OpenSpec-home discovery, with a sole-project fallback only when no local home
was found. A nearer unadopted home SHALL block implicit selection. Existing ID
selectors SHALL remain supported and SHALL take precedence over implicit discovery.

#### Scenario: SDW-C12 Select a component from its source directory

- **WHEN** a command without a selector runs below an adopted OpenSpec home
- **THEN** it selects that home and reports its stable internal identity
- **AND** a nearer unadopted home causes an error rather than falling back to another workflow
- **AND** an explicit supported selector resolves independently of the current directory.
