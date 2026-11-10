# Context

The package root is currently embedded in installer ownership, project discovery,
evidence authority, generated adapters and development commands. Most executable
defaults already derive their paths from the script location.

# Decisions

Use `agentic_harness/` as the sole current runtime path. Update live instructions,
test fixtures, CI and generated SDW adapters. Preserve upstream-generated skills,
archived historical prose and source-provenance paths. Rebuild the handbook from
updated maintained sources; do not hand-edit its generated HTML.

The installer discovers one installed layout before reading its manifest/index.
Validate ownership against that layout. Stage current payload and dependencies
at the new path, update owned instruction blocks, and remove verified legacy
owned files plus its manifest/index in the existing rollback transaction. Keep
project-owned companions and identifiers unchanged. Preserve both registry
schema versions and the existing inline-settings migration.

Use per-file ownership rather than renaming or deleting arbitrary consumer
directories. Unowned legacy files, caches and environments remain at their
original paths. Preserve the legacy ignore file when leftovers require it and
report retained content. Prune only empty directories. Reject ambiguous
manifests, unsafe aliases, and destination authority conflicts before writing;
retain concurrent-edit checks and the active-worktree guard.

Rollback restores original file permissions as well as contents, including
legacy paths deleted before a later transaction failure. Record the original
modes before applying the plan; do not infer them from newly created files.
New canonical destinations corresponding to verified legacy owned files,
including the index and manifest, inherit their original modes before publication.
Existing canonical destinations keep their own permissions; unrelated new payload
files use the normal installation defaults.
Apply the same mapping to newly created package directories before populating
them, so a private legacy directory cannot become a public canonical one. Include
directory modes in concurrent-change detection; retain existing destination modes.

Before removing old payload files, detect explicit local source/lockfile/command
bindings to the old package path. Report affected settings for deliberate local
reconciliation instead of rewriting arbitrary argv or preserving broken checks.
Legacy evidence exclusions may still protect retained local content and must
not be indiscriminately rewritten or rejected.

Current runtime selection requires the new index; a legacy-only live authority
must not be mistaken for an unconfigured repository during source capture.
Historical exclusions resolve either index path from the immutable base, reject
dual authority, and read companions from the same commit. Do not rewrite bundle
paths, digests, ledgers or the `.git/agentic-harness` coordination namespace.

# Ownership and verification

The lead owns the physical source-directory move, OpenSpec artifacts and final
integration. Separate writers own installer plus installer tests, runtime plus
runtime tests, and current documentation/adapters/CI. Only the lead rebuilds the
handbook after all rendered sources are frozen.

Verify fresh root and component installs, legacy v1/v2 upgrades, preservation,
conflicts, concurrent edits, rollback and repeat no-op behavior in temporary Git
repositories. Rehearse an upgrade from the published pre-rename revision. Run
the complete test suite, pinned strict OpenSpec validation, HTML freshness and
browser checks. Independently review installer safety and runtime history.

No live consumer or GitBob migration is part of this source-package change.
