# Apply this workflow to a project

Read this entrypoint when asked to apply spec-driven-workflow to an existing
repository or selected directories. Work from a reviewed version of this
repository. Read the [README](README.md) and [scope rules](docs/scope.md).

## Inspect the project and choose its OpenSpec home

Read the target repository's applicable instructions and contribution rules.
The target must be a Git worktree root. Initialize Git only when creating a new
project is part of the user's request; select an existing worktree otherwise.
Inspect existing OpenSpec roots, agent skills, build and test commands, package
managers and lock files. Do not copy the example application's settings.

Choose the directory containing `openspec/`, the source and test paths covered
by the process, required checks and dependency locks. Prefer one existing
OpenSpec home for folders that share a change lifecycle. A home at the repository
root can describe only selected folders; it need not cover all application code.
Use a component's existing OpenSpec home when that component develops separately.
Identify shared files and related tests outside the immediate source directory.
Reading a dependency does not authorize editing it. Resolve overlapping scopes
and conflicts with existing process rules before installation.

Keep the target's existing specifications and context. Initializing OpenSpec
does not establish that the existing application is fully specified or verified.
Develop specs incrementally through actual changes. Do not invent product
requirements, task completion, issue references or review evidence.

Keep native OpenSpec settings in `openspec/config.yaml` or `config.yml`: schema,
project context, artifact rules and supported operation guidance. Keep this
workflow's executable checks, code roots, preparation, lockfiles and evidence
exclusions in `agentic_harness/config/workflow.yaml` for the root home, or
`agentic_harness/config/<home>/workflow.yaml` for a component. These are
project-owned settings, preserved during package updates. Paths inside `workflow.yaml`
are relative to the Git worktree root. Preserve existing file contents and schema selection.
The built-in `spec-driven` schema provides the required artifacts; custom schemas
must keep compatible proposal, design, tasks and capability-delta paths for the
execution runtime. Do not equate preservation with arbitrary schema support.

## Prepare and apply the installation

Use the [documented installer](README.md#install-into-a-project). Select the home
with `--spec-root` when it is below the repository root. No project name is
required. Pass the real scope and checks for a new configuration, or inspect and
reuse the selected home's existing harness settings. Use argv arrays for
checks, not shell fragments. Select only the agent integrations used by the
target project.

Run `install --dry-run` first and inspect the planned diff. Package files,
project-owned configuration, OpenSpec-generated files and shared instruction
blocks have different owners. The install must preserve unrelated text, skills,
agent settings and specifications. Resolve reported conflicts explicitly.

Once installation is within the user's authorized scope, apply it and run
`doctor`. Existing authorization does not need to be requested again. Separate
remote publication and merge actions still need their own applicable authority.
The installer does not create GitHub repositories, issues or pull requests.

## Verify adoption

Use `harness.py project` to inspect the selected home, or `project --at PATH` to
select it by a repository-relative directory. A nearer OpenSpec home that has
not adopted the workflow is an error, not permission to use another home. Use
explicit `--at` selection when the current directory cannot distinguish several
installed homes, including tests located outside a component's home.

Confirm that the selected home's pinned OpenSpec CLI reports the expected root and
that the target can execute its declared checks. Inspect the final diff for
changes outside the declared source scope and the reviewed installation files.
Running installation again must not create another change.

In a fresh agent session, verify that the scoped entrypoint leads to `sdw-run`,
the correct OpenSpec home and the pinned OpenSpec toolchain. The `sdw-*` entrypoints
invoke the workflow; ordinary OpenSpec commands alone do not provide its review
and acceptance gates. If authorized,
use one small real task to exercise the lifecycle. Installation alone does not
prove that a native provider, GitHub permissions or the application environment
is ready for that task. Report any unverified capability specifically.

## Update deliberately

Choose a reviewed version of the workflow repository and run `update --dry-run`
from that checkout. Inspect the differences, resolve package-file drift and
apply the update within the task's authority. Preserve the target's configuration
and OpenSpec data. Never modify `openspec-*` or `opsx-*` output to embed this
workflow; use its own `sdw-*` files and supported OpenSpec configuration.

For an installation under `_agentic_harness/`, the plan migrates verified
package-owned files and the internal index to `agentic_harness/`. It refreshes
owned routing while preserving local settings and upstream integrations.
Unowned files, old dependency caches and virtual environments stay at their
original paths. The old ignore file is retained when needed to protect those
leftovers. Inspect the reported retained paths; do not remove them as part of
the package migration. Conflicting destinations or ambiguous installations
must be reconciled before the update.

Check project-owned commands, scope paths and dependency locks for references to
managed files under the old directory. Migration stops when these need deliberate
reconciliation; update the appropriate local settings before retrying the dry-run.
Keep evidence exclusions for any files retained under the old path.

The plan moves legacy `openspec/workflow.yaml` files or inline settings from
`projects.yaml` into the deterministic harness configuration paths. Each
`openspec/queue.yaml` becomes `openspec/dependency-map.yaml`; its ordered YAML
content and dependency semantics remain unchanged. The schema-3 index keeps
stable identifiers and roots only. Preserve those identifiers: run history and
retained evidence use them. Conflicting old/new settings or maps require
reconciliation; equivalent duplicates may be explicitly coalesced during update.
Missing indexed authority is an error, not permission to invent replacement
settings. Edit the selected harness settings and refresh through `update`.

Canonical SDW skills are regular files in `agentic_harness/skills/`. The installer
creates relative links for individual `sdw-*` directories under the selected
agents' discovery directories. It preserves other skills and upstream files.
Old copied directories can become links only after ownership and their complete
contents are verified. Extra content, modified copies, unsafe links or unsupported
link creation stop installation. Review the reported recovery paths if concurrent
edits prevent complete rollback; never remove that content automatically.

Active runs retain their recorded source, catalog and evidence versions.
Complete or checkpoint them in their original worktree before adopting a changed
runtime. An update does not relabel old evidence as current acceptance.
