# Extraction boundary

This package extracts the reusable development workflow delivered in
[GitBob PR #128](https://github.com/ignatov/gitbob/pull/128). Its source snapshot is
[`8a21c9da8e38a55079df81db00200de018375e01`](https://github.com/ignatov/gitbob/tree/8a21c9da8e38a55079df81db00200de018375e01).
The extraction creates a separate workflow package. It does not migrate GitBob,
change an existing run, or certify another project merely by copying files.

## Component map

Paths in the source column are relative to that GitBob snapshot. Destination
paths are relative to this repository. The map separates reusable behavior from
the project binding required when a repository adopts it.

| Source component | Destination and extraction boundary |
| --- | --- |
| `_agentic_harness/plans.yaml` | `_agentic_harness/plans.yaml` retains the `plans-v1` role routes, context profiles, review gates, and attempt limits. `budget`, `balanced`, and `smart` are selectable profiles. They do not replace the host's global model settings. |
| `_agentic_harness/policies/` | `_agentic_harness/policies/` holds shared development, execution, and OpenSpec rules. GitBob repository and importer rules are removed from the reusable policy. |
| `_agentic_harness/procedures/` | `_agentic_harness/procedures/` describes the current pipeline, design hardening, implementation review, and execution. Historical native workflow scripts and their fixed call caps are not prerequisites for a new run. |
| `_agentic_harness/roles/runtime.md` | `_agentic_harness/roles/runtime.md` defines the common assignment contract. Roles receive their scope, route, and allowance from the selected run. |
| `_agentic_harness/tools/harness.py`, `intake.py`, `projects.py` | `_agentic_harness/tools/` contains the entrypoint, authority intake, and project resolution. The importer name and fixed source directory become explicit project bindings. |
| `_agentic_harness/tools/plan_runtime.py`, `dispatch.py` | `_agentic_harness/tools/` retains durable attempt accounting, route preflight, independent review rounds, and dispatch. New projects supply their checks and available provider capabilities. |
| `_agentic_harness/tools/coordination.py` | `_agentic_harness/tools/` retains queue validation, claims, file assignments, worktree ownership, freezes, and protected cleanup. Repository coordination remains separate from the selected development scope. |
| `_agentic_harness/tools/evidence.py`, `lifecycle.py` | `_agentic_harness/tools/` retains source bundles, original-result bindings, completion checks, and GitHub operation reconciliation. Application-specific paths and dependency assumptions belong in project configuration. |
| Root and importer `run-pipeline`, `harden-change`, and `review-impl` skills | Package-owned `sdw-run`, `sdw-harden`, and `sdw-review` entrypoints select a project and read the shared policies and procedures. The new names avoid taking ownership of existing skills with the old names. |
| `_agentic_harness/projects.yaml` and importer OpenSpec configuration | Each adopted OpenSpec home supplies native context and local `openspec/workflow.yaml` settings for source scope, checks and environment. An internal index preserves execution identities. [Scope and project binding](scope.md) defines the boundary. The GitBob importer settings are not package defaults. |
| `_agentic_harness/package.json` and lockfile | The package retains a local, pinned OpenSpec toolchain. The extraction baseline is `@fission-ai/openspec` version `1.14.3`, requiring Node.js `>=20.19.0`; a tool upgrade is a separate reviewed change. |
| Harness specifications under `src/gitbob_new_import/openspec/specs/` | Requirements for the reusable workflow belong to this package's specification project. An adopted repository's specifications describe its own product behavior and local integration. |
| Harness tests and synthetic native transports | Portable regression coverage belongs to the package. Adoption tests must also cover existing files, partial scope, and repeated installation. Passing synthetic checks does not establish paid model quality or provider equivalence. |

The [policy map](../_agentic_harness/policies/README.md) is the entrypoint for
shared instructions. The [execution procedure](../_agentic_harness/procedures/execute.md)
describes current runtime use. This inventory explains origin and ownership; it
does not define a second set of execution rules.

## Project-specific material excluded

An adopting project must provide its own product context and verification. The
package does not carry the following GitBob content into another repository:

- The engineering-activity analytics purpose, importer data model, source
  systems, identity rules, metric meanings, and HR-data handling contracts.
- Import CLI commands, DuckDB storage rules, source loading order, publication
  contracts, operational databases, private inputs, and live-import procedures.
- `src/gitbob_new_import` as a fixed project root, `ignatov/gitbob` as a tracker
  destination, and GitBob-specific test or environment preparation commands.
- Existing importer capability specifications, numbered acceptance criteria,
  implementation queue entries, archived product changes, and incident history.
- Application source-fingerprint and wheel/sdist packaging exceptions. Each
  project must decide how development tooling affects its own build artifacts.
- Whole-file ownership of existing agent settings. Adoption must preserve
  unrelated configuration and make shared integration changes explicit.

Generated `openspec-*` skills remain owned by the pinned OpenSpec generator.
Package-specific routing and rules live in the `sdw-*` entrypoints, project
configuration, and shared policy documents. Regenerating upstream skills must
not require manually reconstructing package changes inside their bodies.

The GitBob HTML/SVG handbook and browser-rendering requirements are presentation
assets of the source project. They are not required checks for every product
change in an adopted repository. Package verification and the consumer's product
checks have separate owners.

## Generated OpenSpec skill audit

A source audit compared all twelve nested `openspec-*/SKILL.md` files with clean
npm OpenSpec `1.14.3` output using profile `core`, delivery `skills`, and tools
`codex,claude`. The files match byte for byte: six workflows for each provider,
covering propose, explore, apply, update, sync, and archive. The source
[Codex skills](https://github.com/ignatov/gitbob/tree/8a21c9da8e38a55079df81db00200de018375e01/src/gitbob_new_import/.agents/skills)
and [Claude skills](https://github.com/ignatov/gitbob/tree/8a21c9da8e38a55079df81db00200de018375e01/src/gitbob_new_import/.claude/skills)
therefore need no cleanup of custom instructions. OpenSpec identifies the
`.agents` output as its `codex` integration. No upstream command files are tracked
in the audited source.

The twelve repository-root `openspec-*` skills are custom routing wrappers.
For example, the root
[propose wrapper](https://github.com/ignatov/gitbob/blob/8a21c9da8e38a55079df81db00200de018375e01/.agents/skills/openspec-propose/SKILL.md)
says the nested skill invokes `npm run --silent openspec -- ...`, but the pristine
[generated body](https://github.com/ignatov/gitbob/blob/8a21c9da8e38a55079df81db00200de018375e01/src/gitbob_new_import/.agents/skills/openspec-propose/SKILL.md)
invokes bare `openspec`. The package preserves generated bytes and provides
project selection and pinned command routing through its separate integration.
The harness wrapper sets the selected working directory and invokes the pinned CLI.
The package must not transplant those custom root
wrappers into the upstream namespace. This finding verifies the source boundary;
it is not evidence that the new installer has been tested.

## Historical state stays in GitBob

Historical `budget-v1` runs keep their original checkouts, environments, native
phase scripts, role mappings, evidence validators, and recorded limits. This
package does not relabel those runs as `plans-v1` or reinterpret their results.
The legacy `harden-change-v3.js` and `review-impl-v2.js` routes are not installed
as dependencies of the extracted workflow.

GitBob's queues, archives, claims, stopped worktrees, external ledgers, retained
source bundles, and original worker results remain where they are. Extracting
the package grants no authority to clean up that state or resume its work.
A later GitBob adoption needs its own migration scope and verification.

New package runs also pin their workflow version and evidence interpretation.
Updating installed files does not authorize rewriting an active run's ledger or
discarding the source and results required to verify it.

## Ownership after adoption

This repository owns the reusable process, runtime, schemas, and shipped
profiles. The target repository owns its local binding, product specifications,
project checks, and declared exceptions. Installation must identify conflicts
with existing project rules before claiming that adoption is complete.

A local copy of a selected package revision is a reproducible installation of
the upstream rules. It is not permission to follow a moving upstream branch or
overwrite local decisions on every run. Updates must expose changes to managed
files and preserve user-owned content.

Adoption is verified through behavior: a fresh session resolves the intended
scope, follows the selected process, and preserves unrelated files. The presence
of an `openspec/` directory, a valid catalog, or a completed task checklist alone
does not prove that result.
