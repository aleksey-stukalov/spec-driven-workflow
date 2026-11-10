## Why

The workflow delivered in GitBob PR 128 contains reusable development controls,
but its paths, environment setup and generated integrations assume that project.
A separate package must let an agent apply the process to an existing repository
or selected folders without replacing the project's own instructions or changing
OpenSpec-generated files.

## What Changes

- Extract the runtime, canonical policies, procedures and shipped plan profiles.
- Register one logical project over one or several code roots, with one explicit
  OpenSpec home and project-defined checks and environment inputs.
- Add repeatable installation, reviewed updates and a read-only integrity check.
- Keep OpenSpec 1.14.3 unchanged. Generate workflow skills and roles as `sdw-*`.
- Preserve existing target settings, product specifications and unrelated files.
- Record upstream provenance and the source-specific behavior left in GitBob.

## Capabilities

### New Capabilities

- `harness-configuration`: package ownership, portable project registration,
  pinned dependencies and safe adoption or updates.
- `harness-change-lifecycle`: bounded intake, queue selection, independent
  acceptance, truthful OpenSpec completion and authorized GitHub handoff.
- `harness-role-policy`: shared role/profile contracts, durable counters,
  resource preflight and original evidence.
- `harness-workspaces`: host-local claims, owned worktrees, declared environment
  inputs, retained source, recovery and protected cleanup.
- `harness-documentation`: agent-readable policy navigation, adoption guidance,
  scope semantics and explicit verification limits.

### Modified Capabilities

None. This repository has no implemented capability baseline yet.

## Impact

The change creates a local standalone development repository at
`/Users/Aleksey.Stukalov/Misc/spec-driven-workflow`. It includes runtime code,
installation tooling, agent adapters, package dependencies, documentation and
synthetic verification. Python and Node dependencies belong to the workflow,
not to the application adopting it.

GitBob migration, remote repository creation or publication, paid model
qualification and coordination across separate clones or machines are outside
this change. No existing GitBob run or application capability is modified.
