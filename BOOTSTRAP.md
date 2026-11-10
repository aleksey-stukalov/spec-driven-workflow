# Apply this workflow to a project

Read this entrypoint when asked to apply spec-driven-workflow to an existing
repository or selected directories. Work from a reviewed version of this
repository. Read the [README](README.md) and [scope rules](docs/scope.md).

## Inspect and bind the project

Read the target repository's applicable instructions and contribution rules.
The target must be a Git worktree root. Initialize Git only when creating a new
project is part of the user's request; select an existing worktree otherwise.
Inspect existing OpenSpec roots, agent skills, build and test commands, package
managers and lock files. Do not copy the example application's settings.

Establish a named development domain: its code roots, OpenSpec project root,
required checks and dependency locks. A domain can span several folders.
Identify shared files and related tests outside the immediate source directory.
Reading a dependency does not authorize editing it. Resolve overlapping domains
and conflicts with existing process rules before installation.

Keep the target's existing specifications and context. Initializing OpenSpec
does not establish that the existing application is fully specified or verified.
Develop specs incrementally through actual changes. Do not invent product
requirements, task completion, issue references or review evidence.

## Prepare and apply the installation

Use the [documented installer](README.md#install-into-a-project). Pass the real
scope and checks explicitly. Use argv arrays for checks, not shell fragments.
Select only the agent integrations used by the target project.

Run `install --dry-run` first and inspect the planned diff. Package files,
project-owned configuration, OpenSpec-generated files and shared instruction
blocks have different owners. The install must preserve unrelated text, skills,
agent settings and specifications. Resolve reported conflicts explicitly.

Once installation is within the user's authorized scope, apply it and run
`doctor`. Existing authorization does not need to be requested again. Separate
remote publication and merge actions still need their own applicable authority.
The installer does not create GitHub repositories, issues or pull requests.

## Verify adoption

Confirm that the selected project's OpenSpec CLI reports the expected root and
that the target can execute its declared checks. Inspect the final diff for
changes outside the declared source scope and the reviewed installation files.
Running installation again must not create another change.

In a fresh agent session, verify that the scoped entrypoint leads to `sdw-run`,
the correct registration and the pinned OpenSpec toolchain. If authorized,
use one small real task to exercise the lifecycle. Installation alone does not
prove that a native provider, GitHub permissions or the application environment
is ready for that task. Report any unverified capability specifically.

## Update deliberately

Choose a reviewed version of the workflow repository and run `update --dry-run`
from that checkout. Inspect the differences, resolve package-file drift and
apply the update within the task's authority. Preserve the target's configuration
and OpenSpec data. Never modify `openspec-*` or `opsx-*` output to embed this
workflow; use its own `sdw-*` files and supported OpenSpec configuration.

Active runs retain their recorded source, catalog and evidence versions.
Complete or checkpoint them in their original worktree before adopting a changed
runtime. An update does not relabel old evidence as current acceptance.
