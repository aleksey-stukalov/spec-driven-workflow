# Proposal

## Why

SDW skill bodies are duplicated in agent discovery directories, and executable
workflow settings are stored beside OpenSpec's native configuration even though
they belong to the harness. Consolidating these responsibilities makes ownership
clear while retaining the change dependency document with the specifications.

## What Changes

- Keep the three canonical SDW skills under
  `agentic_harness/skills/sdw-{run,harden,review}/SKILL.md`. Install relative
  directory symlinks in each selected provider's native discovery directory.
- **BREAKING layout change:** move project-owned executable settings to
  `agentic_harness/config/workflow.yaml` for the root OpenSpec home, or
  `agentic_harness/config/<home>/workflow.yaml` for a component home. Introduce
  index schema 3 without changing stable registration IDs, directory selection,
  setting fields, or Git-root-relative path semantics.
- **BREAKING layout change:** rename each home's `openspec/queue.yaml` to
  `openspec/dependency-map.yaml`. Preserve the ordered `queue` list, stable change
  IDs, dependencies, and read-only selection behavior; add no mutable status.
- Migrate verified existing installations transactionally, including old package
  directory and inline-registration formats. Preserve consumer settings and
  native OpenSpec content; reject collisions, unsafe aliases, and concurrent
  edits before overwriting local work.
- Extend ownership and retained-source evidence narrowly to account for the
  exact discovery links, their targets, and displaced or deleted originals.
  General symlink traversal remains forbidden.
- Update current guidance, generated handbook, package integration, and tests
  for fresh adoption and actual upgrades. Leave historical artifacts and runs
  under their recorded layout and evidence semantics.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `harness-configuration`: canonical skill ownership, typed link installation,
  harness-hosted consumer settings, schema-specific routing, and safe migration.
- `harness-workspaces`: exact link-leaf assignment and complete, non-traversing
  retained source for approved discovery links and displaced originals.
- `harness-change-lifecycle`: dependency-map naming with unchanged queue
  semantics, and final acceptance covering links and moved check authority.
- `harness-documentation`: current layout, ownership, migration, and discovery
  guidance for users and agents.

## Impact

Affected interfaces include the installer and adapter generator, project
registration and selection, intake/dispatch path validation, source capture and
verification, final acceptance, and the repository's own installed layout.
OpenSpec 1.14.3, its generated `openspec-*`/`opsx-*` output, native project
configuration, supported plan profiles, and external-action authority remain
unchanged. No application language or new consumer dependency is imposed.

The change follows `26-11-10-004-rename-agentic-harness`; its dependency-map entry
must retain that prerequisite. This delivery covers the three layout moves
together. GitBob adoption, changes to other live consumers, paid provider
experiments, remote publication, merge, and a general-purpose symlink facility
are outside this scope.
