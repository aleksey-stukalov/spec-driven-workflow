# Design

## Sources and generated output

The original HTML is generated rather than independently authored. Preserve that
model. `_agentic_harness/tools/build.py` reads current package Markdown, the
validated `plans.yaml`, presentation metadata in `handbook.yaml`, and templates.
It generates only `_agentic_harness/index.html`.

The handbook renders shipped package policies, procedures and role guidance.
It must not depend on the workflow repository's root README or its own OpenSpec
specifications: those files belong to a different project after installation.
Project configuration remains in native OpenSpec configuration and workflow.yaml;
the visual page explains that relationship rather than storing another binding.

`handbook.yaml` contains section ordering and the existing 21-node, 30-edge
development graph. It does not duplicate model routes or native settings.
The original CSS, SVG frame and geometry preserve the visual design. Replace
GitBob branding, proposed-state language and source-only publication timing with
current process wording. Validate graph endpoints, required gates and repair loops.

Profile and role tables come directly from the validated catalog. Values remain
requested settings and allowances, not measured provider capability or costs.
Inline CSS and SVG make the page usable offline without scripts or remote assets.
Each section has stable anchors; cross-section Markdown links resolve in the
page. Remaining local links resolve to shipped files. The page has one H1.

## Build ownership and portability

The builder has one output and does not modify Markdown, OpenSpec integrations,
native settings, role adapters or runtime state. Normal mode writes deterministic
HTML. `--check` compares expected bytes and fails on stale or missing output
without changing files. Include all relevant source inputs in the fingerprint;
exclude checkout paths and timestamps so installation location has no effect.

The installer owns `index.html`, `handbook.yaml`, templates and the builder with
the existing package-file conflict checks. Native configuration and source scope
remain consumer-owned. An installed package can run its builder and `--check`
without needing the original workflow checkout.

Do not copy the original build script wholesale: it also writes importer native
settings, generates wrappers under upstream names and invokes importer-specific
synchronization. Those operations are outside the portable presentation builder.

## Verification

CI runs the read-only freshness check. Tests cover deterministic output,
catalog/source drift, invalid links/graph data, presentation-only writes and an
installed package's build. Browser verification uses a disposable headless
Chrome/Chromium profile with networking disabled. Inspect desktop and narrow
screenshots and check graph labels, arrows, contrast and clipping.

Browser availability is a package-documentation verification dependency, not a
required dependency or product check automatically imposed on every consumer.
Shared source text and generated output remain separately reviewable in Git.
