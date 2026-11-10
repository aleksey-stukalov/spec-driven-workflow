# Review one implementation

Use `sdw-review` for one selected implementation. Read the
[policy map](../policies/README.md) and [execution procedure](execute.md).
Review-only authority does not permit code fixes or new implementation.

## Paired independent review

Supply the immutable base, full changed-path inventory, relevant specification
and design sections, project checks, downstream boundaries and retained source.
Both reviewers use the same frozen inputs with distinct fresh identities.

- The behavior/test lens checks every affected capability and scenario,
  observable results, failure cases and test strength. For maintenance without
  capability deltas, it checks proposal acceptance and relevant tooling tests.
- The runtime/safety lens checks recovery, determinism, concurrency, idempotency,
  resource use, security, compatibility and affected consumers where relevant.

Reviewers remain read-only. Focused reproductions requiring commands run only
in separately assigned scratch space. Claim reproduction only when performed.
Return the required structured result with input revision, coverage disposition,
findings and a truthful truncation flag. Each finding identifies its location,
violated contract, concrete impact, severity, evidence and suggested correction.
Missing coverage or overflow makes the result incomplete, never clean.

## Findings and repairs

Group exact duplicates deterministically and retain every original. One
independent adjudicator reviews the complete nonempty batch, returning a verdict
and evidence for each finding ID. Do not launch an agent per finding. A serious
dispute remains blocking until evidence and a fresh independent round resolve it.

Within implementation authority, assign confirmed fixes to exact owned files.
Repair code, tests and affected design coherently before the next review.
Preserve authoritative requirements; a missing test is not a reason to weaken
the contract. Under review-only authority, return findings for an authorized
writer instead of modifying the checkout.

## Acceptance

Use the selected plan's shared `I` counter and clean minimum. Reserve subsequent
review capacity before fixes. Run relevant checks and capture the resulting
source. Final integration edits invalidate affected acceptance and require new
review; changing sessions cannot reset allowances.

Require complete original reports, full affected coverage, resolved defects,
required passing checks and clean review on the final relevant bytes. Retain
historical inputs separately. A narrow or partial review cannot be relabeled as
whole-change acceptance, and the end of a budget does not establish readiness.
