# Gated OCR corrections

Historical gated-correction experiments, 2026-11-01. The selected product
workflow now includes the full 95/113 recovery chain; see
[Product OCR recovery](../../../docs/ocr-recovery.md) and
[ADR 0044](../../../adr-code/0044-product-research-recovery.md). The 92/113 results
below describe a later incomplete combination, not the promoted pipeline.

## Historical gated flow and cost policy

1. Recognize the original once.
2. Ask one image/OCR assessment question: ready, orientation, contrast or uncertain.
3. Ready nonempty OCR stops immediately. Uncertain nonempty OCR retains the original.
4. Orientation corrections compare eight rendered previews in one request and
   recognize only the selected correction; compare its real OCR with the original.
5. Contrast corrections try green-minus-red, saturation-inverted, then
   saturation-clahe sequentially. Stop at the first model-judged improvement.
   Empty or identical transcriptions skip model comparison. Each transform
   starts independently from the original image.
6. For images over 2000 pixels on either side, or with a selected OCR box at
   confidence ≥0.8 and height under 12 input pixels, run 1024-pixel local OCR
   tiles at 896-pixel strides when spatial OCR boxes are available. Assemble
   tile readings with the selected result; use the candidate only if it
   preserves the selected result's full word-token multiset. This guard uses
   OCR text, not reference text.

Original empty OCR always triggers the three local contrast probes as needed,
even when the gate says ready, because earlier probes showed false text-absence
judgments. If all remain empty, retain the original with no_verified_improvement;
only the assessment call was needed. Genuinely text-free inputs remain untested.

Normal ready images cost one OCR and one decision request. The contrast route
has at most four OCR and four logical requests, stopping earlier where possible.
The orientation route has at most two OCR and three logical requests. Transport
retries may add physical requests. No reference answers enter the assessment,
orientation selection or pair comparison. No calibrated confidence cutoff is used.

## Same nine-image rerun

| Image | Prior exhaustive selection | Gated selection | OCR calls | Decision calls |
| --- | ---: | ---: | ---: | ---: |
| Mirror / rotated | 5/15 | 15/15 | 2 | 3 |
| Cat | 4/16 | 4/16 | 3 | 2 |
| Beach | 3/14 | 1/14 | 3 | 2 |
| Anamorpher blue | 9/9 | 9/9 | 2 | 2 |
| Anamorpher orange | 6/6 | 6/6 | 2 | 2 |
| Anamorpher orange, large | 0/6 | 0/6 | 4 | 1 |
| Dashboard | 38/38 | 38/38 | 1 | 1 |
| Receipt | 37/37 | 37/37 | 1 | 1 |
| Warehouse | 14/14 | 14/14 | 1 | 1 |

All nine cases completed. The three passed controls were each assessed ready
and stopped after exactly one OCR and one decision call. This demonstrates the
intended fast path on these controls, not a general routing-accuracy estimate.
Four difficult originals were explicitly flagged for correction (orientation
once, contrast three times). The two empty originals with ready assessments
were also locally challenged: beach and large orange. The large orange image
remains unrecovered.

Selected passes changed from 5/9 to 6/9 in this deliberately difficult sample;
matched reference words changed from 116/155 to 124/155. The original-only
sample has 3/9 passes and 97/155 matched words. At the time of this nine-image
report, the latest full-suite result was 89/113; this small rerun did not
measure a new full-dataset rate.

Mirror now uses rendered-preview orientation selection to choose mirror-180,
then confirms its 15/15 OCR against the original. It no longer runs the long
sequential tournament that previously retained mirror-0's 5/15 reading.
For blue and orange, the first raw green-minus-red candidate is sufficient.
Beach stops after a small improvement from saturation-inverted, missing the
3/14 reading from the later saturation-clahe candidate. This is an observed
quality tradeoff of early exit. The request count reduction and quality changes
come from the combined gate, routing and early-exit policy; their individual
effects were not isolated experimentally.

## Measured resource use

| Metric, nine images | Exhaustive shortlist run | Gated run |
| --- | ---: | ---: |
| Native OCR observations | 126 | 19 |
| Decision requests | 117 | 15 |
| Reported input tokens | 522,815 | 33,057 |
| Configured API estimate | $0.0523 | $0.00331 |
| Sum of image durations | 172.7 s | 27.5 s |
| Time inside OCR calls | 41.2 s | 7.0 s |

These are single-run observations using the existing local machine and hosted
decision API. They include per-image setup, but exclude previous experiments,
test runs and local electricity/hardware cost. API estimates use the configured
input-token rate and are not invoices. They do not establish local decision-model
latency or production throughput.

## Complete 113-image run with tile recovery

The current combined pipeline was evaluated on all 113 catalog images. Decisions
ran first; local tiles then ran only for signal-positive images. The Decisions
responses were fresh for this run, and the tile stage used those selected
outputs without repeating the API calls.

| Variant | Strict passes | Tolerant words | Exact words | API requests | Estimated API cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Composite research candidate with recorded Decisions and local recovery | 95/113 | 4052/4175 | 3808/4175 | 73 historical requests | $0.0343504 configured estimate |
| Decisions adaptive, without tile recovery | 92/113 | 4031/4175 | 3787/4175 | 137 | $0.0306473 |
| Decisions adaptive plus local tile recovery | 92/113 | 4038/4175 | 3794/4175 | 137; 190 additional local OCR calls | $0.0306473 |
| Jev adaptive, separately run without tile recovery | 92/113 | 4030/4175 | 3786/4175 | 136 logical; 167 HTTP attempts | Unknown; no verified Jev rate |

The tile signal fired on 32 images and selected the tile-assembled candidate on
13. Its cumulative measured OCR time was 73.7 seconds. It added seven tolerant
and exact reference matches over Decisions alone, but did not raise the strict
pass count. Compared with the local-only candidate, the 92/113 combination has
three regressions and no new passes. Therefore this promotion records the
then-selected research workflow, subsequently superseded; it does not claim a measured pass-rate gain.
The Decisions transport retries transient 429/5xx and connection failures up to
three attempts with backoff; this Decisions run had zero retry events. The Jev
run had 27 retry events, all following HTTP 503 responses.

## Validation boundary

Research tests: 207 passed, 1 skipped; Ruff passed. Coverage includes the exact
one-OCR/one-gate ready path, early exit after improvement, independent source
transforms, original retention, one selected orientation OCR, skipping empty
comparisons, persistence and request mapping. No API reference leakage is used:
reference scoring happens after final selection.

Artifacts: local ignored `.llm-plans/gated-ocr-2026-11-01/`, with native outputs,
actual previews, questions, responses, timing, usage and reference comparisons.
Model routing can still miss nonempty-text defects. Broader datasets, genuinely
text-free controls, Windows/Linux and local decision providers remain unverified.
