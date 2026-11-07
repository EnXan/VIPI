# 0049: Validate provider confidence against OCR reference outcomes

Status: cloud-only research trial completed; no confidence policy adopted,
2026-11-07.

## Context and sources

The OCR recovery pipeline uses decision models to assess transcription
completeness, reviewability and repair choices, then compare correction
candidates. Provider confidence fields and per-option probabilities do not
measure recovered image text directly. The [decision-model review](../research/ocr_eval/reports/DECISION_MODEL_REVIEW_2026-11-07.md)
documents the current provider schemas and cites the OpenAI Decisions guide and
general calibration research. Reference transcripts are available only to
offline evaluation; they must not enter provider requests.

## Decision

Run an initial cloud-only trial on 100 category-stratified entries sampled from
the 578 entries that failed, were unscored, or did not pass the full-reference
criterion in either configuration of the previous 1,113-entry evaluation. Keep
the exact selected keys and their source-report hash in the experiment input.
Split exact image hashes into calibration and held-out evaluation groups before
inference; duplicate catalog entries for one image stay in the same group.

Group native confidence and per-option probabilities by provider, model,
question schema and split. After inference, score the initial OCR against both
80% tolerant word coverage and the full-reference pass. Score comparison
choices against reference-scored candidate/incumbent word counts. Report
reviewability and repair answers descriptively where no direct label exists.
Keep absent confidence values absent. Do not fit a shared cutoff, change
production routing or claim general calibration from this selected development
subset.

## Alternatives and consequences

A universal confidence threshold would assume that different providers and
question schemas assign the same meaning to their scores. No such equivalence
has been established. Fitting or adopting a threshold from this small,
difficulty-selected sample would also risk overfitting to TextOCR-heavy cases.
The trial can show whether the cloud provider's native fields relate to OCR
reference outcomes on these cases; it cannot establish a production-safe
threshold or local-model behavior.

## Validation boundary

The selection contains 100 catalog entries and uses a 79/21 calibration/evaluation
split by image hash. The held-out group is still part of the same development
set and reference sources; TextOCR entries originate from training annotations.
The trial does not rerun local inference and does not evaluate final injection
detection. No calibration method or routing threshold is adopted unless a later
review accepts evidence from a larger held-out set.

See the [measured trial](../research/ocr_eval/reports/DECISION_CLOUD_HARD_100_2026-11-07.md)
and [confidence validation](../research/ocr_eval/reports/DECISION_CONFIDENCE_HARD_100_2026-11-07.md).
