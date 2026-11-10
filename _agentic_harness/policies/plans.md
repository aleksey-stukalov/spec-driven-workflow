# Plan profiles

[plans.yaml](../plans.yaml) is the machine-readable source for the three shipped
profiles: `budget`, `balanced` and `smart`. `balanced` is the catalog default.
Selecting a profile records a run decision; it does not rewrite user settings
or switch an already running lead. Follow the [execution policy](execution.md).

## Read the catalog

Each step records its responsibility, count scope, context profile and allowed
writes. Each plan binds that step to Codex and Claude model/effort routes and a
successful minimum and attempt maximum. A maximum is a ceiling, not a target.
Conditional steps with zero minimum run only when needed. A zero maximum requires
a recorded extension before launch.

Inspect exact routes and limits with the installed harness interpreter:

```sh
python _agentic_harness/tools/harness.py plans routes --plan balanced
```

The catalog preserves the source workflow's model pairs and budgets as explicit
profile data. They are supported requested settings only when the target account,
client and session can verify them. Equal effort names do not establish equal
reasoning, quality, latency or cost across providers. No measured equivalence or
savings is claimed.

## Counting and acceptance

`D` and `I` are shared design and implementation round counters. Each round
launches both required independent lenses against the same frozen revision;
the second reviewer is not a second round. The `clean_rounds` value specifies
how many complete clean rounds must concern the accepted unchanged inputs.

Count admitted attempts, including failed launches, repairs and retries. Count
implementers per predeclared slice and adjudicators per phase. Routine lead
coordination consumes usage but is not a hidden worker launch. Applicable stages
come from the request; review-only work never starts authors or implementers.

Before a repair, retain enough allowance for the full clean minimum afterward.
When that cannot fit, use the extension process before editing. A material final
integration edit consumes its repair allowance, invalidates affected acceptance
and requires a new frozen capture. Stop once the selected plan's acceptance
conditions and required checks pass.

## Context and configuration

The catalog's `lookup`, `context`, `standard` and `deep` profiles set initial
packet, working-input, result and handoff targets. Deep context requires scoped
authority. Use the smallest verified effective capacity and retain room for
tool-result growth and the runtime reserve. A target cannot enlarge a provider's
window. Save decisions and unresolved work before a handoff.

Project bindings configure paths, checks and environment preparation. Profile
changes are separate package configuration changes and must pass catalog
validation. Do not edit generated adapters to create another route table or
claim an arbitrary catalog extension is supported by this version.

The runtime records the chosen catalog with each ledger. Existing runs retain
their original meaning during an update. Historical source-repository runs are
not imported or relabeled by installing this package.
