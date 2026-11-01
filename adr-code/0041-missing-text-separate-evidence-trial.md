# 0041: Trial missing-text probes and separate OCR evidence

Status: Research trial, 2026-11-01.

## Context and decision

The user prioritized wholly missed text and large gaps above ordinary character
errors and requested testing spatial detection of gaps, targeted re-recognition,
separate alternative readings, and special scrutiny for code-like text. In
research only, compare original-coordinate OCR boxes from the existing 2x
probes, retry newly uncovered candidate lines with two local transforms,
preserve distinct whole-page and crop readings with provenance, and report
long code-like disagreements separately. Do not feed references into signal or
selection decisions, concatenate alternatives, or modify the public detector.
The signal thresholds are exploratory, not input limits or calibrated defaults.

## Findings and boundary

The full 113-image comparison retained 93 primary OCR reference passes. The
missing-box signal operated on 27 already-probed images, flagged eight, and
left 86 explicitly unprobed. Eighty-six localized OCR calls produced six
nonempty readings. An additional code-disagreement signal marked one of 12
comparable images; four targeted calls produced two nonempty observations.
Separate alternatives did not change any local Prompt Guard verdict under a
fixed experimental threshold; 53 context-dependent cases have no caller context
and must not be scored as unambiguous truth. A Base64 alternative passes the
tolerant reference but not the exact reference. Detailed findings, cost and
limitations are in [OCR_MISSING_TEXT_EXPERIMENT.md](../research/ocr_eval/OCR_MISSING_TEXT_EXPERIMENT.md).

Do not adopt these prototypes as production routing or claim improved attack
recall. The data is a reused development suite, the compared OCR probes are
selective, and lack of a detected signal does not establish complete image text.
