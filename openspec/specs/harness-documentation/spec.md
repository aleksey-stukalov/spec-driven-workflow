# harness-documentation Specification

## Purpose
Make the maintained development process discoverable to people and agents while preserving upstream and project ownership.

## Requirements

### Requirement: Agent-readable canonical process guidance

The package SHALL provide a Markdown reading map to its canonical policies,
procedures, role contracts and plan catalog. Guidance SHALL cover intake,
project selection, worktrees, specification lifecycle, review, evidence, recovery
and authorized handoff without requiring HTML or private project data.

#### Scenario: SDW-D01 A fresh agent starts a scoped change

- **WHEN** the agent reads the installed entrypoint for an applicable project
- **THEN** it can locate the required policies and phase procedure through explicit links
- **AND** the instructions distinguish required reads from automatic imports
- **AND** commands resolve from the worktree root and identify the selected project.

### Requirement: Reproducible adoption and upgrade instructions

Documentation SHALL explain required tooling, pinned versions, installation
inputs, dry-run, integrity checks, repeat installation, updates and conflict
resolution. It SHALL distinguish package-owned files, upstream-generated files,
native OpenSpec configuration, local executable workflow settings and product
specifications. Ordinary examples SHALL select an OpenSpec home without a
user-chosen registration name.

#### Scenario: SDW-D02 A consumer needs local process guidance

- **WHEN** a consumer needs to configure project checks or extend context
- **THEN** guidance points to `openspec/workflow.yaml` for executable settings and native OpenSpec configuration for context, rules and schema
- **AND** it does not recommend editing upstream-generated skills or package-managed policies in place
- **AND** active runs retain their original checkout/version instead of being silently migrated during update.

#### Scenario: SDW-D05 Understand native and SDW execution

- **WHEN** a developer chooses between native OpenSpec commands and SDW entrypoints
- **THEN** guidance states that independent reviews, accounting and final acceptance require SDW execution
- **AND** it describes the proposal, design, tasks and capability artifact layout that execution requires
- **AND** preserving a custom schema is not presented as support for arbitrary artifact layouts.

### Requirement: Explicit scope semantics and limits

Documentation SHALL distinguish process applicability, permitted changes,
dependency context, OpenSpec home and repository-level installation glue. It
SHALL explain whole-repository adoption, several folders in one logical project
and the need to resolve cross-project ambiguity before work.

#### Scenario: SDW-D03 Adopt only one component

- **WHEN** a developer follows the scoped adoption instructions
- **THEN** the example includes related tests and an explicitly selected specification home
- **AND** shared root integration is identified without granting blanket application write authority
- **AND** directory instructions are not presented as filesystem isolation.

### Requirement: Traceable extraction and honest verification

The repository SHALL record its source revision and distinguish retained core,
parameterized project behavior and source-only historical obligations. Guidance
SHALL identify supported profiles and verification limits without claiming
unperformed migration, remote publication or paid comparative model results.

#### Scenario: SDW-D04 Review the extraction result

- **WHEN** a reviewer inspects provenance and verification records
- **THEN** the source PR and commit are identifiable
- **AND** GitBob migration and historical runs are explicitly outside this delivery
- **AND** synthetic execution tests, actual CLI checks and unresolved limits are distinguished.
