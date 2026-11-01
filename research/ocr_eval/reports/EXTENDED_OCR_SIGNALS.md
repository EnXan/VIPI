# Expanded priority-cascade signal experiment

For the subsequent 113-image threshold sweep and reserved comparison, see
[OCR_SIGNAL_THRESHOLD_SWEEP.md](OCR_SIGNAL_THRESHOLD_SWEEP.md).

The maintainer chose the priority cascade for continued research. This
experiment adds regional confidence, small detected text, unusual symbol
proportion, overlapping text groups and contrast inside detected OCR boxes.
It is still a replay of stored original OCR, not an active adaptive pipeline
change, correction run or external model request. The existing dictionary,
empty/short-text and aggregate confidence signals remain in place.

The research-only code is `evaluation/extended_signals.py`. Signal order is:
empty text, short text, aggregate low confidence, regional low confidence,
small text, unusual symbols, overlapping groups, regional contrast, then
unknown words. The first triggered signal ends the cascade. All new thresholds
were frozen before running the comparison and are hypotheses, not defaults:

| Signal | Exploratory trigger | Limitation |
| --- | --- | --- |
| Regional confidence | Any word/region with at least three characters and confidence below 0.5 | Scores depend on the OCR engine and can be low even for a correct reading. |
| Small text | Any eligible box under 12 pixels tall | Box height alone does not establish recognizer downscaling or a defect. |
| Unusual symbols | At least 35% punctuation/symbols among eight or more non-space characters | Code, equations, identifiers and some languages can legitimately trigger it. |
| Group overlap | Boxes overlap by at least half of the smaller group's area | Overlapping groups can be legitimate or artifacts of grouping; neither proves a missed payload. |
| Regional contrast | The 95th minus 5th grayscale percentiles in an eligible detected box are under 25 on a 0–255 scale | Only detects weak contrast within boxes already found; colored text and backgrounds can mislead grayscale measurements. |

Missing eligible boxes, confidences, images or insufficient text are recorded
as unavailable. One valid group cannot overlap a second group and is clear for
that particular check. Missing evidence does not establish image completeness.
These are review signals, never statements about whether content is malicious.

## Results on the same 30 development images

The sample remains deliberately balanced: 15 baseline reference failures and
15 passes. The original cascade marked 7 failures and 3 passes; the expanded
cascade marked **11 failures and 9 passes**. Four baseline failures remained
without a triggered signal. There were no unresolved routes on these inputs.
The additional four failures are three with overlapping groups and one with a
low-confidence region; these associations do not prove that a transformation
would fix them. Six extra passing references were also marked for review.

Each additional signal was separately evaluated on all 30 cases for diagnosis,
even when the actual cascade would have already stopped:

| Signal | Failed references marked (of 15) | Passed references marked (of 15) | Unavailable (of 30) |
| --- | ---: | ---: | ---: |
| Regional low confidence | 5 | 7 | 2 |
| Small text | 0 | 0 | 2 |
| Unusual symbols | 0 | 0 | 2 |
| Group overlap | 3 | 3 | 2 |
| Regional low contrast | 2 | 0 | 2 |

Counts overlap and must not be added. For example, dashboard's correctly
recognized `SLO` has confidence 0.46219; the previously passed warehouse case
contains `R-418` with confidence 0.44479. Both therefore trigger the new
regional rule. In `data_ingest_flow.png`, `partition` was read as `partion`,
but no signal triggered. This illustrates both over-triggering and missed
errors. The contrast result is promising only as a small exploratory finding:
both cases were already flagged earlier in the cascade.

The 30-image labels assess approved payload reference text rather than all
image text. This reused development set is not a held-out population sample;
these results are not OCR pass rates, costs after correction, or attack
detection rates. Detailed selection, first-trigger evidence and individual
diagnostics are in `.llm-plans/ocr-extended-signals-2026-11-01/`. No new
runtime or memory comparison has been made.

## Not available from this replay

Detection-versus-recognition mismatch requires rejected detector boxes, which
are not present in these saved artifacts. A cheap-probe disagreement requires
a second OCR pass. Orientation detection needs a tested local classifier;
small-box height does not expose recognizer resize metadata. Blur and
compression need separately validated regional measurements. Script/language
uncertainty and rare-word frequency need language- and domain-aware evaluation;
the existing multilingual unknown-word lookup is not a universal language
signal. None of these is claimed as implemented or clear, and none should be
invented from the reference labels. Further work needs appropriate input data
and a separate evaluation before routing can rely on them.
