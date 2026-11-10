# Complete one implementation change

Use this procedure through `sdw-run` for one authorized change. Follow the
[execution procedure](execute.md) for registry selection, dispatch, evidence,
coordination and recovery. The selected [plan](../policies/plans.md) supplies
attempt limits; this procedure does not introduce another set of caps.

## 1. Select and prepare

Confirm the problem, acceptance criteria, project, ticket, change and dependencies.
Read current contracts and relevant target instructions. Inspect the registered
queue, then claim the selected change and create or resume its owned worktree.
Prepare the declared environment. Preserve unrelated work and retain the base
revision, authority, scope and ownership in the intake and ledger.

## 2. Harden the contract

Apply [design hardening](harden-change.md) to new or changed implementation
contracts. Reconcile valid existing artifacts instead of rewriting them.
Establish observable scenarios, interfaces, failure cases and a test plan.
Do not begin dependent implementation while required design acceptance is
incomplete. Pure review and setup requests end within their authorized phase.

## 3. Implement bounded slices

The lead derives a compact scenario-to-task map from the accepted design.
Assign each writer exact exclusive source and test files, relevant contracts,
dependencies, checks and an output contract. Shared files have one owner at a
time. Keep assignments within the registered areas and task scope.

Integrate completed slices and run their relevant checks. Record actual behavior
and justified design decisions in the owning artifacts. Do not weaken a
requirement to excuse a failed implementation or skip an independent review
because a writer reports success.

## 4. Review and repair

Apply [implementation review](review-impl.md) to the integrated change. Both
lenses cover the full affected behavior, including shared interfaces and relevant
consumers. Adjudicate a nonempty findings batch and assign coherent repairs.
Reserve enough allowance for fresh independent review after every material fix.

Run checks required by project registration and changed behavior. Tests validate
implementation; source bundles and ledger checks validate evidence bindings.
Neither replaces the other. Broaden successful verification only when new
changes, failures or unresolved concerns justify it.

## 5. Finish artifacts and final acceptance

After implementation and verification, complete the same-change
[specification lifecycle](../policies/openspec.md). Check delivered tasks, sync
full requirement bodies, archive completed work and repair references. Capture
the resulting final artifacts and renew affected review acceptance, including
design evidence changed by archive relocation.

Bind all required checks and both review phases to the relevant final inputs.
Inspect the full diff, including deletions, modes, new files and shared metadata.
Report incomplete evidence or unresolved findings instead of claiming readiness.

## 6. Hand off within authority

Prepare a concise change summary linking the ticket and OpenSpec artifacts,
with checks, review coverage and limitations. Publish or merge only within the
applicable scope of authority and after the runtime gates pass. Preserve the
ledger and original evidence for handoff. Cleanup and the next task are separate
actions.
