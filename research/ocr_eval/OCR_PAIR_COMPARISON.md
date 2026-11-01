# OCR-first candidate comparison experiment

Historical exhaustive run; current implementation: [Gated OCR corrections](GATED_OCR.md).

Date: 2026-11-01. This run used the then-opt-in research profile `adaptive-jev`,
temporarily using OpenAI Decisions with `gpt-6-luna`. The current default is
recorded in [ADR 0044](../../adr-code/0044-product-research-recovery.md).

## Protocol

Recognize a fixed shortlist locally before making any decision request:
the unchanged image, seven further rotations/reflections, raw green-minus-red
and blue-minus-red, their normalized inverted counterparts, saturation-inverted
and saturation-clahe. Thus each image produces 14 native PP-OCRv6 Tiny readings
with PDFMiner grouping. These are measured development candidates, not a
validated universal transform pool. Compound orientation/color transformations
and central crops are outside this experiment.

Starting with the original, compare each candidate with the incumbent using
their actual OCR texts, groups, image previews and OCR-derived text-region
crops. Source context and crops can reach 1568 pixels; full variant thumbnails
use 512 pixels. Crop padding equals the tallest detected text-region height.
Whole-image context is retained because detected-region crops can miss text.

The fixed choices are improved, equivalent, worse and uncertain. Only improved
replaces the incumbent. All readings and requests remain saved. References and
scores are used only after selection. This replaces the previous three-attempt
budget with the fixed shortlist; it does not run image-family selection first.
`selection.accepted` means model-judged improvement, not complete transcription.

## Results

The same nine authorized development images completed without API failures.
Prior results are from the previous Decisions preview-selection run.

| Image | Original baseline | Prior selected | New selected | Best available in new shortlist |
| --- | ---: | ---: | ---: | ---: |
| Mirror / rotated | 1/15 | 15/15 | 5/15 | 15/15 |
| Cat | 1/16 | 2/16 | 4/16 | 4/16 |
| Beach | 0/14 | 0/14 | 3/14 | 3/14 |
| Anamorpher blue | 6/9 | 3/9 | 9/9 | 9/9 |
| Anamorpher orange | 0/6 | 4/6 | 6/6 | 6/6 |
| Anamorpher orange, large | 0/6 | 0/6 | 0/6 | 0/6 |
| Dashboard | 38/38 | 38/38 | 38/38 | 38/38 |
| Receipt | 37/37 | 37/37 | 37/37 | 37/37 |
| Warehouse | 14/14 | 14/14 | 14/14 | 14/14 |

Selected passes increased from 4/9 in the prior selector to 5/9, versus 3/9
for original-only OCR in this sample. Matched reference words increased from
113/155 to 116/155 (original-only: 97/155). Six images have a passing reading
somewhere in the new shortlist; this is an offline ceiling, not a selection
result. The full 113-image baseline remains 89/113; no new full-dataset rate
was measured.

## Findings and limitations

Running OCR before comparison recovers the known successful channel-difference
readings for blue and orange Anamorpher. The blue result selects raw
green-minus-red at 9/9. The orange result selects saturation-inverted at 6/6;
several channel-difference readings also achieve 6/6. Cat and beach improve
partially. All large orange readings remain empty, so the original is retained
with no_verified_improvement. Its current limit is candidate OCR recovery, not
the model's choice among recovered text.

Mirror is the concrete selector regression: mirror-0 produces 5/15 and is
judged better than the original. Later mirror-180 produces the correct 15/15
reading, but Luna labels it worse than the 5/15 incumbent. Both OCR outputs and
their actual transformed images were supplied. Thus a passing reading exists
and is rejected; preserving the original and offering uncertainty does not
guarantee selection of the best candidate. Source anchoring, text-group order
and sequential comparison order are possible factors, not isolated causes.
For the remaining eight images, selected reference coverage equals the best
available coverage, including ties.

The three controls retain their original OCR with no_verified_improvement.
This relative comparison avoids requiring whole-image completeness before
stopping. The benchmark still measures the catalog reference payload, not a
verified full-image transcript. No truly text-free control or held-out dataset
was tested. Sequential comparisons remain order dependent, and 14 local OCR
passes cost more computation than the former two or three attempts.

## Validation and artifacts

Research tests: 205 passed, 1 skipped; Ruff passed. Tests cover OCR preceding all
model calls, independent source transforms, incumbent retention for equivalent,
worse and uncertain answers, empty OCR, failure persistence and image/text
request mapping. Windows/Linux execution remains unverified.

The run used 126 OCR observations and 117 Decisions requests, reporting 522,815
input tokens. The configured input-token estimate is $0.0523, not an invoice.
Summed per-image durations were 172.7 seconds, including 41.2 seconds inside
native OCR calls. These numbers exclude tests and previous experiments.

Local ignored artifacts: `.llm-plans/ocr-pair-comparison-2026-11-01/`, including
results, native outputs, all candidate rasters, comparisons, actual model
previews and costs. No automatic optimization beyond this concept is implied.
