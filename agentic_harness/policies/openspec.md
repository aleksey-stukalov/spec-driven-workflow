# OpenSpec authority and completion

OpenSpec owns product change artifacts and capability specifications. This
package adds execution and acceptance rules around its pinned CLI. Read the
selected project's context and instructions before using a generated skill.

## Select one authority

Choose the directory containing the intended `openspec/`. From the Git worktree
root, use `harness.py project --at PATH`, where `PATH` is repository-relative and
`.` selects the root. The source and test areas in `openspec/workflow.yaml` may
be outside this directory.

Without a selector, the wrapper finds the nearest adopted OpenSpec home from
the current directory. If no local home is found, it can select the sole
configured project. A nearer unadopted OpenSpec home or an ambiguous choice
stops selection. Review the returned home and source scope against the request.
The wrapper runs the pinned CLI from that home. Preserve its returned internal
`id` in the run's requests and evidence, even if the working directory changes.

Reuse an existing OpenSpec home through deliberate adoption. Do not initialize a
second home to evade an existing project's rules, history or unfinished work.
Never silently replace its config, schemas, specifications or change archive.
Preserve the existing `config.yaml` or `config.yml`; two config files are
ambiguous. This version requires non-overlapping registered project roots.

Use native configuration for schema selection, context, artifact rules and
supported operation guidance. Use the adjacent `workflow.yaml` for this
package's executable checks, source scope, preparation commands, lockfiles and
evidence exclusions. The installer maintains the internal index; these settings
have one project-owned source beside OpenSpec after migration.

OpenSpec-generated skills remain managed by OpenSpec. Keep package behavior in
the `sdw-*` entry points and these policies. Editing generated skill bodies is
not a supported customization mechanism; an OpenSpec update may replace them.
Native `/opsx` operations do not automatically invoke this package's independent
review or final acceptance. Use the `sdw-*` entrypoints for those procedures.

## Artifacts and evidence

A proposal states the problem, scope, capabilities and dependencies. Delta
specifications define observable behavior and scenarios. A design records
interfaces, tradeoffs, failure behavior and verification. Tasks identify bounded
implementation slices and their checks. Their existence demonstrates planning,
not delivery.

Keep `openspec/specs/` truthful about implemented and verified behavior. Use
added requirements for new capabilities and modified or removed requirements
only against an existing baseline. Do not promote proposed behavior early.
Follow the pinned OpenSpec schema instead of inventing structural headings.

The built-in `spec-driven` schema already provides the artifacts this runtime
uses. Existing custom schemas are preserved, but the runtime requires
`proposal.md`, `design.md`, `tasks.md` and capability deltas at
`specs/<capability>/spec.md` within each change. A schema with different outputs
needs a deliberate compatibility change before this runtime can execute it.
Adding a review document to a schema does not establish reviewer independence
or acceptance of the final source; those checks belong to the runtime.

For maintenance without capability changes, use the supported `skip_specs: true`
change metadata and explicit acceptance tasks. Do not fabricate a product
capability merely to satisfy lifecycle checks or use this mode to avoid a real
behavioral delta.

## Synchronization and archive

Archive only completed and verified work. Check that synchronized requirement
bodies match the approved deltas, including renames and removals. Matching
headings or checked task boxes alone are insufficient.

Archive relocation changes review inputs. Retain the original evidence and bind
new snapshots to affected final artifacts before acceptance. Fix relative links
and references in the same change. Preserve stopped work and historical archives.

Run strict validation of the selected project after synchronization. Successful
OpenSpec validation checks artifact structure; implementation tests, independent
review and the final-source gate remain separate requirements.
