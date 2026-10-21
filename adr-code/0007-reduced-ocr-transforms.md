# ADR 0007: Reduced OCR transformation set as the production default

Status: Accepted on 2026-10-19 after explicit user direction.

## Superseded decision

ADR 0005 kept the existing fixed OCR transformation sequence because the early
screening rounds used development images only and did not establish that a
reduced profile would retain recognition quality on unseen content. That
precaution was justified by the absence of a holdout result. Round 5 later
validated the frozen candidate on ten previously unseen, source-stratified
images, after which the user explicitly directed that the candidate become the
production default. ADR 0005 is superseded by this record.

## Context and sources

The production pipeline previously OCRed all generated whole-image views and
tiles with five filters each. Research Round 5 compared a frozen 13-pass
candidate with a 34-pass control on ten holdout images from all six OCR sources.
The candidate had 192/205 matched reference tokens (93.7%) versus 193/205
(94.1%) for the control, and 129 OCR calls versus 340. Summed per-image child
elapsed time was 304.0 seconds versus 670.5 seconds; this is not an end-to-end
scan wall-clock comparison. The measurements and limitations are recorded in
[the screening report](../research/experiments/ocr/README.md).

## Decision

Use the frozen `reduced-transforms-v1` profile as the single production default. It runs
these passes in order: unchanged original; Pillow Bicubic 2×; Pillow Nearest
0.5×; OpenCV Bicubic 0.5×; OpenCV Nearest, Pillow Nearest, OpenCV Linear Exact
and OpenCV Bicubic at 0.25×; 90° and 180° rotations; inverted original; grayscale
OpenCV Nearest 0.125×; and Pillow Nearest 0.125×. Skip only the 2× pass when its
output raster would exceed 8 megapixels. Runs record the profile ID and actual
pass count. The 8-megapixel threshold is part of the tested candidate; keeping
it preserves that evaluated profile. Images above it skip one potentially useful
upscale reading, while always running that pass would change the tested profile
and needs a fresh validation.

Do not add `Deep`, `Balanced` or `Fast` modes in this change. Each mode would
need its own predeclared pass set and measured quality/runtime tradeoff. OCR
engine/model comparisons are also separate research work; this decision keeps
the pinned PP-OCRv6 model unchanged.

## Alternatives

- Keep the previous sequence pending a larger holdout. This avoids adopting a
  candidate with a 0.4 percentage-point lower measured token coverage, but keeps
  its much higher OCR workload.
- Add modes immediately. That requires selecting and validating additional
  profiles; Round 5 only tests one candidate.
- Change OCR models at the same time. That would confound the transformation
  comparison and lacks a paired evaluation in the available results.

## Consequences

The production schedule reduces OCR work substantially for common images and
forgoes some transforms that could help rare inputs. In this small holdout, the
candidate missed one more reference token overall; the two profiles tied on the
final assembled coverage for eight of ten images. The result supports the
requested operational tradeoff but does not establish equal accuracy across
all image types, hardware, or OCR engines. Future profile or model changes need
paired evaluation on content groups not used to select them.

## Validation boundary

Round 5 used ten images, including one Anamorpher variant whose payload group
also appeared in development; it was not an independent payload replicate.
Reference coverage is not a complete image transcript. Runtime figures sum
fresh per-image child process measurements including model initialization,
transforms, OCR and image saving, with final assembly measured separately.
Production adoption does not imply that Linux or Windows performance has been
measured.
