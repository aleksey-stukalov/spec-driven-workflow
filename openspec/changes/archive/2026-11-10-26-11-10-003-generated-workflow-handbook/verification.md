# Generated handbook verification

Verified on 2026-11-10 with the pinned Python dependencies and OpenSpec 1.14.3.

## Delivered behavior

The presentation-only builder generates `_agentic_harness/index.html` from
12 shipped Markdown sources, the validated plan catalog, graph metadata and
presentation templates. The original responsive styling and SVG layout are
retained with portable wording. The page uses inline CSS/SVG and no scripts or
remote resources. Native settings writes and importer synchronization from the
original generator were not included.

The installer ships the page, generator and required inputs under the existing
package ownership and conflict rules. Consumer checks remain in the consumer's
`openspec/workflow.yaml`; adopting the package does not add browser checks to
those application checks.

## Checks

| Check | Result |
| --- | --- |
| Builder regression tests | 26 passed, including input drift, invalid catalog/graph/links, escaping, deterministic output across paths and write boundaries. |
| Installer regression tests | 69 passed, including handbook ownership and local-edit conflict detection. |
| Real OpenSpec integration tests | 5 passed, including installed build/check from the repository root and a component descendant, unchanged native settings and upstream regeneration. |
| Browser probe regression tests | 8 passed, including intentional graph/page regressions and browser failure cleanup. |
| Complete `uv run --locked pytest` suite | 685 passed in 268.34 seconds on macOS with Python 3.12.14. |
| `build.py --check` | Passed against the generated page without changing files. |
| `check_render.py` and `check_render.py --dark` | Passed at 1440 px and an actual 390 px iframe viewport in both themes; each reported 21 nodes, 30 edges and zero rendering errors. |
| Pinned OpenSpec strict validation | Active change passed before archive; all 5 baseline specifications and all 3 archived changes passed after synchronization and completion. |
| `git diff --check` | Passed. |

The browser uses a disposable profile with background networking disabled and
host resolution blocked. Desktop header/diagram and narrow header/diagram
screenshots were inspected in light and dark themes. Text, arrows and labels
were readable. The narrow diagram scrolls horizontally inside its container;
the page itself does not overflow. Screenshots were temporary QA artifacts,
not inputs to the generated page.

## Independent review

A read-only reviewer checked the design and final implementation for portable
inputs, output ownership, graph-policy consistency and link behavior. A separate
review checked the browser probe and its result extraction. No blocking findings
remained. Additional temporary-package probes covered output/input symlinks,
duplicate YAML keys, duplicate formatted headings and Unicode fragments.

The lead inspected the final integration diff and representative desktop and
narrow screenshots independently of the browser-check author.

## Lifecycle

The three added requirements were synchronized into `harness-documentation`.
Their complete blocks match the delta, and the previous specification content,
including its Purpose, was preserved. The change was archived with the pinned
CLI after this synchronization. Its final bookkeeping task includes archiving
itself, so that task was marked complete only after the archive command succeeded.
Strict validation of the completed archive then passed.

## Verification limits

Browser checks used Chrome; they do not establish exhaustive browser coverage.
The handbook explains the portable process and does not render private consumer
configuration or mutable execution state. Existing runtime tests use synthetic
native-provider transports and do not establish live model quality or billing.
No GitBob checkout, application data or historical execution evidence was changed.
