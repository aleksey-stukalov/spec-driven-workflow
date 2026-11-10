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

### Requirement: Generated offline visual handbook

The package SHALL provide an offline HTML handbook generated from maintained
Markdown, the validated plan catalog and a workflow graph. It SHALL preserve
the reusable visual design while describing current portable behavior. The page
SHALL use inline styling and SVG without requiring remote assets or scripts.

#### Scenario: SDW-D06 Read the process visually

- **WHEN** a developer opens the generated handbook offline
- **THEN** the process diagram shows required reviews, repair loops and authorized handoff
- **AND** profile tables reflect the current catalog rather than a second route table
- **AND** local links and section anchors resolve
- **AND** desktop and narrow layouts keep prose and diagram content accessible.

### Requirement: Deterministic presentation-only build

The handbook build SHALL generate only its declared presentation output and
SHALL NOT modify Markdown, native settings, agent adapters or runtime state.
Identical inputs SHALL produce identical bytes independently of checkout path.
A read-only check SHALL fail on stale or missing output. CI SHALL run that check.

#### Scenario: SDW-D07 Detect outdated HTML

- **WHEN** a maintained input changes without rebuilding the handbook
- **THEN** the check fails without changing files
- **AND** rebuilding updates the generated page from the current input
- **AND** a repeated build makes no further content changes
- **AND** invalid graph data or broken local references fail before publishing output.

### Requirement: Complete portable handbook payload

Installation SHALL include the handbook, generator and all required presentation
inputs under package ownership. Consumer specifications, configuration and
checks SHALL retain their ownership. Browser rendering checks SHALL NOT become
mandatory consumer product checks merely because the handbook is installed.

#### Scenario: SDW-D08 Rebuild an installed handbook

- **WHEN** a scoped consumer installation invokes the handbook builder
- **THEN** it succeeds using installed inputs and the workflow's dependencies
- **AND** the output remains identical to the distributed page
- **AND** unrelated instructions, native settings and product files are unchanged.
