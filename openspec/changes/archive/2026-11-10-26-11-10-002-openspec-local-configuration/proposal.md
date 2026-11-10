# Why

Adoption currently requires a name for a registry entry before the user can use
OpenSpec. The name describes no application behavior and duplicates a location
the user already chose. Project checks and scope also live away from the
specifications they govern. The user asked to bring the whole configuration
closer to native OpenSpec, while preserving the complete execution workflow.

# What Changes

- Keep native OpenSpec configuration responsible for schema, context and rules.
- Store executable workflow settings in a project-owned `openspec/workflow.yaml`.
- Select a workflow by its OpenSpec directory, without a required invented name.
- Retain stable internal IDs and accept old commands for existing runs.
- Migrate legacy inline configuration through the reviewable installer plan.
- Include the new check and privacy authority in retained-source verification.

# Capabilities

## Modified Capabilities

- `harness-configuration`: local settings, directory selection and safe migration.
- `harness-documentation`: native configuration and execution responsibilities.

# Impact

Installer, runtime configuration loading, command routing, evidence capture,
acceptance authority, generated SDW integrations and adoption documentation.
The source repository adopts the new settings format as a working example.

OpenSpec-generated files, review/accounting/recovery mechanisms, existing run
identities and GitBob remain outside the implementation scope. Native external
stores and overlapping or nested independent workflow roots remain unsupported.
