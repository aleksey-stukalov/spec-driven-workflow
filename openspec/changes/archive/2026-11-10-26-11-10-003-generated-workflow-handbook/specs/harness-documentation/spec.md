## ADDED Requirements

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
