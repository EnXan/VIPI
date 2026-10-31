# 0029: Opt-in visual selection and review of measured OCR transformations

Status: Accepted for implementation and a small Jev experiment, 2026-10-31.
This does not approve replacing the baseline or claim improved overall accuracy.

## Context and sources

The maintainer requested selecting a transformation from the image with a
System One model, running OCR, and reviewing the resulting image and text.
They explicitly requested up to three OCR attempts, restarting from the original
so a wrong transformation can be corrected. They authorized Jev tests on six
difficult images and subsequently three passed controls.

The reviewed anchor is native PP-OCRv6 Tiny with the checkpoint1 PDFMiner
grouping and evaluation v4: 89/113 passed. Contrast/orientation experiments are
local artifacts under `.llm-plans/transformations/`,
`.llm-plans/contrast-literature-2026-10-30/` and
`.llm-plans/photoshop-equivalent-2026-10-31/`.

API sources: [TypeSafe images](https://docs.typesafe.ai/images) and
[official choice response types](https://github.com/typesafe-ai/typesafe-sdk-js/blob/main/src/types.ts).
Images currently require the experimental image header and dimensions from
280 to 1568 pixels per side. Choice answers supply a selected label, confidence
and probabilities. These are provider outputs, not calibrated OCR correctness.

## Decision

- Add an explicit research profile, `adaptive-jev`, using `jev-1.14.0`. Retain
  the original-only default and historical transformation control. The public
  scanner's default is unchanged.
- Offer the measured orientation, color/contrast and crop plans. Include an
  unchanged full image. A single choice selects a complete plan. Exclude
  previously attempted plans from subsequent requests: separate axis choices
  repeated the same unsuccessful combination in the first experiment.
- Apply each plan to the original decoded image, use native OCR, group text in
  the corrected view frame, then map grouped boxes back to the input. Ordering
  mapped mirrored boxes in the original frame reverses the corrected text.
- After each OCR attempt, show the original, transformed candidates and their
  OCR text/groups to Jev. Let it accept, retry or report uncertainty, and select
  the best existing attempt, including an earlier one. Keep all candidates and
  raw decisions. Reference text and evaluation outcomes never enter requests.
- Permit at most three OCR attempts, matching the explicit user requirement.
  A requested fourth attempt returns the selected existing candidate with
  `attempt_limit` and `accepted=false`. This trades recovery opportunities for
  the agreed experiment length. Alternatives are fewer attempts or a separately
  agreed larger budget; this is an application choice, not an API constraint.
- Preserve OCR resolution. Only Jev previews are downscaled to the documented
  maximum and padded to the minimum. This can hide small or scaling-dependent
  payloads; save the previews so the actual model input is inspectable.
- Persist model/confidence/probabilities, token usage, timings, plans, native
  observations, grouped readings, final choice and stop reason. Unverified Jev
  pricing produces an unknown total cost, never a zero-cost claim.

## Alternatives and consequences

Running every transform can establish an offline ceiling, but does not test
the requested intelligent selection. Selecting by reference coverage would leak
ground truth. Selecting solely by OCR confidence previously preferred incorrect
orientations. Cumulative filters cannot reliably undo lost pixels.

The new profile sends images and OCR text to TypeSafe; transformation and OCR
remain local when a local recognizer is selected. Local d1/Clef routing remains
a follow-up. An accepted model review is not an evaluation pass. The initial
small Jev test did not recover an additional passed case and included false
acceptance of empty OCR; retain opt-in experimental status.

## Validation boundary

The promoted grouping reproduces all 113 reviewed texts and v4 scores exactly
(89 passed). Tests cover corrected-frame order, inverse coordinate mapping for
every orientation/crop, independent restarts, earlier-candidate selection,
three-attempt exhaustion, uncertain/error outcomes, request contents and cost
reporting. Pixel comparisons check promoted filters against saved experiment
rasters. See [the Jev experiment](../research/ocr_eval/ADAPTIVE_JEV.md) for actual
recognition results. A nine-image experiment is not a new full-dataset score.
Windows/Linux runtime behavior and local decision providers remain untested.
