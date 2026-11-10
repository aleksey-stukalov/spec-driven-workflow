# Spec Delta

## MODIFIED Requirements

### Requirement: Agent-readable canonical process guidance

The package SHALL provide a Markdown reading map to its canonical policies,
procedures, role contracts and plan catalog. Guidance SHALL cover intake,
project selection, worktrees, specification lifecycle, review, evidence, recovery
and authorized handoff without requiring HTML or private project data. Canonical
SDW skill links SHALL resolve both from harness storage and native discovery
paths without duplicated skill bodies.

#### Scenario: SDW-D01 A fresh agent starts a scoped change

- **WHEN** the agent reads the installed entrypoint for an applicable project
- **THEN** it can locate the required policies and phase procedure through explicit links
- **AND** the instructions distinguish required reads from automatic imports
- **AND** commands resolve from the worktree root and identify the selected project
- **AND** the skill's relative Markdown links work from both its canonical and discovery locations.

### Requirement: Reproducible adoption and upgrade instructions

Documentation SHALL explain required tooling, pinned versions, installation
inputs, dry-run, integrity checks, repeat installation, updates and conflict
resolution. It SHALL distinguish package files and discovery links from
upstream-generated files, native configuration, consumer-owned harness settings
and specifications with dependency maps. Ordinary examples SHALL select an
OpenSpec home without a user-chosen registration name.

#### Scenario: SDW-D02 A consumer needs local process guidance

- **WHEN** a consumer needs to configure project checks or extend context
- **THEN** guidance points to the selected `agentic_harness/config/` settings file for executable settings and native OpenSpec configuration for context, rules and schema
- **AND** it explains the root and component settings-path mapping and Git-root-relative semantics
- **AND** it does not recommend editing upstream-generated skills or package-managed policies in place
- **AND** active runs retain their original checkout/version instead of being silently migrated during update.

#### Scenario: SDW-D05 Understand native and SDW execution

- **WHEN** a developer chooses between native OpenSpec commands and SDW entrypoints
- **THEN** guidance states that independent reviews, accounting and final acceptance require SDW execution
- **AND** it describes the proposal, design, tasks and capability artifact layout that execution requires
- **AND** preserving a custom schema is not presented as support for arbitrary artifact layouts.

#### Scenario: SDW-D09 Upgrade an earlier workflow layout

- **WHEN** a developer follows current adoption or upgrade guidance
- **THEN** it explains canonical skills, relative discovery links, the settings move and `dependency-map.yaml` rename as one reviewed installation plan
- **AND** it describes conflicts, rollback, retained legacy content, unchanged ordered-queue behavior and explicit refresh after local settings changes
- **AND** it reports unsupported symlink creation without suggesting duplicated skill bodies as an automatic fallback
- **AND** documented provider support is distinguished from any actually performed live-session discovery check
- **AND** historical archives and evidence are not rewritten to appear to have used the new paths.
