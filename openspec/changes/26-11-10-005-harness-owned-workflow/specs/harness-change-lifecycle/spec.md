# Spec Delta

## MODIFIED Requirements

### Requirement: Canonical queue and qualified selection

Each project SHALL maintain an ordered `queue` list of stable full change IDs
and dependencies in its home's `openspec/dependency-map.yaml`. Selection SHALL
validate the map and prerequisites at the pinned base. Explicit selection SHALL
override ordering but not dependencies, readiness or authority. Listing and
selection SHALL NOT claim or execute work. Mutable execution status SHALL remain
outside this document in the existing coordination store.

#### Scenario: SDW-L03 The next eligible change is incomplete

- **WHEN** the first unfinished dependency-satisfied change lacks required planning or has an execution blocker
- **THEN** selection reports that blocker without silently choosing a later change
- **AND** malformed, duplicate, cyclic or improperly ordered dependencies prevent execution selection
- **AND** an archive in another unmerged worktree does not satisfy a dependency at the pinned base
- **AND** reordering queue entries does not rename their stable IDs.

#### Scenario: SDW-L10 Rename the planning dependency document

- **WHEN** an idle verified installation moves from `queue.yaml` to `dependency-map.yaml`
- **THEN** the installer preserves its ordered entries, prerequisite edges, archived history, bytes and permissions
- **AND** its `queue` key and entry schema remain unchanged
- **AND** changes and archives are still resolved beside the dependency map in the selected OpenSpec home
- **AND** internal queue fields and coordination commands remain compatible without adding a status authority.

#### Scenario: SDW-L11 Reject conflicting dependency documents

- **WHEN** both old and new dependency documents exist with different ordered entries or dependencies
- **THEN** update fails without modifying either file
- **AND** runtime selection rejects the ambiguous pair instead of choosing one
- **AND** an installer may explicitly coalesce equivalent documents while preserving destination bytes and permissions
- **AND** a missing indexed map is not silently replaced by an empty list or a legacy filename.

### Requirement: Independent final-revision acceptance

Design and implementation acceptance SHALL require complete independent review
of final relevant inputs and passing required checks. Coverage SHALL include
changed link identities, canonical skill inputs, original deletions, dependency
map and selected settings authority. Authors SHALL NOT
review themselves. Disputed serious findings SHALL remain blocking; material
edits SHALL invalidate affected acceptance and require fresh independent review.

#### Scenario: SDW-L06 A repair follows review

- **WHEN** a fixer changes code, tests, design or lifecycle artifacts after review
- **THEN** the affected checks and review inputs are reconciled to the final content
- **AND** both required independent review lenses cover that content before acceptance
- **AND** missing reports, incomplete coverage, serious disputes or exhausted capacity produce incomplete results instead of success.

#### Scenario: SDW-L12 Review omits a layout change

- **WHEN** an acceptance request omits a changed discovery link, displaced legacy child, canonical skill input, selected harness settings file or dependency map
- **THEN** final acceptance fails even when supplied ordinary-file hashes match
- **AND** changing a discovery target or file type after review invalidates final-source correspondence
- **AND** an unsupported same-leaf file/link transition fails explicitly instead of bypassing final coverage
- **AND** linked paths are compared by lexical identity without treating target coverage as link coverage
- **AND** moving configuration or archiving a change does not reuse stale review acceptance.
