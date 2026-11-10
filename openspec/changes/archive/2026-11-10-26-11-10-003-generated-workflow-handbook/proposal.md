# Why

The original GitBob workflow includes an offline HTML handbook with a visual
development flow and role/profile tables. The extraction kept the executable
workflow and Markdown but omitted that useful human-facing view. The user asked
about this HTML and clarified that a tool must build it.

# What Changes

- Restore the visual handbook using the original responsive styling and SVG
  layout, with portable branding and current workflow content.
- Generate prose from maintained package Markdown and tables from `plans.yaml`.
- Keep graph semantics and presentation coordinates separate from runtime policy.
- Provide deterministic build and read-only stale-output checking commands.
- Ship the page, generator and inputs together and check freshness in CI.
- Verify the rendered diagram and page in an isolated offline browser.

# Capabilities

## Modified Capabilities

- `harness-documentation`: generated human-readable handbook and its verification.

# Impact

The package gains a presentation-only generator, templates, graph metadata,
generated HTML and rendering checks. Installer ownership includes these assets.
Documentation and package development checks explain how to build and read them.

The original generator's native settings writes, importer synchronization,
upstream-named wrappers and legacy policy are excluded. This change does not
change execution profiles, review gates, target product checks or GitBob.
