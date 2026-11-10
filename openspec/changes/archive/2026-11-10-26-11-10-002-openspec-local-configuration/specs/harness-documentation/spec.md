## MODIFIED Requirements

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
