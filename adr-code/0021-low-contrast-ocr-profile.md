# 0021: Extend OCR preprocessing for faint text over colored backgrounds

Status: Accepted within the user's requested OCR contrast work; implemented in
PR #14 for review. Recorded on 2026-10-25.

## Context and sources

The user requested low-contrast OCR improvements in the existing OCR PR and
revised the quality goals to a 90% OCR and scanner line, with OCR first.
Small-text crops, mirror transforms and encoded-text fidelity are follow-up
concepts; a second-recognizer comparison is deferred. These goals do not imply
that the current implementation achieves either target.

The completed 113-image detection-evaluation batch
`bbd44ecaa44c448499ea59d04ce0c9e0` contains two poorly recognized translucent
overlays. The beach image's final exact token coverage is 1/17 (5.9%); the cat
image's is 5/19 (26.3%). Its original OCR profile has no native-size CLAHE or
color-derived contrast pass. The dataset is pinned by
[`research/dataset.json`](../research/dataset.json). The evaluator measures
reference coverage, not full-image precision or successful attack detection.

## Replaced decision

This replaces ADR 0007, **Reduced OCR transformation set as the production
default**, accepted on 2026-10-19 after user direction. It selected the fixed
`reduced-transforms-v1` profile: original, optional 2x upscale, eight downscale
readings, 90/180-degree rotations and inverted original, with 13 calls or 12
when the 2x raster would exceed 8 megapixels. It kept model comparisons separate
and added no extra transformation modes. Its rationale was the Round 5
ten-image comparison: 192/205 versus 193/205 matched reference tokens, 129
versus 340 OCR calls, and summed child elapsed time 304.0 versus 670.5 seconds.
That small comparison included a related Anamorpher payload and was not proof
of general accuracy or cross-platform performance. ADR 0007 had replaced ADR
0005's earlier decision to retain the larger schedule pending holdout evidence.

The present revision keeps every existing pass and the existing 8-megapixel
upscale rule. It adds measured contrast observations in response to the user's
new request rather than changing the model or removing downscaling.

## Decision

- Use `reduced-transforms-v2`: the previous schedule plus native-size CLAHE and
  native-size `color-contrast`, in that order. This means 15 passes, or 14 when
  the existing 2x upscale rule applies. Preserve raw images, readings, input
  mappings and their actual profile in artifacts.
- Keep the existing CLAHE parameters (clip limit 2, 8x8 tiles). For color
  contrast, extract HSV saturation, apply morphological black-hat with a 61x61
  elliptical kernel, normalize the response to the uint8 range and invert it
  to present dark strokes on a light background. Convert that derived image
  back to RGB for the existing engine.
- The 61-pixel neighborhood is an application heuristic selected on the two
  development overlays; a 31-pixel alternative was also tested. Its
  purpose is to separate low-saturation strokes from their local colored
  background. It is not a model/protocol requirement or a limit on input size.
  Smaller text and other colors can behave differently. Achromatic text has
  no saturation signal; the original and other passes remain necessary.
- Keep the checksum-pinned OCR model, detector/recognizer thresholds, CLI
  options and detection policy unchanged. Expose the additional filter in the
  existing workbench matrix and effect summary.
- Combine the new observations with assembly version 6, as described in
  [ADR 0020](0020-ocr-assembly-geometry-and-reading-order.md). Contrast can
  fragment a line or join neighboring columns; preserve native word evidence
  while handling those associations before final text is sent to detection.

## Alternatives and tradeoffs

Grayscale, CLAHE alone, RGB channels, saturation polarity, other morphological
neighborhoods, fixed contrast gains and lower text-detector thresholds were
screened on the two development overlays. Better raw recognition did not always
survive assembly. The selected two-pass combination improves final text without
lowering measured reference coverage elsewhere in this suite. It does not solve
the cat example or make the beach payload complete.

The fixed schedule keeps execution and evidence reproducible. An adaptive
selection rule would require a separately evaluated trigger and accounting for
missed fallback opportunities. Replacing the OCR model would confound this
preprocessing comparison. Removing rotation or downscale passes is a separate
quality/runtime decision, even when individual ablations look redundant.

The new profile costs two additional whole-image OCR calls. Native-resolution
calls can cost substantially more than downscaled calls. This is a quality
tradeoff, not a speed improvement. Additional text may contain recognition noise;
coverage does not penalize it, so inspect actual text and duplication as well.

## Validation boundary

The candidate was selected using the two translucent overlays. Both added passes
were then inferred on all 113 suite images using the pinned Medium model on
CPU. Existing 13-pass observations were reused; historical runs and transcripts
were not modified. Raster hashes confirm the experimental preprocessing matches
the production filters. A full fresh 15-pass extraction of each development
image confirms the final beach coverage of 6/17 (35.3%) and unchanged cat
coverage of 5/19 (26.3%).

Compared with the existing PR's assembly-v5/profile-v1 baseline, final reference
coverage improves on three images and declines on none. Matched tokens increase
from 3769 to 3776 out of 4251. Mean per-image coverage changes from 78.3% to
78.7%; complete payloads remain 40/113. The blurred invoice and warehouse board
also improve. Both previously corrected Phantom collages remain complete.

On the separate ten-image Round 5 regression set, new inference for the two
added passes plus replay of frozen prior observations yields 193/205 matched
tokens, versus 192/205 before, with no per-image decline. The set is small and
has been inspected repeatedly; it is a regression check, not a new independent
quality certification. Most other suite images are also not independent of
their scenario variants. Known nonliteral references remain unchanged.

Unit and integration checks cover pixel geometry, source preservation, blank
achromatic contrast, profile counts, word association and effect reporting.
These measurements neither establish 90% OCR reliability nor measure scanner
recall after the OCR changes. No paid detector requests were made. Windows/Linux
OCR inference and a controlled full-pipeline latency comparison remain untested.
Tiny/Small, Tesseract and GPU inference quality were not remeasured.
