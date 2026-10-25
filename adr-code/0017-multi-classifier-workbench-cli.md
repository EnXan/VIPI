# 0017: Multi-classifier workbench CLI and guided setup

Status: Accepted for the workbench CLI and UI.

## Context and sources

The user asked for a guided setup with required essentials and only options
supported by the CLI, then clarified that text classifiers must allow any
combination and that the CLI can change to support this. The local workbench
CLI's options are defined in [`detector_options.py`](../research/workbench/detector_options.py)
and parsed by [`research.workbench`](../research/workbench/__main__.py) and
[`detector_cli`](../research/workbench/detector_cli.py). The shared verdict
policy is in [`verdict.py`](../src/vipi/detection/verdict.py).

This replaces [ADR 0016](0016-cli-aligned-workbench-setup.md). ADR 0016 chose a
three-step wizard and matched its UI to a single CLI classifier choice
(`jev`, `openai`, `prompt-guard`, `compare`, or `off`). The rationale was to
keep the UI within existing CLI capabilities. The user has now authorized
changing the CLI to support the multi-select UI, and clarified that `compare`
and `off` are unnecessary once selection is expressed as a list. The guided
three-step flow, required threshold configuration and dataset behavior remain.

ADR 0016 also carried forward ADR 0015's cooperative cancellation decision:
stop requests use a shared event, allow in-flight native/provider calls to
finish, skip queued work and preserve completed results. That decision and its
rationale (threads cannot be safely force-killed while retaining valid saved
state) remain in force.

## Decision

- Keep the three-step setup: choose input, configure options, review and start.
  Dataset browsing and evaluation reports remain workbench input/research
  features.
- Use a checklist for Jev, OpenAI Decisions and Prompt Guard 2. Support any
  subset, including none for OCR-only extraction.
- Make `--text-classifier` repeatable in the workbench CLI. Each occurrence
  selects one classifier; omitting it selects no text classifier. Remove
  `compare` and `off` from CLI choices: selecting every checkbox replaces
  `compare`, and selecting none replaces `off`. A detector CLI invocation with
  no text, image or context check remains invalid.
- Keep the existing internal/API singular aliases and plural option for saved
  results and programmatic callers. The CLI and guided UI use the plural list.
- Require versioned threshold entries for every enabled detector in the UI.
  Detection evaluation requires at least one text classifier and still runs
  without caller context. Require caller context when the context check is
  selected for a regular scan.
- Keep configuration fields limited to options represented by
  `research.workbench extract` (`--model`, `--backend`, `--workers` and the
  shared detector options). The input source chooser and dataset browser are
  workbench workflow features, not scanner configuration flags.

## Alternatives

Retaining `compare` and `off` alongside checkboxes would duplicate the states
“select all” and “select none”. Keeping a single CLI choice would force users to
run separate commands for combinations supported by the detector pipeline.
Removing dataset browsing would discard the requested research workflow;
therefore it remains a source step while actual scanner settings follow CLI
options.

## Consequences

CLI users select multiple text classifiers by repeating the same option, for
example `--text-classifier jev --text-classifier openai`. The no-option case is
OCR-only in `extract`. Detection evaluation cannot silently complete with only
unresolved scores because the UI requires thresholds for all selected signals.
Older saved checks and internal callers retain compatibility with the legacy
`compare`/`off` values and plural API representation.

## Validation boundary

The CLI parser, workbench option adapter and UI are the changed surfaces. The
decision does not claim that supplied thresholds are calibrated or that a
detector's score represents a probability of attack. Existing saved results
are not migrated. Cancellation remains cooperative and waits for in-flight
operations as already documented.
