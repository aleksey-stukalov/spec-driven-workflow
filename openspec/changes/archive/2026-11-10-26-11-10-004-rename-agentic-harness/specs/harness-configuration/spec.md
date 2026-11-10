## MODIFIED Requirements

### Requirement: Canonical package ownership

The workflow SHALL keep its runtime, policies, procedures, role contracts and
plan catalog under `agentic_harness/`. An installation manifest SHALL record
the package version, payload identity and ownership of installed files and
instruction blocks. Local project bindings and product specifications SHALL
remain distinct from package-managed content.

#### Scenario: SDW-C01 Identify the installed process

- **WHEN** a developer inspects an installed workflow
- **THEN** the manifest identifies its workflow version and managed content
- **AND** the internal index identifies OpenSpec homes without duplicating local settings or process rules
- **AND** an integrity check reports changed or missing managed content.

## ADDED Requirements

### Requirement: Compatible package directory migration

Updates SHALL migrate verified package ownership from `_agentic_harness/` to
`agentic_harness/` as one reviewable, rollback-capable plan. They SHALL preserve
stable IDs, local settings, upstream integrations and unowned files. Ambiguous
layouts, conflicting destinations and edited managed files SHALL block before
mutation. Historical evidence SHALL retain its original paths and exclusions.

#### Scenario: SDW-C13 Update an installation using the old directory

- **WHEN** an idle verified legacy installation is updated
- **THEN** the dry-run exposes the path migration without changing files
- **AND** managed tools, routing and the internal index use the new directory afterward
- **AND** new destinations corresponding to verified legacy files and their package directories preserve their permissions
- **AND** a repeated update produces no further changes
- **AND** unowned files or dependency caches remaining in the old directory retain their bytes and ignore protection.

#### Scenario: SDW-C14 Reject an unsafe directory migration

- **WHEN** a migration encounters edited managed files, ambiguous installed layouts, a destination conflict or a concurrent edit
- **THEN** it stops without overwriting local work
- **AND** a failure during application restores the previous owned file contents, permissions and configuration
- **AND** active worktrees are not migrated in place.

#### Scenario: SDW-C16 Local commands still use the old package path

- **WHEN** a migration detects explicit local scope, lockfile or command bindings to the old package path
- **THEN** it reports the affected settings for reconciliation before removing their inputs
- **AND** it does not rewrite arbitrary application commands or discard privacy exclusions for retained files.

#### Scenario: SDW-C15 Preserve exclusions from historical package paths

- **WHEN** review source captures deleted originals from a base using the old package directory
- **THEN** exclusions are read from that base's original index and companion files
- **AND** malformed or ambiguous historical authority blocks capture
- **AND** retained bundles keep their original path identities instead of being relabeled.
