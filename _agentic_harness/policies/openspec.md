# OpenSpec authority and completion

OpenSpec owns product change artifacts and capability specifications. This
package adds execution and acceptance rules around its pinned CLI. Read the
selected project's context and instructions before using a generated skill.

## Select one authority

The registered `root` is the project directory containing `openspec/`. It may be
the repository root or another directory; it is independent of `code_roots`.
Invoke the package wrapper with an explicit project when several are registered.
The wrapper runs the pinned CLI from the registered directory. A current working
directory or skill name alone does not establish the intended project.

Reuse an existing OpenSpec home through deliberate adoption. Do not initialize a
second home to evade an existing project's rules, history or unfinished work.
Never silently replace its config, schemas, specifications or change archive.
Preserve the existing `config.yaml` or `config.yml`; two config files are
ambiguous. This version requires non-overlapping registered project roots.

OpenSpec-generated skills remain managed by OpenSpec. Keep package behavior in
the `sdw-*` entry points and these policies. Editing generated skill bodies is
not a supported customization mechanism; an OpenSpec update may replace them.

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
