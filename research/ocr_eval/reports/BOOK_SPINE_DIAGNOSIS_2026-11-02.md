# Book-spine OCR diagnosis, 2 November 2026

This is a single-image investigation of `94939c68120f8ae9`, the photographed
Harry Potter boxed set in the TextOCR selection. It does not replace or change
the [1,113-entry benchmark](PRODUCT_OCR_1113_2026-11-02.md).

Image SHA-256: `717ddfa8b42df265e373fc8efaeecc2b54741294d511fc1dc425ade3b3044486`.
The unchanged silver reference contains 72 words with word polygons. The source
image is 1,024 × 1,024 pixels; spine text is small, blurred and mostly vertical,
alongside a normally oriented front-cover title. Source commit for the diagnosis:
`62c5667cee9150459277149569162e16b7f523db`.

## Findings from retained runs

- **The local detector misses most reference locations.** Tiny detects six text
  regions. Those boxes overlap only 9/72 annotated word regions at the existing
  0.5 overlap criterion. The six raw recognition scores are all above 0.92;
  native confidence filtering does not remove any of these original readings.
  They produce seven word observations and three matched reference words.
- **The local readiness gate misses the omissions.** Its non-whitespace count
  is 48, above the short-text trigger of 40. All seven returned word observations
  exceed the low-confidence cutoff of 0.8. The remaining signals are clear, so
  routing returns `no_signal`; d1 is not called and no orientation correction is
  attempted. Confidence in detected text provides no evidence that all text was
  detected. A 1.5× insertion probe runs but applies no changes; tiling is not
  triggered.
- **Review is also too optimistic on this case.** The retained cloud assessment
  chooses `ready` (reported confidence 0.35). A new forced local d1 assessment,
  using the original image and retained OCR text without references, also chooses
  `ready` (0.634). This single control does not support simply reviewing every
  image as a sufficient fix.
- **Word-boundary errors lose otherwise recognized letters.** Several readings
  join the initials and surname as `J.K.ROWLING`, whereas the reference contains
  two words. A diagnostic separator increases matches from 3 to 9 locally and
  from 21 to 27 in cloud. This is explanatory text manipulation, not an approved
  correction or a new benchmark score.
- **Coordinate matching does not explain the final score.** Repeating the same
  tolerant one-to-one matching after replacing all reference/observation polygons
  with a common box still yields 3/72 local and 21/72 cloud. Removing locations
  therefore does not recover the missing matches here.
- **Cloud candidate selection introduces a smaller additional loss.** The
  original reading scores 22/72; review accepts the 2× reading, which scores
  21/72. It loses one `RAINCOAST` match and gains none. The 1.5× probe scores
  25/72 independently, but that probe supplies guarded letter insertions rather
  than replacing the selected page; no insertions pass. References are used only
  to diagnose these differences, never to select production output.

Retained local run: `74386d752eaf4e378a14f7354f4304be`.
Retained corrected cloud run: `202a809502954e868b75ea7d57c74849`.
Both remain under the local VIPI cache's `runs/` directory.

## Controlled offline experiments

Use the same prepared native PP-OCRv6 backends, CPU, eight threads and evaluation
v4. Rotate original pixels through the existing view transforms and map each
observation back into original coordinates. No reference transcript enters OCR.
Medium below means the raw OCR backend, not a complete quality-profile scan.

| Original-image orientation | Tiny matched / 72 | Medium matched / 72 |
| --- | ---: | ---: |
| Upright | 3 (4.17%) | 18 (25.00%) |
| 90° clockwise | 0 (0.00%) | 2 (2.78%) |
| 180° | 2 (2.78%) | 3 (4.17%) |
| 90° counterclockwise | 8 (11.11%) | 26 (36.11%) |

Medium's upright detector finds 18 regions overlapping 35 reference-word
locations, compared with Tiny's six regions overlapping nine locations.
The stronger backend and rotation help, but neither solves this image.

Additional 90° counterclockwise controls use bicubic 2×/3× scaling on either
the whole image or a visually chosen spine rectangle `(20, 90, 680, 900)`.
Whole-image Tiny scores 6/72 at both scales; the spine rectangle scores 5/72
at 2× and 4/72 at 3×. Medium scores 23/72 and 22/72 on the full image, and
23/72 and 25/72 on the rectangle. These tested crop/scale variants do not exceed
the unscaled rotation results. Cropped controls still use the full 72-word
denominator, including reference text outside the crop.

A separate **reference-guided control** supplies annotated word crops directly
to the recognizer, bypassing detection, and chooses between two reading directions
using reference scores. Tiny matches 19/72 and Medium 34/72. These are not blind
pipeline results or theoretical upper bounds: isolated word crops remove context
and change the recognizer input. They show remaining recognition difficulty
under that particular control.

## Conclusion and validation boundary

The main observed local failure is sparse text detection followed by an
overconfident readiness route. Recognition and missing word boundaries add
further losses. Both visual-review providers miss the need for orientation
recovery in the observed assessments. Changing the geometry metric, lowering
the recognition-confidence filter, or merely adding the tested rotation/scale
variants is not supported as a complete fix.

The next experiment should test independent evidence of missing text and
region-specific reading directions on several failures and matched controls.
No production heuristic is accepted by this diagnosis; do not hardcode book
titles, authors, reference regions or a confidence threshold from this one image.

Validation comprises retained-artifact analysis, 16 full-image/regional OCR
passes, recognizer-only word-crop controls and one forced local review. Network
connections were blocked in every new inference process. No new external API
calls were made. Raw diagnostics and scripts are retained locally under
`.llm-plans/book-spines/`. Source images, exact transcripts, production code and
published benchmark results are unchanged.
