# Verification

The portable extraction was verified locally on 10 November 2026.

## Automated checks

`uv run --locked pytest -q` completed with **534 passed** on the final runtime,
installer and adapter implementation. The run included the complete extracted
runtime suites, malformed-result and cleanup regressions, installation/update
fixtures and real OpenSpec 1.14.3 integration tests.

Pinned OpenSpec strict validation passed before archival. The original source
skills and this distribution's upstream-owned files were compared byte-for-byte
with pristine output from the published pinned package. Native adapter generation
uses the canonical validated plan catalog. Six namespaced skills passed the
skill-creator structural validator.

## Independent checks

Independent reviewers checked all five capability contracts against the final
implementation and tests. Reproduced defects in manifest ownership, concurrent
installation edits, scope/metadata overlap, malformed worker results and
cross-worktree evidence retention were fixed and independently rechecked.

A separate fresh-session rehearsal followed BOOTSTRAP.md in a temporary Git
repository. It installed for apps/api and tests/api, preserved apps/web, native
agent preferences, unrelated skills and existing instruction prose, resolved the
correct pinned OpenSpec root and ran a Node application check. Repeated
installation produced no changes. All installed guidance links resolved.

## Verification limits

Native-provider and GitHub transports in runtime tests are synthetic. No live
model-quality, account-capability, billing or GitHub publication claim follows
from these checks. The rehearsal verifies adoption and routing, not a paid
end-to-end agent run. Folder scope is not an operating-system sandbox, and
coordination is local to one clone's shared Git directory. Known active-worktree
protection does not discover arbitrary external ledgers.

GitBob was not migrated. The repository has not been published remotely.

After archival, strict OpenSpec validation passed for all five main specs. The
full requirement bodies match their archived deltas, all 16 tasks are complete,
and the final link and adapter checks passed (7 tests).
