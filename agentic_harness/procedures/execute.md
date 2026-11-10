# Execute one bounded run

Read the [policy map](../policies/README.md), [execution policy](../policies/execution.md),
[plan profiles](../policies/plans.md) and [role contract](../roles/runtime.md).
`sdw-run`, `sdw-harden` and `sdw-review` select the full pipeline, design phase or
implementation review. Their discovery does not grant additional authority.

Commands below run from the assigned repository or worktree root. `python`
means the interpreter prepared for the installed harness; it is not necessarily
the target application's interpreter. `SPEC_ROOT` is the repository-relative
directory containing the intended `openspec/`; use `.` for the root. JSON
filenames identify the requests you prepared. Later `harness.py` references abbreviate
`python agentic_harness/tools/harness.py`; use the full invocation when running them.

## Resolve inputs and ownership

1. Select the intended OpenSpec directory:

   ```sh
   python agentic_harness/tools/harness.py project --at SPEC_ROOT
   python agentic_harness/tools/harness.py openspec --at SPEC_ROOT -- list --json
   ```

   Read the returned specification home, source scope, queue, checks and
   environment policy. Read native context and rules in its `openspec/config.yaml`
   (or existing `config.yml`) and executable settings at the returned `workflow`
   path under `agentic_harness/config/`. Legacy schemas retain their recorded
   inline or OpenSpec-local settings until installer migration.
   Keep the returned `id` in all machine requests for this run. The internal index
   preserves stable identifiers; you do not need to invent or remember one.
   Read the selected change and applicable target instructions. The wrapper
   selects that OpenSpec directory and the pinned executable.

   Omit `--at` when the current directory identifies the intended adopted home,
   or when no local home is found and only one project is configured. A nearer
   unadopted home or ambiguity stops selection. When tests are outside the
   specification home, choose their owning home explicitly. Preserve the selected
   binding after intake; changing directories does not change an admitted run.

2. Record bounded intake and validate it with `harness.py intake INTAKE.json`.
   Preserve the current ticket observation outside the repository when
   implementation requires it. Record planning, review, implementation,
   publication, merge and cleanup authority separately. A remote action can be
   prepared locally without permission to publish it.

3. Inspect the queue through `coordination list` or `coordination next`, supplying
   the repository and request. Inspection does not claim work. A separate
   `coordination claim` binds project, change, immutable base, session and
   generation. Coordination state lives in Git's common directory and is shared
   by linked worktrees on this host, not other clones or machines.

4. Create or adopt an owned worktree with the coordination commands. Bind branch,
   base, allowed parent and environment ownership. Run the registered preparation
   commands and retain their original result. Fingerprint declared lockfiles;
   use explicit environment rebind after intentional lock changes. Missing
   dependency preparation or a dirty owned workspace requires reconciliation.

## Admit and dispatch assignments

5. Choose the run ID and retain its initial source through
   `harness.py source capture SOURCE.json`. Use a fresh destination outside the
   worktree and explicit nonignored source paths. Capture intended untracked
   files as well as committed and modified files; retain executable modes and
   declared deleted originals from the pinned base. Approved discovery links
   require their canonical `SKILL.md` explicitly in scope. Schema-4 bundles store
   literal link text as inert regular files, with original type `120000` in the
   manifest; tell reviewers where the canonical skill content lives. Include
   old child-file deletions displaced by a new directory link. Unsupported
   same-leaf regular/link transitions fail explicitly. Honor project exclusions
   and reject unsafe or secret paths. Verify the resulting bundle before use;
   its `input_revision` is the ledger's initial source revision.

6. Initialize an external ledger using
   `harness.py plans --db RUN.sqlite init --request RUN.json`. Pin that verified
   input revision, plan, project, change, applicable stages, implementation
   slices, scope authority, context capacity and spend envelope. Preserve this
   ledger on resume. Inspect `plans routes` and run `plans preflight` with actual
   client/account evidence before launching workers. CLI help alone does not
   demonstrate account access or effective context capacity.

7. Prepare a dispatch request binding intake, ledger, run ID, worktree, bundle,
   fresh evidence directory, assignment kind, admission, original prompt files,
   checks and coordination ownership. Capture each assignment's current source
   and reconcile changed inputs before admission; the request's input revision
   must match its verified bundle. Writers receive exact exclusive paths.
   Freeze the workspace before read-only assignments or a paired review round.
   Dispatch through `harness.py dispatch --request ASSIGNMENT.json`; it reserves
   capacity and records attempts before native launch.

8. Retain original requests, prompts, native stdout/stderr, structured results
   and available usage. Read-only reviewers use retained source. Reproductions
   requiring commands are separate permitted scratch checks, retained with
   their results. Do not equate transport completion with successful review.

## Reconcile, accept and hand off

9. After edits, reconcile the ledger against verified source manifests and the
   relevant design and implementation revisions. Preserve unaffected original
   evidence; reset affected clean rounds when inputs change. Handle findings
   through the relevant [design](harden-change.md) or
   [implementation review](review-impl.md) procedure. Record any needed resource
   extension before exceeding a limit.

10. Run required checks against the final source and complete the
    [OpenSpec lifecycle](../policies/openspec.md). Final coverage includes changed,
    new and deleted paths, synchronized capability bodies, archived change
    artifacts, queue, native configuration, internal index and the selected
    harness settings file containing check authority, dependency map, approved
    discovery links and their canonical skill inputs. Archive relocation needs
    a newly bound design snapshot and affected independent acceptance. Confirm full review
    originals and final-source correspondence before claiming readiness.

11. Use `harness.py remote prepare`, `grant`, `execute` and `reconcile` for the
    supported GitHub operations, with their JSON requests. Retain operation
    identity and receipts. A lost response remains unknown until reconciled
    against GitHub; do not blindly repeat the mutation. Publication and merge
    require their own applicable authority. Merge also checks the current head.

12. Return the bounded outcome, evidence, remaining limitations and next action.
    Handoff never starts another queued task. Cleanup first inventories dirty
    files, active assignments, environment dependencies and evidence pins.
    Apply only an authorized inventory after rechecking protections, using
    normal non-forced worktree removal. Branch deletion is a separate action.

## Interrupted work

Save a checkpoint containing ownership, revisions, decisions, unresolved
findings, checks, originals and the next action. Reconcile all attempted writer
edits before resume. Do not repeat completed commits, archival operations or
external actions merely because the session restarted.

For uncertain dispatch, use
`harness.py dispatch --recover --request RECOVERY.json` only with evidence of the
original result and stopped-process outcome. Retain the uncertain receipt as
history. Settle existing reservations and usage once; missing billing is not
zero billing. If originals remain unavailable, report the attempt incomplete.

## Request contracts

The runtime rejects unknown or missing fields. Build requests from the installed
version's public contracts below, then use its CLI validation. Do not copy a
historical request, fabricate an observation or guess a field to bypass a gate.
JSON paths and evidence references must identify the actual assigned workspace
and retained originals.

| Request | Defining contract |
| --- | --- |
| Intake and ticket observation | `validate_intake` and ticket validation in [intake.py](../tools/intake.py) |
| Initial ledger, preflight, rounds, extensions and checkpoints | `Ledger.init`, `preflight` and the corresponding public `Ledger` method in [plan_runtime.py](../tools/plan_runtime.py) |
| Project, claim, workspace, environment and cleanup | CLI action mapping and corresponding public function in [coordination.py](../tools/coordination.py) |
| Source capture and verification | `materialize` and `verify` in [evidence.py](../tools/evidence.py) |
| Assignment and interrupted launch | `execute` and `recover` in [dispatch.py](../tools/dispatch.py) |
| Remote operations and final acceptance | `Journal` methods and `acceptance_gate` in [lifecycle.py](../tools/lifecycle.py) |

The [CLI entrypoint](../tools/harness.py) shows how each JSON request reaches its
contract. These explicit tools require an agent or operator to assemble the
bounded run; there is no unattended queue runner.
