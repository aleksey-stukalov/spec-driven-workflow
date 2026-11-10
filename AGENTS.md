# Working on spec-driven-workflow

Read [README.md](README.md), [BOOTSTRAP.md](BOOTSTRAP.md) and the applicable
requirements under [openspec/](openspec/) before substantive changes. This
repository develops the reusable workflow; application facts belong in the
consumer project's configuration and specifications.

- Keep OpenSpec-generated `openspec-*` skills and `opsx-*` commands unchanged.
  Generate them with the pinned upstream CLI. Our integrations use `sdw-*`.
- Preserve existing consumer instructions, settings and specifications. Shared
  files require narrow ownership and conflict detection.
- Keep whole-repository and selected-folder installations working. Do not assume
  the application uses Python, uv, GitBob or a particular source layout.
- The runtime's dependencies are isolated under `_agentic_harness`. Consumer
  checks and dependency locks come from project registration.
- Use separate file ownership for concurrent edits. Retain the accounting,
  recovery, original-evidence and independent-review contracts during refactors.
- Run `uv run --locked pytest` and relevant pinned OpenSpec validation. Test
  installation against temporary repositories, not unrelated live projects.
- Record changes to process contracts in OpenSpec. Keep completion evidence
  accurate and leave unfinished tasks unchecked.
- Do not publish, migrate GitBob or merge without the applicable user authority.

The initial extraction is local work. Remote repository creation and GitBob's
adoption remain separate actions.
