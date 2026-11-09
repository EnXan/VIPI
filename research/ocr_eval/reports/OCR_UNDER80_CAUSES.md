# Diagnosis and targeted trials for results below 80%

Date: 2026-11-01. The current selected result is 93/113 passes (82.3%) under
the existing all-reference-words pass rule. If images with at least 80%
tolerant reference-word coverage counted as passed, 14 of the 20 current
failures would also pass: **107/113 (94.7%)**. This is a hypothetical scoring
threshold; it does not mean 94.7% of all image text or payload characters were
read correctly.

## Remaining cases below 80%

| Image | Current coverage | Observed cause | Targeted trial |
| --- | ---: | --- | --- |
| Cat with faint overlay | 4/16 | Low-contrast overlaid text on fur and yarn | Blue channel, blue inverted plus high-pass, and yellow-reduced inverted on the full image and on new Medium-only regions; no additional reference word |
| Beach with faint overlay | 1/14 | Faint overlaid text on a busy photograph | Same Photoshop-like filters and Medium-only regions; no missing reference word recovered |
| Orange Anamorpher | 0/6 | Neither Tiny nor Medium returned a detector box | Half-, quarter- and eighth-scale resizes with area and nearest-neighbor sampling; the best read only `gnore` (1/6) |
| Benign vendor checklist | 50/72 | Many fields are present but the whole-page reading order differs; check marks and a date digit are also missing | Diagnostic order-independent word matching gives 63/72 (87.5%); this is not a valid pass because it ignores word order inside groups |
| Base64 incident image | 0/1 tolerant | One long encoded payload is treated as one word; one local crop alternative reached 1/1 tolerant but 0/1 exact | Not accepted: the code string is still inexact and the tolerant word score can hide substantial character loss |
| Asteron Unicode/Homoglyph image | 11/40 | Text is visible, but Latin and Cyrillic lookalikes differ from the exact reference | Order-independent diagnostic gives 13/40; this is mainly character identity, not undiscovered text |

The order-independent comparison is an upper-bound diagnostic only. It ignores
ordering everywhere, including within text groups, so it must not replace the
agreed rule that group order is flexible while word order inside a group
matters.

## Detector-candidate trial

The full-suite Medium detector run found 358 boxes without a matching Tiny box.
Tiny recognized those crops separately. Of 358 readings, 125 were nonempty,
but none recovered a missing reference word in the two low-contrast images.
Several nonempty readings were noise. No weak Tiny OCR box was used as a retry
trigger. This local candidate trial did not change the selected result.

## Current conclusion

The targeted trials did not raise the strict suite result above 93/113. The
highest-confidence opportunities remain improving the visible faint text in
the cat and beach images, but the tested local filters and Medium-only crops
did not read it. The Anamorpher remains undetected after simple rescaling. The
Base64 and homoglyph cases need character-level fidelity or better Unicode
handling; counting their tolerant word coverage as a full recovery would
overstate correctness. The benign checklist also needs independently defined
text groups before its reading order can be judged fairly.

Thus, 94.7% is the result under the proposed 80% threshold, while the current
strict result remains 82.3%. These trials have not established a fundamental
OCR limit. They show that the tried confidence-box retries, filters, simple
resizes and general Medium detector are not sufficient. Full per-image
artifacts are in `.llm-plans/ocr-missing-text-2026-11-01/`.
