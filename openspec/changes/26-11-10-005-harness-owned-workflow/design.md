# Design

## Context

See [proposal.md](proposal.md) for the motivation and bounded scope. The current
installer generates identical SDW skill copies through `tools/adapters.py`.
`tools/workflow.py` records regular-file digests, rejects symlink path components,
and rolls back file writes and removals. Its existing `CLAUDE.md` to `AGENTS.md`
exception preserves that link; it does not install arbitrary links.

The runtime reads schema-2 `projects.yaml` entries containing stable ID/root
pairs, expands each home's `openspec/workflow.yaml`, and derives `queue.yaml`.
Schema 1 stores settings inline. The earlier package-directory migration also
supports `_agentic_harness` installation manifests and historical privacy rules.
`projects.relative_path`, intake, dispatch and retained-source capture reject
aliases. Source bundles use schema 3 for regular bytes, executable modes and
deleted originals; verification also supports historical schema 2.

These are intentional safety boundaries. This change introduces a bounded link
object and a new current configuration layout; it does not turn path resolution
into a general alias-following mechanism. Existing context and baseline specs
describe the delivered old layout; this change's deltas explicitly replace that
contract, and implementation updates current guidance in the same change.

## Goals / Non-Goals

**Goals:** keep one maintained body for each SDW skill; make setting authority
deterministic from an OpenSpec home; retain consumer ownership; preserve ordered
dependency semantics; support complete migration and review of changed path
types with original evidence intact.

**Non-Goals:** alternate configurable settings locations, renaming stable IDs,
changing setting fields or plan routes, general alias traversal, concurrent live
runtime migration, distributed locking, Windows support expansion, or replacing
provider discovery with a custom loader. Provider models and live sessions are
unchanged. No implementation outcome is established by these planning artifacts.

## Decisions

### 1. Canonical skills are regular payload; discovery entries are links

Maintain these three regular files as the source of truth:

```text
agentic_harness/skills/sdw-run/SKILL.md
agentic_harness/skills/sdw-harden/SKILL.md
agentic_harness/skills/sdw-review/SKILL.md
```

For each selected provider, create the directory link
`.agents/skills/<name>` or `.claude/skills/<name>` with literal target
`../../agentic_harness/skills/<name>`. Selection remains the union of providers
needed by registered homes. All three canonical skills are shared package
payload; an unselected provider receives no new discovery links. Generated role
adapters stay provider-specific regular files derived from the unchanged catalog.

Remove duplicate skill-body rendering from `tools/adapters.py`; its outputs
describe regular role files and a separate explicit link plan. Add `skills` to
the payload directory allowlist, but never `config`. The payload scanner still
rejects every symlink inside distributed payload trees. Checked-in discovery
links live outside those trees. Do not copy provider discovery trees into the
payload or infer allowed links from arbitrary source symlinks.

Keep skill Markdown links in the form
`../../../agentic_harness/policies/README.md` and corresponding procedure paths.
Both canonical and discovery skill locations have three directory components
above the file; these links work when a reader uses either lexical location.
The shorter canonical-only `../../policies/...` form breaks discovery-relative
resolution. Update skill prose to identify the harness settings returned for
the selected home. Upstream `openspec-*` and `opsx-*` output remains untouched.

A small standard-library helper, proposed as
`agentic_harness/tools/skill_links.py`, owns the finite provider/name/target
mapping and lexical validation. Installer and runtime reuse it. It distinguishes
an allowed leaf path from an existing approved link and validates the literal
target, real ancestors, real canonical directory and regular `SKILL.md` without
following aliases. It does not import mutable project settings or add a general
`follow_symlinks` option to `relative_path`. The source repository can capture
its own approved links without an installed manifest; installer ownership still
requires its manifest, and assignment authority still requires intake and scope.

Freeze these helper contracts before the dependent slices start:

- `discovery_links(agents)` returns a new sorted mapping of the selected exact
  discovery leaf paths to literal relative targets; unknown providers fail.
- `expected_target(relative)` returns the allowlisted literal target or raises
  `ValueError`; it performs no filesystem access.
- `canonical_skill(relative)` returns the corresponding canonical repository-
  relative `SKILL.md` path or raises `ValueError`.
- `validate_link(root, relative)` checks the actual leaf and real ancestors,
  exact target and canonical skill, then returns
  `{"kind": "directory_symlink", "target": expected_target(relative)}`.
  It does not resolve or return a target path as the caller's ownership identity.

Missing-leaf assignment planning uses lexical `expected_target` plus the
ordinary no-alias parent checks; `validate_link` is for existing links, not
permission to create arbitrary ancestors. Transactional mutation safety remains
the installer's responsibility. Runtime owns this module; installer imports
these interfaces rather than copying the allowlist.

Provider documentation explicitly supports symlinked skill directories:
[Codex](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)
and [Claude](https://code.claude.com/docs/en/skills#choose-where-skills-load).
Filesystem, parsed frontmatter and link-resolution tests are reproducible
acceptance evidence; these references do not claim a live agent session was
tested. A filesystem unable to create/preserve required links fails and rolls
back, with no silent copy fallback.

Alternative considered: tiny forwarding `SKILL.md` files avoid symlinks but keep
multiple instruction entrypoints and rely on another import step. The approved
directory-link approach gives both providers the canonical body directly.

### 2. Schema 3 selects deterministic harness settings and dependency maps

Keep the index shape and stable identities, changing only `schema_version` to 3:

```yaml
schema_version: 3
projects:
  api:
    root: services/api
```

Use this pure lexical mapping from a validated OpenSpec home:

| Home | Settings path | Dependency map |
| --- | --- | --- |
| `.` | `agentic_harness/config/workflow.yaml` | `openspec/dependency-map.yaml` |
| `services/api` | `agentic_harness/config/services/api/workflow.yaml` | `services/api/openspec/dependency-map.yaml` |

The settings document keeps schema version 1 and its existing fields. Paths,
checks and preparation commands remain relative to the Git worktree root,
including when settings are several directories below it. Native
`config.yaml`/`config.yml`, custom schemas, context and artifact rules stay in
the selected OpenSpec home. Existing native filename preservation and ambiguity
checks apply unchanged.

The mapping avoids a required registration name, directory slug or second map
of paths. It is injective for permitted non-nested homes. A hypothetical
`workflow.yaml` component would collide with the root settings slot only if
the root home were also registered; existing non-nested-home rules already
forbid that combination. Canonical path validation also rejects aliases and
traversal. New settings paths participate in cross-project scope-overlap checks,
so another project's code scope cannot absorb a neighbor's settings authority.

`projects.configuration_paths` includes the index and selected harness file.
`editable_areas` adds that exact file, not its containing directory or all of
`agentic_harness`; explicit intake authority remains necessary. The existing
code roots and selected OpenSpec metadata remain eligible as before. Directory
selection, nearest-home errors, sole-project fallback and old ID selectors keep
their behavior. Project inspection reports the selected settings path so callers
and generated guidance need not duplicate layout inference.

Normal readers choose authority by the index schema, not by whichever file
exists. Schemas 1 and 2 retain their old inline/companion and queue meanings;
schema 3 requires the new settings and dependency-map paths. A missing required
file is an error. Presence of both legacy and new settings or map files is an
ambiguity error, even if equivalent. Preserve the existing schema-1 rule that
an optional legacy companion must agree with inline settings; a new harness
file alongside either legacy format requires explicit migration. The current
runtime continues to reject a live `_agentic_harness` installation until the
installer moves it; historical and installer readers understand that old root.

Alternatives considered: use IDs as settings filenames, or add explicit settings
paths to the index. Both create extra user-facing naming or mutable routing
state without benefit for the supported one-home/one-settings model.

### 3. Rename the dependency document, not its behavior

The new path remains beside `changes/`, preserving the existing derivation of
the change directory from the map's parent. Retain the YAML `queue` key, list
order, `change` and `depends_on` entry fields, complete stable IDs, and earlier-
entry prerequisite validation. Preserve archived entries. Internal `queue`
properties and `coordination list/next/claim` command interfaces remain stable.

No status, lease, claim or completion field is introduced. Mutable execution
state stays in Git's common directory. A missing indexed map fails; creating
`queue: []` is valid only for a new unregistered home with no active changes,
under the existing fresh-adoption check. Rename with byte/mode preservation.
The owning change's entry follows `26-11-10-004-rename-agentic-harness`.

Alternative considered: rename the top-level YAML key or redesign this as an
unordered graph. That would change existing selection behavior and add migration
work unrelated to the requested document name.

### 4. Typed installer state and bounded transactional conversions

Introduce installation manifest schema 2, retaining the current `managed`,
`upstream` and `blocks` file-digest maps and adding a required `links` map of
exact discovery leaves to typed records containing `kind: directory_symlink`
and the literal target. Legacy schema-1 manifests remain valid inputs and imply
no link ownership. Reject unknown link types, overlapping managed/link paths,
links for unselected providers, and any record outside the finite allowlist.
Canonical skill bytes contribute to payload identity; link records contribute
to the installation identity. Consumer settings and maps are not managed files,
but expanded settings continue to participate in the configuration digest.

For example, the new ownership member is exactly:

```json
{"links": {".agents/skills/sdw-run": {
  "kind": "directory_symlink",
  "target": "../../agentic_harness/skills/sdw-run"
}}}
```

Existing `managed` values remain SHA-256 strings identifying regular file
contents, not link text. The new schema requires `links` even when empty. Link
records allow exactly `kind` and `target`; legacy manifests do not acquire link
semantics from strings that happen to name paths.

The installation plan and read set distinguish absent, regular file, real
directory and approved link. File state includes bytes/digest and permission
mode; directory state includes its complete immediate entry names and mode;
link state includes its literal text and type without target dereference.
Observe every source, destination and structural parent before the first read
or conflict decision. Recheck after generation/dependency preparation and before
each mutation, accounting for the installer's own preceding expected changes.
No-follow directory-relative operations or equivalent verified parent handles
must prevent an ancestor swap from redirecting writes outside the target.

The legacy conversion is allowed only when each discovery directory is real,
its sole child is the recorded owned regular `SKILL.md`, and its bytes match
the old manifest. Even an empty extra directory or same-content unowned child
blocks conversion. A missing or modified owned file, unowned existing link,
wrong path type or nonliteral target is a conflict. An unowned canonical regular
file may follow the existing identical-content adoption rule; differing bytes
cannot be overwritten. No unowned discovery directory is deleted merely because
its skill body resembles the current package.

Model the conversion as a structural operation, not a file write through the
eventual link: retain old file bytes/mode and directory mode, remove the verified
child, remove only its now-empty verified directory, then atomically publish a
temporary relative symlink at the leaf. Publish canonical files first, and the
new manifest last. Existing approved links are inspected with `lstat/readlink`,
never with `read_bytes` or recursive copying. Remove a no-longer-selected owned
link only at its leaf, leaving canonical payload and unrelated provider content
intact.

Rollback reverses the applied operation list and restores the original file,
directory or link kind, literal target, bytes and portable permissions. Restore
directory modes before restoring their children. Unlink a created link before
restoring a copied skill directory. Remove only directories created by this
transaction and still empty. Preserve old package caches and unrelated leftovers
under the existing legacy-directory rules. Symlink permissions are not portable;
link type and text, regular-file permissions and real-directory modes are the
restoration contract.

Before reversing an applied operation, verify that its current state still
matches the installer's recorded poststate. If another actor changed it, preserve
that content, restore other uncontested operations, and report the exact paths
requiring recovery; never overwrite a concurrent edit to claim full rollback.
This is rollback on detected application failure, not a claim of multi-file
atomic visibility or power-loss recovery. Active-worktree guards remain in force.

Alternative considered: add symlinks to `target_path`'s generic permitted types.
That would allow alias traversal in unrelated settings, payload and upstream
paths, so ordinary resolvers remain strict and link operations use their narrow
typed API.

### 5. Migration is explicit and atomic across the registered layout

The installer independently observes and parses old and new settings/map
candidates before choosing migration inputs. Compare normalized setting values
(including default empty environment/exclusion fields) and the validated ordered
dependency lists. Reject differences, malformed YAML, unknown fields, wrong
types or aliases. Equivalent duplicates are explicitly shown as coalescing in
the plan: retain the new destination bytes/mode and remove the verified old
copy. This privilege belongs only to migration, not normal runtime selection.

If only a legacy settings or map file exists, copy its exact bytes and mode to
the destination and remove it only within the transaction. If settings exist
only inline, serialize an equivalent schema-1 settings document, retaining the
stable ID/root. Schema-2 or schema-3 missing indexed authority is an error, not
permission to recover from an unindexed alternate or supplied check flags.
An unregistered home may deliberately adopt a valid existing settings file.

Plan all registered homes together when publishing schema 3, including
provider-union links, owned routing blocks, digest changes, and dependency-map
renames. Do not publish a schema-3 index while another home still uses schema-2
locations. Compose this transaction with the existing `_agentic_harness` move;
the new runtime/settings destination is always the canonical root. Preserve
existing rejection of local scope, command or lockfile references that would
point at removed package inputs. Also detect explicit references to removed
settings/map/copy paths in those bindings and require deliberate reconciliation;
do not rewrite arbitrary command arguments. Historical privacy exclusions can
continue to name old paths.

Read set and rollback include settings source/destination, both map names,
registry, manifest, native configuration observations, discovery directory
inventories, canonical destinations, instruction blocks and their modes. Dry-run
shows moves, removals, link targets and type transitions without modifying the
target or preparing target dependencies. Reapplying unchanged settings and
providers produces no bytes, types, permissions or manifest changes.

### 6. Review evidence records link identity as inert data

Keep `relative_path` strict. Add separate exact-link-leaf admission only where a
source/assignment explicitly represents that object. Ownership retains the
lexical discovery leaf; it never resolves to the canonical target. Assigning a
descendant through an existing link is forbidden. Admission checks explicit
intake and project eligibility for both link and canonical source independently.
Coordination prevents a leaf conversion from overlapping an assignment to an
old child path. Its existing source-state link-text hash remains relevant.

Introduce retained-source schema 4 for typed inputs while continuing to verify
schema-2 and schema-3 originals with their existing identity formulas. Keep
`input_files` as path-to-digest and `input_modes` as path-to-Git-mode, with
`120000` allowed only at approved discovery leaves. Link digest bytes are the
literal UTF-8 target text. `input_revision` binds the schema-4 typed maps and
original records; it cannot alias a schema-3 revision. Every current link requires
its canonical `SKILL.md` explicitly in `input_scope`; reject an incomplete scope
rather than silently broadening it. Link validation does not require the
installer manifest for this source repository, but it does require the exact
allowlisted target and real canonical skill path.

Schema 4's revision preimage is canonical JSON with keys `schema_version: 4`,
`input_files`, `input_modes` and `deleted_files`. An original
record is exactly `{"sha256": "<digest>", "mode": "100644|100755|120000"}`;
current link text is retained under the normal `input_files` digest and mode
`120000`. Current inputs and deleted originals remain disjoint. Existing manifest identity
and policy fields remain present; historical schema-2/3 verification formulas
are unchanged. Schema numbers here describe source evidence independently of
installation manifest schema 2 and project index schema 3.

Store link bytes as read-only regular files at their lexical leaf under retained
`source/`, with symlink type carried solely in the manifest. No traversable
symlinks are created in retained source. Verification distinguishes this storage
mode from original mode `120000`, rejects extra entries, validates literal
targets and canonical coverage, and confirms live `lstat/readlink` identity when
a worktree is supplied. Reviewer prompts explain these inert link records and
where canonical content lives. No ordinary public-source or exclusion rule is
relaxed. Capture uses before/after no-follow identity checks and republishes
nothing if parents, link text, canonical files or policy change while reading.

Deleted originals retain their lexical paths and are read from Git only.
Inventory must stop at a symlink ancestor: after a copy-to-link conversion,
`.agents/skills/sdw-run/SKILL.md` is absent as an independently stored path even
though following the new link would find a skill file. Report it in
`deleted_scope`; `_deleted` must not call a live child resolver that traverses
the new parent. Validate the original path and all its ancestors against the
immutable base instead. Current approved links and canonical source are new or
changed inputs, so all three identities remain reviewable.

Deleted approved discovery links are retained as inert target bytes with mode
`120000`, validated against their exact allowed path/target in the immutable
base. They are never traversed, and arbitrary historical symlinks remain
unsupported. A same-leaf regular-file/link replacement is outside this migration:
capture and changed-source inventory fail with an actionable unsupported-type-
transition error rather than omitting the original or treating it as an ordinary
edit. The actual copied-directory migration has distinct old child and new link
paths, so ordinary deleted originals plus typed current links fully describe it.
No replacement-history fields, request API or extra retained tree are introduced.

`_base_exclusions` reads schema 1 inline settings, schema 2 old companions, or
schema 3 deterministic harness paths from the same immutable Git base. The
base's index location selects the historical package root; no live settings or
preferred-name fallback may substitute for it. Validate duplicate authorities,
path syntax and file kinds within that commit, without live alias checks.
Current and historical exclusions are combined for deleted originals. Malformed,
missing or ambiguous historical authority fails closed.

Final acceptance requires the selected schema-appropriate settings file, index,
native configuration, dependency map, changed links, required canonical skill
inputs, and complete deleted originals. `changed_scope` must identify untracked
links, link deletions, literal target edits and displaced children even with
`core.filemode=false`; unsupported same-leaf type transitions and unsafe links
fail explicitly rather than disappearing from coverage. Existing reports, ledgers and bundles are not
rewritten or relabeled.

Alternative considered: materialize live symlinks in reviewer source. Inert link
data preserves exact identity without introducing alias traversal into otherwise
read-only, public-source trees or requiring targets outside the retained scope.

### 7. Implementation ownership and verification boundaries

Use bounded slices with exact paths assigned before dispatch. The table defines
responsibility; it does not grant concurrent ownership of every listed path.

| Slice | Exclusive implementation responsibility | Dependency |
| --- | --- | --- |
| Configuration and layout helpers | `projects.py`, new `skill_links.py`, registry/selection tests | First; freeze helper interfaces before dependent writers |
| Installer and adapters | `tools/workflow.py`, `tools/adapters.py`, installer/layout/adapter tests | Uses frozen helpers; owns all install transaction changes |
| Evidence and acceptance | `evidence.py`, intake/dispatch/lifecycle/coordination changes and their runtime tests | Uses frozen helpers; owns all schema-4 and scope integration |
| Source adoption and guidance | canonical skills, discovery links, own config/index/map, current docs/policies/procedures, native context and generated handbook | Runs after runtime and installer behavior stabilize |

The lead allocates concrete test files and any helper amendments to one writer
at a time. Installer and evidence slices may run in parallel only after helper
ownership transfers are explicit. Guidance and checked-in adoption cannot race
an installer or runtime writer's fixtures. No generated OpenSpec body is assigned
for edits. Independent reviewers, not authors, assess the frozen design and later
implementation under the selected run ledger.

Tests map to the delta scenarios:

| Coverage | Scenarios and concrete checks |
| --- | --- |
| Canonical skills and discovery | C01/C17/C21/C22, D01/D09: provider matrix, one canonical body, exact relative targets, Markdown resolution from all locations, canonical and link drift, creation failure/rollback, unchanged upstream bytes |
| Settings and selection | C02/C08/C11/C18-C20: schema 1/2/3, root/components, spaces and distinct homes, missing authority, equivalent/conflicting duplicates, unchanged IDs/argv/locks/exclusions, exact settings eligibility and overlap rejection |
| Transaction boundaries | C05/C06/C13-C16/C23/C24: actual old-format installs, dry-run full typed tree snapshot, repeat install, extra child including empty directory, modified copy, ancestor alias, alternate link target, concurrent entry/type/mode changes, faults after conversion/config/map/index/manifest publication |
| Source and authority | C09, W04/W08-W13, L06/L12: new/deleted/retargeted links, displaced child originals, explicit same-leaf type-transition refusal, inert retained storage, extra/tampered entries, missing canonical coverage, omitted final link, every historical privacy schema and old package root |
| Dependency semantics | L03/L10/L11: byte/mode rename, duplicate conflicts, current missing map, prerequisite ordering/cycles, pinned-base archive behavior, read-only inspection, no status fields |
| Documentation and compatibility | D02/D05/D09: current links and examples, settings ownership, legacy guidance, supported-vs-tested discovery claims, preserved native configs/custom schemas and clean pinned generation |

Extend the existing tests in `tests/` and `agentic_harness/tests/`; add a focused
skill-link module test if needed. Do not use a snapshot helper that silently
omits symlinks: record link text, node kinds, bytes and relevant modes without
following links. Installer tests use temporary Git repositories only. In
addition to synthetic unit fault injection, exercise the real pinned toolchain
for fresh root adoption, root-with-selected-folders adoption, component-home
adoption, a second independent home, and upgrades produced by prior installer
formats. A hand-edited current manifest alone is insufficient upgrade evidence.

## Risks / Trade-offs

- **Symlink support varies by filesystem/client** → Fail with recovery details
  when link creation is unavailable. Test actual filesystem links and document
  provider support without claiming unperformed fresh-session tests.
- **Directory-to-link conversion masks old children** → Use lexical inventories,
  explicit structural operations and immutable-base originals. Never rely on
  `exists()` through a changed ancestor for deletion detection.
- **A race can prevent complete rollback** → Compare operation poststates, retain
  concurrent work and report unresolved recovery paths. Parent-handle safety
  prevents escaping the repository; this does not promise atomic visibility to
  other processes or crash recovery beyond the existing runtime.
- **Settings now share a parent with installed code** → Exclude all consumer
  config from payload ownership and restrict project eligibility to one exact
  file. Preserve check-authority review and expanded configuration digests.
- **Versioned readers increase compatibility surface** → Keep explicit schema
  branches, immutable historical lookup and actual-upgrade regression fixtures;
  do not infer a layout from the current filesystem.
- **Old user scripts can reference removed paths** → Show exact moves, reject
  detected executable-binding references that would break, and document manual
  reconciliation. Do not rewrite arbitrary commands or historical archives.

## Migration Plan

1. Complete independent design acceptance before implementation. Develop helpers
   and runtime support, then installer/evidence slices and their regression tests.
2. Adopt the layout in this repository with one canonical skill set, both native
   discovery link sets, schema-3 own index, moved own settings and renamed map.
   Preserve existing setting bytes/modes except separately required truthful
   current-context edits; add this change's dependency entry without renumbering.
3. Update current README, bootstrap, scope/integration guidance, policies,
   procedures and native OpenSpec context. Leave historical archives untouched.
   Rebuild `agentic_harness/index.html` from maintained sources.
4. Verify the temporary-install and upgrade matrix, then run
   `uv run --locked pytest`, the handbook build freshness check, and pinned strict
   OpenSpec validation of the change and all project specifications. Compare
   generated upstream integrations to clean OpenSpec 1.14.3 output.
5. Reconcile complete final source including links and original removals, obtain
   independent implementation acceptance, and only then check tasks, synchronize
   deltas and archive through the pinned CLI in this same implementation change.
   Archive relocation requires refreshed affected review evidence.
6. Deliver locally within existing authority. No GitBob migration or remote
   publication follows from this layout change. Idle consumer upgrades use the
   installer; active runs retain their original worktree/runtime/evidence. Failed
   installs restore prior owned state where uncontested and report any preserved
   concurrent changes requiring recovery. Post-success downgrade is not an
   automatic reverse migration; retain the reviewed pre-update state for
   deliberate recovery rather than rewriting live run evidence.
