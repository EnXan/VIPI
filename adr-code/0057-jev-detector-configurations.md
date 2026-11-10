# 0057 — Jev detector configurations for evaluation

Status: accepted, 2026-11-10. Amends one point of
[ADR 0054](0054-evaluation-runs-and-baseline.md).

## Context and sources

ADR 0054 made evaluation configurations the product scan options with the
detector at `auto`. `auto` follows the decision provider: d1 for local Speed
and Balanced, Clef for local Quality, OpenAI (`gpt-6-luna`) in the cloud
(`ScanOptions.resolved_decision_provider` in `src/vipi/config.py`). Jev is a
supported cloud detector (`vipi scan --detector jev`) but no configuration
selected it. On 2026-11-10 the user asked to select Jev in the workbench to
compare it directly with OpenAI Luna.

## Decision

- Three configurations `cloud-google-jev`, `cloud-openai-jev` and
  `cloud-mistral-jev` add `detector: jev` to the matching cloud configuration.
  OCR, OCR review (decision provider) and threshold stay the same, so only the
  final detector differs.
- The workbench settings show an **Injection detector** field. In the cloud it
  offers OpenAI Luna and Jev; locally it shows the fixed detector and cannot be
  changed. Configuration labels name the detector.
- Each configuration keeps its own baseline, as before.

## Alternatives

- *Switch the decision provider to Jev as well* (`--decision-provider jev`):
  the OCR text could then differ too, so a difference in results could not be
  attributed to the detector.
- *A free detector setting for every configuration* (including Prompt Guard
  and local/cloud combinations): more than requested; local and cloud
  detectors cannot be mixed in the product anyway.

## Consequences

Nine configurations instead of six. Jev runs need `TYPESAFE_API_KEY`; Jev
usage is recorded, but its cost stays unknown because no verified rate is
configured (`src/vipi/ocr/costs.py`).

## Validation boundary

Tests check the configuration list, that the `-jev` configurations resolve the
same OCR model and decision provider with Jev as detector, and the workbench
labels. The settings field was checked in the browser. No Jev evaluation run
has been executed.
