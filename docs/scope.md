# Applying the workflow to part of a repository

An adopted project is a named development domain with one OpenSpec authority.
It may cover the whole repository, one directory, or several disjoint directories.
The domain boundary follows work and contracts; it need not match one folder.

## Separate the boundaries

| Boundary | Meaning |
| --- | --- |
| Repository root | Git history, worktrees, shared integration and host-local coordination |
| Registered project `root` | Directory containing that project's `openspec/`; `.` means the repository root |
| Registered `code_roots` | Explicit source areas adopted by the process; several paths may belong to one project |
| Workflow metadata | The selected project's `openspec/` tree, including its specification and queue |
| Shared installation files | Package runtime, namespaced skills and narrowly owned instruction blocks |
| Task scope | Paths authorized for one bounded request |
| Writer ownership | Exact files assigned exclusively to one writer |
| Read and test context | Relevant dependencies and checks needed to understand or verify the change |

These boundaries are related, but they are not interchangeable. An OpenSpec home
can sit at repository root while its project covers only a service and its tests.
A dependency may need to be read without becoming writable. A repository-wide
test may be necessary for a local change without expanding implementation scope.

## Whole repository and selected areas

For whole-repository adoption, register `root: .` when OpenSpec lives at the
repository root and use `code_roots: [.]` deliberately. Secret, ignored and
unsafe paths remain unsuitable for retained evidence. Task and assignment scope
must still be bounded; whole-repository adoption is not unlimited task authority.

For partial adoption, list the actual source and test roots. For example,
`services/api` and `tests/api` may form one project. Its OpenSpec home may be
`services/api` or a separately selected project directory. Register checks that
validate this behavior and its affected shared interfaces.

Do not create a separate specification project for every physical folder. Use
separate projects only when they have independent change lifecycles and clear
ownership. Preserve existing OpenSpec homes during adoption. Commands select a
registered project explicitly when more than one exists; the wrapper pins its
working directory and CLI.

This version does not register nested OpenSpec project roots, even if their code
roots are disjoint. A project with `root: .` cannot coexist with a second
component-root project. Use one root-level project covering the selected folders
or separate non-overlapping project roots. This is a package constraint, not a
claim that OpenSpec itself lacks nested-root discovery.

## Shared files and overlapping work

Adoption can require shared routing in `AGENTS.md` or `CLAUDE.md` and namespaced
skills under agent discovery directories. These are installation changes, not
an automatic grant for ordinary product changes to rewrite all root settings.
The install record distinguishes package-managed files from project-owned
configuration and generated OpenSpec files.

Name a shared build file, dependency lock, schema or CI configuration explicitly
when a task needs to change it. Include the relevant owner, tests and approval
in the task's scope. A matching parent directory is not sufficient justification
for expanding a narrowly requested change.

Ambiguous overlaps between registered domains are rejected. If one change spans
multiple domains, resolve its owning changes, specification updates and writer
ownership before dispatch. Do not silently
choose a project based on the first touched file or assume an overlap means both
projects can write concurrently. The current bounded run selects one project;
it is not a cross-project scheduling system. Split independently owned work or
explicitly reconcile the project binding; do not broaden it implicitly.

## What isolation means here

Worktrees isolate Git working copies. The dispatcher checks declared writer
paths against task and project boundaries and coordinates exclusive ownership.
Final review must inspect the full diff, including new, deleted and renamed
paths. Neither a nested instruction file nor an OpenSpec root is an operating
system sandbox or a guarantee that arbitrary commands cannot write elsewhere.

The coordination database is shared by linked worktrees in one Git common
directory on one host. It does not prevent concurrent work in another clone or
machine. Use the repository's normal remote coordination for those cases.

## Checks for an adoption

Verify the selected OpenSpec root from both repository and component entry
points. Confirm that existing specifications, instructions and unrelated agent
settings remain intact. Inspect the installation diff and repeat installation
to establish that unchanged inputs produce no further edits.

Exercise one bounded change against the adopted paths, including relevant
shared interfaces. Confirm that outside paths are not silently admitted and
that final evidence covers all actual changes. Record the installed package
version and update it through a reviewable change. Package upgrades do not
reclassify historical runs or replace product specifications.

The [extraction inventory](extraction.md) explains what comes from the source
workflow. The executable rules start at the
[policy map](../_agentic_harness/policies/README.md).
