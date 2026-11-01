# Adaptive Jev transformation experiment

Latest implementation and results: [Gated OCR corrections](GATED_OCR.md).
The sections below retain the earlier experimental runs.

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

The first selector run found that direct transformation prediction was
unreliable. At the time, the profile remained opt-in; the OCR-first
preview-selection pilot below tests the next architecture iteration. The
current Research Workbench default is recorded in
[ADR 0044](../../../adr-code/0044-product-research-recovery.md). Local Clef/d1
tests were pending at the time of the historical experiment.

See [Workbench usage](../../workbench/README.md).

## Follow-up diagnosis

The subsequent [controlled Jev diagnosis](JEV_DIAGNOSIS.md) separates context
size, spatial action prediction, direct preview comparison and concrete OCR
verification. It finds useful comparison/verification behavior alongside
unreliable absolute transformation prediction. These diagnostic results do not
replace the initial end-to-end scores above or change the implemented profile.

## OCR-first preview-selection pilot (2026-11-01)

The profile now runs OCR on the original first. Jev reviews the original image,
the actual OCR result and groups. It answers separate questions about text
presence and per-attempt completeness; code derives whether to accept, retry or
report uncertainty. A retry selects a correction family and compares locally rendered previews.
Contrast candidates are compared within seven named operator groups, then the
group winners are compared once more. Together the groups include all 31
non-unchanged contrast filters. Selection previews are 512-pixel JPEGs; OCR
still receives the full-resolution transformed raster. Sending all contrast
previews as PNG exceeded the observed 33,554,432-byte request limit; sending
them as JPEG exceeded the provider token limit. Staged comparisons address
both constraints while retaining every filter in the search space.

The first OCR-first pilot completed five cases before Jev returned HTTP
503 (`Image processing is unavailable`) for four: cat/faint overlay,
beach/faint overlay, blue Anamorpher and orange Anamorpher. No reference or
evaluation data was sent. Completed results:

| Image | Baseline words | New result | Pass |
| --- | ---: | ---: | --- |
| Mirrored / rotated text | 1/15 | 15/15 | yes |
| Large orange Anamorpher | 0/6 | 0/6 | no |
| Dashboard control | 38/38 | 38/38 | yes |
| Receipt control | 37/37 | 37/37 | yes |
| Warehouse control | 14/14 | 14/14 | yes |

The four HTTP 503 cases are incomplete observations, not OCR failures. In a
focused check of the large orange image, Jev answered `no` for text presence
despite empty OCR and a 0/6 reference score. A follow-up preview-selection
request then returned HTTP 503 before another OCR attempt. This showed that
Jev's no-text answer cannot prove the image is text-free. The current code
therefore challenges empty OCR with transformations and ends uncertain if it
remains empty. The earlier table's `accept` for that image is not a pass.
The 78.8% anchor is unchanged; these partial observations do not establish a
new aggregate rate.

Validation: `tests/research` passed (209 passed, 1 skipped); Ruff passed. The
external pilot is partial due to repeated provider 503 responses. Artifacts are
local and ignored under `.llm-plans/adaptive-jev-2026-11-01/`.

## Temporary OpenAI Decisions API run (2026-11-01)

After repeated TypeSafe HTTP 503 responses, the maintainer requested temporarily
using OpenAI Decisions for the same opt-in profile. The adapter uses
`gpt-6-luna`, inline JPEG previews and the existing OCR-first, per-attempt
review and grouped preview-selection flow. The [official API guide](https://developers.openai.com/api/docs/guides/decisions)
documents image input, typed `choice` answers and `gpt-6-luna` as the currently
supported model. The profile's internal ID remains `adaptive-jev` for this
temporary experiment; the workbench labels it Decisions API.

All nine permitted images completed. Results compared with the unchanged
78.8%-baseline references:

| Image | Baseline words | Decisions result | Pass |
| --- | ---: | ---: | --- |
| Mirrored / rotated text | 1/15 | 15/15 | yes |
| Cat / faint overlay | 1/16 | 2/16 | no |
| Beach / faint overlay | 0/14 | 0/14 | no |
| Anamorpher blue | 6/9 | 3/9 | no |
| Anamorpher orange | 0/6 | 4/6 | no |
| Anamorpher orange, large | 0/6 | 0/6 | no; uncertain |
| Dashboard control | 38/38 | 38/38 | yes |
| Receipt control | 37/37 | 37/37 | yes |
| Warehouse control | 14/14 | 14/14 | yes |

The aggregate changed from 3/9 to 4/9 passed images, and word matches changed
from 97/155 to 113/155. The mirror case is the clear recovery. Decisions also
recovered four words from the orange Anamorpher, while the blue Anamorpher lost
three matches. All controls remained passed. The large orange image ended
uncertain after three empty OCR results, avoiding Jev's prior false acceptance.
The result remains a small sample and does not establish the full dataset's
rate.

The run made 134 Decisions requests with 269,630 input tokens. Estimated API
cost is about $0.027 using the repository's current input-token rate; this is
not an account invoice. Artifacts are local under
`.llm-plans/adaptive-decisions-2026-11-01/`.
