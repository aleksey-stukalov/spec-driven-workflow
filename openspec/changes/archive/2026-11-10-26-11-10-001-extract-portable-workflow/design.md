## Context

The source is [GitBob PR 128](https://github.com/ignatov/gitbob/pull/128) at
`8a21c9da8e38a55079df81db00200de018375e01`, including the earlier components it
uses. `_agentic_harness/` is not self-contained there: application paths,
environment assumptions and importer-owned specifications cross its boundary.

The source's twelve nested OpenSpec skills match pristine 1.14.3 output. Twelve
root-level `openspec-*` wrappers provide custom routing under upstream names.
The extraction replaces that routing with separate `sdw-*` integrations.

## Goals / Non-Goals

**Goals:** preserve the reusable execution controls; support whole-repository
and selected-folder adoption; install without replacing local policy; keep
OpenSpec reproducible and unchanged; verify behavior in isolated fixtures.

**Non-goals:** migrate GitBob, import its application requirements or historical
runs, publish remotely, add another tracker, coordinate multiple hosts, promise
filesystem confinement by folder, or claim measured model quality or savings.

## Decisions

1. Keep `_agentic_harness/` as the installed runtime and policy directory. The
   project registry and product artifacts remain local configuration; package
   ownership is recorded separately in the installation manifest.
2. Keep the standard OpenSpec schema and pin 1.14.3. Use supported initialization
   and update operations. Package integrations own `sdw-*`; upstream retains
   `openspec-*` and any generated command namespace.
3. Keep the OpenSpec home independent of code roots. `.` explicitly means the
   repository root. Several source folders may form one logical project.
   Ambiguous overlaps require resolution; the installer does not invent a
   cross-project coordination policy.
4. Bind environment verification to declared lockfiles and preparation commands.
   An empty lockfile list is valid. Missing declared files remain recorded as
   absent; creation, deletion or edits require reconciliation. The harness does
   not assume the target uses Python or execute preparation implicitly.
5. Preserve source profile choices in `plans.yaml`, including the paired routes,
   two-worker limit and clean-round rules. They remain shipped policy choices,
   subject to client/account capability checks and existing user authorization.
6. Merge narrowly owned instruction blocks and create namespaced integration
   files. Preserve host configuration, local instructions and product specs.
   Reject conflicting managed-file edits rather than overwrite them silently.
7. Leave historical runs in their original checkout and version. Installation
   does not relabel old ledgers or promise automatic active-run migration.
8. Support non-behavioral maintenance explicitly: `skip_specs: true` requires no
   capability deltas or main-spec behavior edits, but still requires completed
   tasks, checks and review evidence.

## Scope and Ownership

Process applicability, permitted task edits, dependency context and installation
glue are separate. A project covering `apps/api/` and `tests/api/` can read shared
dependencies without receiving blanket write authority over them. Root-level
discovery files may be touched during adoption without making the process apply
to all application code.

The dispatcher checks exact declared owned files against intake and registered
scope. Native write confinement is workspace-wide; these checks and instructions
do not establish an operating-system sandbox for each folder.

## Validation and Migration

Port relevant runtime tests and add checks for root adoption, disjoint folders,
existing configuration, path aliases, repeated installation, managed-file drift,
OpenSpec routing and unchanged upstream generation after update. Use synthetic
native-provider and GitHub transports for execution and recovery tests. State
their limits separately from real CLI installation and filesystem checks.

Once implementation and verification complete, synchronize these deltas and
archive this change with the pinned CLI. Keep tasks unchecked until their checks
have actually passed. GitBob becomes a consumer through a later explicit
migration; its existing worktrees, environments and evidence remain untouched.

## Human Decisions

- Use `/Users/Aleksey.Stukalov/Misc/spec-driven-workflow` for implementation.
- Extract into the new repository first; migrate GitBob in a separate next step.
- Remove custom changes from OpenSpec-owned integration surfaces and preserve
  the process through separate package files or supported OpenSpec configuration.
- Support adoption for selected folders as well as an entire target repository.

## Source Requirement Mapping

The five `harness-*` capabilities retain the source topics and portable controls.
New scenarios use the `SDW-` prefix. GitBob-specific roots, data classification,
application fingerprint and packaging contracts become project bindings or stay
in GitBob. Offline HTML, SVG rendering and its historical entrypoint are not
delivery obligations of this Markdown-based package.
