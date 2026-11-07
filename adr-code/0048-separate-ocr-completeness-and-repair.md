# 0048: Separate OCR completeness from repair selection

Status: accepted for implementation, 2026-11-07.

## Context

The initial OCR recovery decision combined two questions in one answer: whether
the OCR was usable and which image transformation to try. This could interpret
an unclear view as evidence of completeness, and it could not express both
missing text and insufficient visual detail independently. The product OCR
recovery workflow is recorded in [ADR 0044](0044-product-research-recovery.md).

## Decision

For existing signal-triggered visual assessments, ask three separately named
choice questions in the same model request:

- Does the OCR appear to contain all legible visible text?
- Does the supplied image detail support judging completeness across the image?
- Which correction, if any, is supported: orientation, contrast, both, none or
  uncertain?

Derive routing in ordinary code. Mark the original ready only when completeness
is judged, review detail is sufficient and no repair is supported. Missing or
uncertain completeness, insufficient detail and unsupported repairs never imply
a complete OCR result. A missing transcript with a supported correction may be
reprocessed; empty OCR continues to trigger the existing contrast probes.
Orientation and contrast corrections can be combined from the original image.

Do not ask the model for an ungrounded numeric coverage percentage or introduce
a confidence cutoff. Preserve the three answers in run data. Existing signal
routing remains unchanged: if no signal triggers a visual assessment, record
that assessment was not required, not that completeness was verified.

## Alternatives and consequences

Keeping a single combined answer preserves fewer fields but conflates whether
text is missing with whether a particular repair can recover it. Asking each
question in a separate API request increases latency and fees without needing
independent image evidence, so the questions share one request and one image.
The model's categorical completeness judgment is still fallible and does not
replace evaluation against annotated references.

## Validation boundary

Offline tests verify that the three answers are required, that uncertainty or
insufficient detail cannot mark the original ready, and that combined repairs
are applied to one source view. No live provider comparison or full-image
completeness validation has been run; the existing signal gate can skip the
assessment for images with no detected signal.
