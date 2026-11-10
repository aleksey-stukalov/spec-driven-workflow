# Package directory rename verification

## Delivered scope

The current source and installed package use `agentic_harness/`. Runtime paths,
development commands, CI, SDW adapter generation, documentation and handbook
sources use that name. The 34 generated SDW integrations changed only their
package paths; upstream OpenSpec-generated files were not edited.

Legacy updates use verified file ownership and the existing transactional
installer. Unowned legacy files, caches and virtual environments stay at their
original paths, with the old ignore file retained when necessary. Stable IDs,
project-owned settings, native configuration and product specifications remain
unchanged. Explicit local commands or path bindings that need reconciliation
block the update before removal of their inputs.

Historical privacy authority is read from the immutable base's original package
path. Old review bundles retain their path identities and bytes. Current runtime
selection rejects legacy-only or ambiguous authority rather than silently
discarding exclusions. The Git coordination namespace is unchanged.

## Verification

| Check | Result |
| --- | --- |
| Adapter and Markdown link tests | 8 passed. |
| Real OpenSpec integration tests | 5 passed, including root/component installs, installed handbook rebuild and unchanged upstream generation. |
| Runtime evidence, registry and isolation tests | 166 passed. |
| Installer and directory migration tests | All 105 cases passed across the final focused runs, including permission preservation on success, rollback and concurrent changes. |
| Full local suite before permission follow-ups | 738 passed in 258.58 seconds; the final affected installer/migration cases passed afterward. The final suite contains 747 tests. |
| Handbook build and freshness | Passed with the new source paths. |
| Chrome rendering, light and dark | Passed at 1440 px and 390 px, with 21 nodes and 30 edges. |
| Pinned strict OpenSpec validation | Active change passed; after synchronization, all 5 baseline specifications and all 4 archived changes passed. |

## Published-version upgrade rehearsal

Two temporary Git repositories were installed with published revision
`93c144f428d591cecedbe70defebf58e7478a3d5`: one whole-repository installation and
one component home covering separate source/test directories. Both were updated
with the renamed distribution. All 31 recorded commands succeeded.

Dry-run retained all file hashes. Updates moved the owned runtime, index and
manifest, left no duplicate active authority, and preserved native configuration,
specifications, executable settings, stable IDs, upstream skills and unrelated
agent settings. Unowned notes, legacy caches and virtual environments retained
their bytes and ignore protection. Doctor, directory/ID selection, pinned
OpenSpec, handbook freshness and actual fixture product checks passed. Both
repeat installation and repeat update were no-ops.

## Independent review

Design review identified local settings that could retain references to removed
paths. The design and implementation now stop for explicit reconciliation.

The runtime/evidence reviewer found no substantive defect. An independent bundle
created by the pre-rename code verified standalone without byte changes and
failed comparison with the renamed live tree. Historical private originals were
still excluded; six focused acceptance tests also passed.

Installer review identified permission loss during successful migration and
rollback. The corrected plan preserves original file and directory modes before
publishing content, retains existing destination modes and detects concurrent
permission changes. Independent probes covered both registry formats, absent and
existing destinations, ordinary defaults for unmatched new files, rollback and
concurrent chmod. Eleven focused tests passed; no review blocker remained.

The five real OpenSpec integration tests were repeated successfully after the
final installer changes. The final diff and unchanged upstream integrations
were checked by the lead.

## Lifecycle

The canonical-location requirement and complete migration requirement were
synchronized into `harness-configuration`, preserving its existing Purpose and
unaffected requirements. The pinned CLI archived this change after synchronization.
The final bookkeeping task includes archiving itself and was marked complete
only after that operation succeeded. Strict archive validation then passed.

## Limits

All consumer operations used temporary fixtures; no live application or GitBob
was migrated. Unmanaged legacy leftovers are deliberately preserved, so an old
directory may remain after a consumer update. Archived records and original
GitBob provenance retain the historical spelling. No provider capability, model
quality or billing claims are inferred from these checks.
