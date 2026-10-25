# 0014: Detection evaluation without scanner context

Status: Accepted following the user's correction.

## Context and sources

The user clarified that the scanner does not currently support context for this
evaluation. Context-dependent misclassifications are expected and intentional.
The workbench must measure that limitation rather than supply the context or
remove contextual cases.
[The catalog](../research/detection_eval/README.md) groups expected injection and
benign labels under each image, with optional context explaining those labels.

This replaces ADR 0013, **Separate OCR and detection evaluation collections**.
That decision introduced independent OCR/detection collections, shared OCR per
image, separate checks using each case's context as `context.task`, confusion
counts, unresolved/error reporting and payload OCR coverage. Its rationale was
to compare context-sensitive labels using the existing scanner's optional
context parameter while avoiding repeated OCR. Inspection of that parameter
was incorrectly treated as support for contextual evaluation. The user's
clarification revises the context assumption and the per-case detection calls;
the collection layout, ground truth and metric definitions remain applicable.
[ADR 0012](0012-hugging-face-evaluation-dataset.md) governs dataset distribution.

## Decision

- Keep `ocr_evaluation` and `detection_evaluation` independent in the browser and
  batch APIs. Requests without a collection retain OCR behavior. Switching
  collections clears selection. Detection categories describe injection,
  benign or context-dependent labels without inferring a source dataset.
- Run OCR and the selected detector checks once per image with empty caller
  context. Neither catalog nor manual workbench context is passed to scanners.
  Reuse that image's saved detector result for every case. Each contextual case
  keeps its exact original label, payload and context for review.
- Require at least one detector for detection evaluation. Payload OCR coverage
  remains separately available in the report. Neither expected labels nor
  payload transcripts become scanner hints.
- Count context-dependent mismatches as ordinary false positives or false
  negatives. Do not hide cases, relabel them, compensate their scores or add
  context support to improve evaluation results.
- Keep true/false positives and negatives, unresolved verdicts, technical errors
  and pending cases overall and per signal. Preserve existing explicit,
  versioned threshold semantics. Any provider failure makes the overall case
  an error; independently successful signals remain evaluable.
- Accuracy is correct / decided cases. Decision rate is decided / completed
  cases, including unresolved results and errors. Pending cases are excluded
  from both denominators; empty denominators have no percentage.
- New reports record `detection_context_mode: "none"` and their actual scanner
  options. Historical results are not rerun or relabeled. The UI identifies
  reports that predate evaluation without context.
- Compare OCR with the catalog's primary visible payload separately. This is
  payload coverage, not a full-image transcript or detection accuracy.

## Alternatives

Passing each case's context would measure a capability outside the user's
current evaluation scope. Filtering contextual cases would conceal the known
limitation. Repeating identical detection calls per case adds provider cost
and introduces varying predictions for the same scanner input. Treating
unresolved verdicts as benign or inventing thresholds changes scoring policy.
An OCR-only run cannot evaluate injection/benign classification; ordinary image
uploads remain available for OCR-only inspection.

## Consequences

Paired contexts can deliberately produce different correctness outcomes for the
same verdict. Metrics count labeled cases, so an image with multiple cases has
multiple contributions. OCR and detector artifacts are shared within an image;
reports preserve all ground-truth cases. Evaluation stays under `research/` and
does not change the public product CLI or add scanner context support.

## Validation boundary

Tests use temporary images and fake providers to verify that both catalog and
manual context are withheld, detection runs once per image, contextual false
positives count normally, failures continue, and saved reports restore without
changing source data. No real detector quality or context support is validated.
