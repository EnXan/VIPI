# 0061 — Prompt Guard detector configurations for evaluation

Status: accepted, 2026-11-10. Extends
[ADR 0057](0057-jev-detector-configurations.md).

## Context and sources

The product supports Prompt Guard 2 (`meta-llama/Llama-Prompt-Guard-2-86M`,
pinned by `PROMPT_GUARD_REVISION`) as a local final detector
(`vipi scan --detector prompt-guard`). It classifies the final OCR text only;
it does not review OCR. The workbench lost its multi-detector comparison with
[ADR 0055](0055-workbench-without-research-model-tools.md), and ADR 0057 added a
second detector (Jev) only for cloud runs, so Prompt Guard could not be
evaluated. The user asked on 2026-11-10 to make it selectable.

## Decision

- `local-speed-prompt-guard`, `local-balanced-prompt-guard` and
  `local-quality-prompt-guard` add `detector: prompt-guard` to the matching
  local configuration. OCR, OCR review (d1 or Clef) and threshold stay the
  same, so only the final detector differs.
- The workbench offers Prompt Guard 2 (Meta) in the detector field for every
  local OCR size.
- A configuration that uses Prompt Guard records its repository and pinned
  revision in its model identity (`detector_models`), so a changed Prompt
  Guard revision turns its baselines stale. Other configurations record no
  such field, so their saved baselines stay comparable
  ([ADR 0060](0060-model-identity-per-used-entry.md)).

## Alternatives

- *Prompt Guard also for Clef-Flash*: one more configuration without a current
  request; it can be added the same way.
- *A free detector setting*: rejected in ADR 0057 for the same reasons.

## Consequences

Twelve configurations. Preparing Prompt Guard needs accepted model terms on
Hugging Face; runs are free and offline afterwards. Results of a
`-prompt-guard` run can reuse the OCR of its local counterpart (ADR 0058) when
code and packages match.

## Validation boundary

Tests cover the configuration list, that the Prompt Guard configurations
resolve the same OCR model and review provider with Prompt Guard as detector,
the `detector_models` identity entry and its absence elsewhere, and the
workbench label. A real 3-image `local-speed-prompt-guard` benchmark on an
Apple M2 (16 GB) completed all three images in 47 seconds. The three saved
baselines stay `fresh`. No full development-split run with Prompt Guard has
been executed.
