# Verification

## Delivered behavior

- New installations need no registration name. A selected OpenSpec directory
  supplies native context and rules, plus local executable `workflow.yaml`
  settings for SDW.
- Legacy IDs and commands remain valid. Migration preserves effective settings
  and creates a compact index with no second writable copy of those settings.
- Directory selection, nearest-home discovery and ambiguity handling retain
  explicit scope. External-store selectors cannot override local routing.
- Companion settings participate in final review authority and historical
  privacy checks. Review accounting, recovery and assignment contracts remain.

## Independent review

Behavior review checked the two README installation examples through the actual
CLI, their dry-run immutability, settings reuse, generated instructions and
native ownership. Runtime review checked nearest-root semantics, ID selection,
aliases and argument forwarding. Safety review checked migration, initial
readsets, rollback, stable identity, historical exclusions and final authority.

Two concrete findings were resolved:

- Native store selectors could override the wrapper's chosen directory. The
  wrapper now rejects them and native store pointers before execution.
- An unchanged legacy configuration with omitted optional defaults could fail
  `doctor` because old manifests hashed the unexpanded document. The diagnostic
  now recognizes that exact recorded v1 authority; v2 still requires the expanded
  settings digest. Changed legacy checks continue to fail.

Focused verification passed: 133 runtime/routing tests, 68 evidence/acceptance
tests, the installer suite, adapter/link tests and five focused legacy-diagnostic
checks. A folder-install no-op check initially ran across a concurrent runtime
edit; its isolated rerun passed after the files were frozen.

## Published-version upgrade rehearsal

A temporary Git consumer was installed with the published source at
`308902a61efc2a1547b3a48871605cf48d762c50`, using the actual pinned toolchain.
It adopted `services/api` and `tests/api` with the internal ID `legacy-api`.
The new installer then previewed and applied the upgrade.

Eleven commands succeeded. The rehearsal verified:

- The dry-run left every consumer file unchanged.
- The stable ID, source scopes, checks and lockfiles were preserved.
- Native `config.yml` spelling, comments and bytes were preserved, along with
  upstream skills, local agent settings and unrelated files.
- `doctor`, sole selection, `--at services/api`, selection from a descendant
  directory and the old ID all resolved the same configuration.
- Pinned OpenSpec resolved the component home and the fixture's application
  check passed.
- Repeating installation without a name or repeated settings produced no edits.

The development repository also adopted the format. A comparison against the
published configuration confirmed identical identity, scope, commands,
environment and evidence exclusions.

## Full verification

- `uv run --locked pytest -q`: **650 passed** on the final implementation.
- Pinned OpenSpec strict validation: the active change and five baseline
  specifications passed before synchronization.
- After synchronization, all five baseline specifications and both archived
  changes passed strict validation. All ten tasks are complete; no active change
  remains. The archival bookkeeping task was checked after archive succeeded.
- The eight adapter/document-link checks passed again after archival.
- `git diff --check`: passed.

## Limits

This verifies configuration, routing, migration and the retained runtime
contracts. Native-provider execution, model quality, account capabilities and
billing were not exercised. External stores, arbitrary custom artifact layouts,
nested independent workflow roots and GitBob migration remain outside this
change. Native generated OpenSpec files and the role catalog were unchanged.
