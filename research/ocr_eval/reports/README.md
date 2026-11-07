# OCR reports

Current measured product run: [1,113-entry local/cloud benchmark](PRODUCT_OCR_1113_2026-11-02.md),
[per-image JSON and provenance](PRODUCT_OCR_1113_2026-11-02.json), and
[protocol and limitations](../../../docs/ocr-benchmark.md).

Focused case analysis: [book-spine OCR diagnosis](BOOK_SPINE_DIAGNOSIS_2026-11-02.md).

Direct model diagnostic: [33-image Luna-only comparison](LUNA_ONLY_33_2026-11-07.md)
and [raw responses, references and comparable text-only scores](LUNA_ONLY_33_2026-11-07.json).

Research review: [decision models and proposed recovery experiments](DECISION_MODEL_REVIEW_2026-11-07.md).
These proposals have not changed production behavior or established a quality gain.

Scoped point-4 trial: [100 difficult cloud cases and OCR metrics](DECISION_CLOUD_HARD_100_2026-11-07.md),
[provider confidence and reference validation](DECISION_CONFIDENCE_HARD_100_2026-11-07.md),
and the [reproducible 100-entry selection](../experiments/DECISION_CONFIDENCE_HARD_100.json).
The trial does not rerun local inference or establish a production confidence threshold.

## Historical development trials

These reports retain the measured protocols, results and limitations of the
development trials. They do not describe the current scanner by default.
See [product recovery](../../../docs/ocr-recovery.md) for the selected workflow,
[the evaluation guide](../README.md) for current metrics and
[the baseline protocol](../BASELINE.md) for comparison models.

Retained trial operators live in `research.ocr_eval.experiments`; evaluation
metrics and catalog handling live in `research.ocr_eval.evaluation`.

| Report |
| --- |
| [Adaptive Jev transformation experiment](ADAPTIVE_JEV.md) |
| [Expanded priority-cascade signal experiment](EXTENDED_OCR_SIGNALS.md) |
| [Gated OCR corrections](GATED_OCR.md) |
| [Jev diagnosis: perception, operation prediction and OCR review](JEV_DIAGNOSIS.md) |
| [Ambiguous-character line retry experiment](OCR_AMBIGUOUS_LINE.md) |
| [Group-wise OCR reading comparison](OCR_GROUP_MERGE.md) |
| [Layout-specific correction route](OCR_LAYOUT_ROUTE.md) |
| [PP-OCRv6 Medium detector benchmark](OCR_MEDIUM_DETECTOR.md) |
| [Missing-text and separate-evidence experiments](OCR_MISSING_TEXT_EXPERIMENT.md) |
| [OCR-first candidate comparison experiment](OCR_PAIR_COMPARISON.md) |
| [Raw detector and empty-region retry experiment](OCR_RAW_DETECTOR_EXPERIMENT.md) |
| [Local retries and guarded upscaling experiments](OCR_REGION_UPSCALE_EXPERIMENTS.md) |
| [Local missing-letter correction from a resolution probe](OCR_RESOLUTION_INSERTIONS.md) |
| [Local OCR signal experiment](OCR_SIGNAL_ARCHITECTURES.md) |
| [Signal-informed OCR assessment experiment](OCR_SIGNAL_CONTEXT.md) |
| [Signal-gated OCR correction comparison](OCR_SIGNAL_END_TO_END.md) |
| [OCR signal threshold sweep](OCR_SIGNAL_THRESHOLD_SWEEP.md) |
| [Diagnosis and targeted trials for results below 80%](OCR_UNDER80_CAUSES.md) |
