# Adaptive Jev transformation experiment

Run date: 2026-10-31. Native PP-OCRv6 Tiny on CPU, one OCR thread; Jev 1.14.0.

The opt-in `adaptive-jev` profile implements visual plan selection, OCR and visual
review with at most three OCR attempts. All attempts restart from the original.
Jev sees the original and transformed previews, OCR text and grouping; it never
sees reference transcripts, reference boxes or evaluation results. References
are scored only after selection has completed.

The 52 complete plans include eight orientations, 33 color/contrast choices
(including unchanged), and measured central crops with unchanged or channel
difference readings. Already attempted plans are excluded. This follows an
initial axis-based prototype that repeatedly proposed identical plans.

The prior 113-image anchor was replayed without OCR: all texts and v4 scores
matched exactly, with 89/113 passes (78.8%). The new experiment below is a small
development sample and does not establish a new full-dataset pass rate.

| Image | Baseline words | Selected words | Pass | Stop reason |
| --- | ---: | ---: | --- | --- |
| Mirrored / rotated text (`45a827c612a0e43b`) | 1/15 | 1/15 | no | `attempt_limit` |
| Cat / faint overlay (`a67ffa56d853ab52`) | 1/16 | 2/16 | no | `attempt_limit` |
| Beach / faint overlay (`9f49206039aba4ae`) | 0/14 | 0/14 | no | `attempt_limit` |
| Anamorpher blue (`ecf2dcbf78cf982b`) | 6/9 | 7/9 | no | `attempt_limit` |
| Anamorpher orange (`8a7a35692ceaa130`) | 0/6 | 0/6 | no | `attempt_limit` |
| Anamorpher orange, large (`9c9a00ea6e53aaba`) | 0/6 | 0/6 | no | `accept` |
| Dashboard control (`699bfd478f6a1d2b`) | 38/38 | 38/38 | yes | `accept` |
| Receipt control (`aec19a132c3a4ce4`) | 37/37 | 37/37 | yes | `accept` |
| Warehouse control (`98abc9f2dda4289f`) | 14/14 | 14/14 | yes | `accept` |

The six difficult cases remain 0/6 passed. All three passed controls remain
passed. The final selector recovers one additional tolerant reference word in
the cat and blue Anamorpher cases. Other exploratory selector configurations
produced different word counts, including a blue Anamorpher regression, so
selection stability is not established.

The mirrored case requires horizontal reflection plus 180-degree rotation
(equivalent to a vertical reflection). Jev tried rotations without reflection.
For the colored Anamorpher payloads, green-minus-red and blue-minus-red are
available and previously achieved 9/9 and 6/6 tolerant words, respectively,
but Jev did not select them in this final run.

Jev accepted an empty OCR result on the large orange Anamorpher image despite
0/6 reference words. Its accept confidence was 0.56. This is a false acceptance,
not a passed case. Five difficult cases exhausted the three-attempt budget.
The dashboard required a second attempt but ultimately retained the first one.

The final run made 29 Jev requests and 20 OCR attempts. Sum of per-image elapsed
times: 43.35s; median: 5.92s. Reported usage:
456,808 input tokens and 27,116 output tokens. No verified Jev rate is
configured, so monetary cost is unknown. These figures exclude earlier
development runs; their raw artifacts are retained separately.

Only Jev previews are resized/padded to its documented image dimensions
(280–1568 pixels per side). OCR retains full raster resolution. The reduction
can hide small or scaling-dependent text from the decision model.

Validation: 183 unit/integration tests passed and 203 research tests passed
(one optional research test skipped). Ruff, JavaScript syntax and diff checks
passed. The combined all-suites process aborted while importing PyTorch on
macOS; the two separate suite commands used by CI both passed. Nine promoted
filter rasters matched the prior saved images pixel for pixel. The 19 positive
literature filter aliases were also checked against their original operators.

Artifacts are local and ignored by Git:
`.llm-plans/adaptive-jev-2026-10-31/`.
It contains `review.html`, `manifest.json`, `results.json`, individual case
records, all run directories, actual Jev previews, decisions/confidences,
native OCR, grouped text, and test/baseline/filter verification logs.

The current finding is a selector limitation, not evidence that the available
transformations cannot recover these cases. Keep the profile opt-in. Smaller
decision families or direct visual comparisons of candidate transformations
are follow-up concepts requiring joint review; local Clef/d1 tests are pending.

See [ADR 0029](../../adr-code/0029-adaptive-ocr-transformation-review.md) and
[Workbench usage](../workbench/README.md).

## Follow-up diagnosis

The subsequent [controlled Jev diagnosis](JEV_DIAGNOSIS.md) separates context
size, spatial action prediction, direct preview comparison and concrete OCR
verification. It finds useful comparison/verification behavior alongside
unreliable absolute transformation prediction. These diagnostic results do not
replace the initial end-to-end scores above or change the implemented profile.
