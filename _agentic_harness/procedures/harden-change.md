# Harden one design

Use `sdw-harden` for one selected OpenSpec change. Read the
[policy map](../policies/README.md), [OpenSpec policy](../policies/openspec.md)
and [execution procedure](execute.md). This phase prepares and independently
reviews a contract; it does not authorize implementation.

1. A combined context assignment reads the relevant current and prerequisite
   contracts, source interfaces and downstream expectations. It returns a
   bounded brief and scenario-to-test map. Report missing evidence or uncovered
   scope; do not survey every unrelated change or archive.

2. One author writes or reconciles the proposal, delta specifications, design
   and tasks within assigned artifact paths. Specify concrete behavior,
   interfaces, failures, migration and tests where applicable. Preserve valid
   existing decisions and run strict OpenSpec validation. Retain the resulting
   source for independent review.

3. Dispatch a paired design round against the same frozen inputs. The contract
   lens checks every scenario, acceptance criterion, interface and verification
   plan. The feasibility/risk lens checks determinism, recovery, concurrency,
   resource bounds, security and affected consumers where relevant. Reviewers
   use fresh identities and return complete coverage and concrete findings.

4. Group exact duplicates deterministically while preserving original findings
   and IDs. For a nonempty batch, one independent adjudicator verifies each ID
   against cited evidence. A rejected major or blocker finding remains a
   dispute until evidence and independent acceptance resolve it. A vote or
   absence of reproduction does not waive a real defect.

5. One assigned author/fixer resolves the confirmed batch and checks coherence
   in the same interval. Record each assigned finding as resolved or unresolved,
   validate the artifacts and retain the new inputs. Obtain fresh independent
   review under the selected plan; earlier reviews of changed content do not
   satisfy acceptance.

Use the plan's shared `D` counter, clean-round minimum and repair allowances.
Do not impose historical source-workflow call caps. Before a repair, retain
enough later review capacity or obtain the required bounded extension.

Incomplete reports, missing originals, uncovered scope, unresolved serious
disputes or exhausted allowances leave this phase incomplete. Acceptance needs
full coverage, required checks and the selected clean minimum on unchanged
accepted inputs. Retain the complete originals outside the worktree.
