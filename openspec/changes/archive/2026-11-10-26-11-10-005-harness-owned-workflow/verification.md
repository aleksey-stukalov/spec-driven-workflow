# Harness-owned layout verification

## Delivered scope

Canonical `sdw-run`, `sdw-harden` and `sdw-review` bodies are regular files in
`agentic_harness/skills/`. Selected agents discover them through exact relative
directory symlinks. Canonical contents and discovery links have separate ownership.

Schema-3 registrations preserve stable identifiers and OpenSpec homes. Consumer
settings live under `agentic_harness/config/`, with deterministic component paths,
and remain project-owned. Native OpenSpec configuration stays in its selected home.
`openspec/dependency-map.yaml` preserves the ordered `queue` document and its
dependency semantics. Updates migrate settings, maps and verified copied skills
together, preserving contents and permissions and detecting conflicting changes.

Typed source evidence retains discovery links as inert data and preserves removed
originals. Historical evidence and privacy rules keep their original meaning.
Upstream-generated OpenSpec integrations remain unchanged.

## Checks and independent review

The immutable implementation base is
`a0aa879731648159aba0bd517e49c95621077261`. The requested checkpoint is `467acf6`;
the final code repair is `287e211`. Original source bundles, complete reports,
commands and migration results are retained outside the source tree in Git's
common directory under
`agentic-harness/runs/26-11-10-005-harness-owned-workflow/`.

| Check | Result |
| --- | --- |
| Full suite on final implementation commit `287e211` | `uv run --locked pytest`: **1006 passed in 403.86 seconds**. |
| Final settings-diagnostic focused suites | **404 passed**; all eight original malformed-key probes passed, including sixteen real CLI invocations. |
| Generated handbook | `build.py --check` passed; maintained inputs and generated contents remain consistent. |
| Actual prior-installer upgrades | Root and component cases passed all **20 commands** after transaction repairs. |
| Additional fresh adoption matrix | Root with selected source/test folders and two independent component homes passed **23 commands**, including expected ambiguity rejection. |
| OpenSpec before lifecycle | The active change and five baseline capabilities passed strict validation. |
| OpenSpec after synchronization and archive | All five baseline capabilities and all five archived changes passed strict validation; document-link and handbook freshness checks passed. |

The actual upgrade fixtures were produced by the base installer. They preserved
settings/map bytes and `0640` modes, stable identifiers, consumer instructions,
specifications, unrelated skills/settings and twelve upstream-generated files per
case. Doctor, routing, declared checks and installed handbook freshness passed.
Dry-run retained the typed filesystem snapshot; repeated installation and update
were no-ops. Focused tests cover legacy inline and old package-directory variants,
transaction rollback, concurrent edits and rejected unsafe paths.

Both independent design lenses passed D1. I1 found six distinct defects; an
independent adjudicator confirmed them. They covered staging/rollback races,
dependency-map validation, live source correspondence, canonical-skill idempotency
and configuration diagnostics. Later rounds found additional malformed-settings
diagnostic branches. Original reports and failed probes were preserved; all
confirmed defects were repaired and independently verified closed in I4.

Both I4 lenses are complete and clean on retained revision
`5ea26be06d2f045ee2e6e4fc14a0ffdb8487c5a7a3c9c2bb2e1abe0ff45dbcae`.
The bundle contains 169 current inputs, eight deleted originals and six inert
discovery records. Reviewers checked exact live correspondence and preserved
complete original coverage for unchanged inputs. Subsequent lifecycle files
require their separately retained final snapshot and I5 reports; this narrative
does not substitute for those final acceptance records.

## Specification lifecycle

All 25 implementation tasks were marked complete only after I4 and the full
suite passed. Four capability baselines were synchronized: eleven requirements
modified, three added and one removed.
All modified and added requirement bodies match the approved deltas. Titles,
Purpose sections and twenty-two unaffected requirement blocks were preserved.
Strict validation of all five synchronized baseline capabilities passed.

The pinned OpenSpec 1.14.3 CLI archived the completed change as
`2026-11-10-26-11-10-005-harness-owned-workflow`. It used `--skip-specs` because
the agent had already synchronized and verified the baselines. Proposal, design
and delta bodies retain their accepted D1 bytes at the archive location. The
dependency-map entry and its prerequisite retain their stable identities.
Final archive/source correspondence and validation results are retained with the
separate final review records rather than rewriting the earlier snapshots.

## Evidence limits

Task 5.6's session accounting and review bindings are recorded in the retained
host `execution.json` and original reports. This authoring session used host
collaboration tools and did not issue a native-dispatch run acceptance receipt.
Local fixtures exercise dispatch, accounting and final acceptance, including
rejection when changed links or settings/map authority are omitted. They do not
prove live Codex/Claude account access, billing or fresh-session skill discovery.
Unknown provider usage remains unknown.

All consumer operations used temporary repositories. GitBob adoption and remote
publication remain outside this local layout delivery.
