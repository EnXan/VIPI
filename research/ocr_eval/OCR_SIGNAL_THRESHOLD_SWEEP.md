# OCR signal threshold sweep

This research comparison tests thresholds on stored original PP-OCRv6 Tiny
results. It does not change the active adaptive OCR profile, run transformations
or issue model requests. The labels are baseline payload-reference passes and
failures; neither a marked pass nor an unmarked failure is a ground-truth
image-wide security classification.

## Protocol

The same previously fixed 30 development cases (15 failed and 15 passed) were
used for threshold selection. The other 83 of the 113 verified cases were
reserved until the configurations were selected; they contain 9 failed and 74
passed references. Some images have appeared in earlier project investigations,
so this is a reserved comparison, not a fully blind external test.

Other signal definitions and thresholds from the extended experiment were
held fixed. Three rounds tested: regional confidence alone, group overlap alone,
then their joint grid. For regional confidence, the candidates were disabled
or thresholds below 0.15, 0.25, 0.35, 0.4, 0.5 and 0.6. For group overlap,
they were disabled or at least 0.5, 0.75, 0.9 and 1.0 of the smaller group's
area. The resulting joint grid has 35 combinations. In this comparison,
disabled signals do not contribute either triggers or missing-evidence states.

Two illustrative operating points were selected using only the development
set: maximize marked failures while routing at most 3 of 15 passing references
for the conservative point, or at most 6 of 15 for the balanced point; ties
favor fewer passing references marked, then deterministic candidate order.
These 20% and 40% development budgets explore tradeoffs; they are not user
requirements or limits on processing. The prior extended cascade is retained
as a comparator. The exact protocol, complete sweep, feature records and
verification are in `.llm-plans/ocr-threshold-sweep-2026-11-01/`.

## Results

| Configuration | Development failures marked | Development passes marked | Reserved failures marked | Reserved passes marked | Reserved unresolved |
| --- | ---: | ---: | ---: | ---: | ---: |
| Previous: region < 0.5, overlap ≥ 0.5 | 11/15 | 9/15 | 8/9 | 24/74 | 0 |
| Conservative: both new signals disabled | 7/15 | 3/15 | 4/9 | 6/74 | 4 (1 fail, 3 pass) |
| Balanced: region disabled, overlap ≥ 0.5 | 10/15 | 5/15 | 6/9 | 10/74 | 2 (both pass) |

On reserved cases, the balanced configuration marks 66.7% of the nine known
reference failures and 13.5% of the 74 passing references. The earlier
configuration marks 88.9% and 32.4%, respectively. These are descriptive
sample proportions with very small failure counts, not deployment estimates.
Unresolved inputs are reported separately, not silently treated as clear. If
all unresolved inputs are reviewed, that implies two more reviews in the
balanced reserved sample; the actual downstream policy has not been selected.

On the development sample, region thresholds at or below 0.25 did not mark any
additional failures compared with leaving that signal disabled; below 0.5 it
marked one additional failure but five additional passes. Overlap at 0.5 marked
three additional failures and two additional passes; higher overlap thresholds
did not retain those additional failures. These are associations with the
current reference labels, not proof of how grouping or OCR should be repaired.

`BALANCED_EXPERIMENTAL_PARAMETERS` in `evaluation/extended_signals.py` makes the
balanced candidate reproducible: it disables the single-region confidence
trigger, retains 0.5 group overlap and leaves the other experimental thresholds
unchanged. It is opt-in research configuration, not the function default or a
production recommendation. A direct rerun of the actual cascade on all 113
stored results reproduced all selected-candidate routes from the sweep.

## Boundaries

High-confidence wrong OCR and undetected image regions can evade all signals.
Payload references do not cover all visible text, and failures do not imply
that a transformation can fix them. No new image OCR, correction success,
latency, memory, model call count, language coverage or live traffic was
measured. The selection cannot justify a production gate without new external
images, more failed cases, separate local/cloud backend calibration and
end-to-end correction and cost measurements.
