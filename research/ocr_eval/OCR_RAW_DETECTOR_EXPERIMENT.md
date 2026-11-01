# Raw detector and empty-region retry experiment

Date: 2026-11-01. This research-only experiment asked whether OCR detector
regions discarded after recognition could provide a signal for missed text.
The 113-image active suite and its references were left unchanged. The current
best selected result remains 93/113 passes.

## Method

Instrument PP-OCRv6 Tiny's native `run_ocr_steps` in a temporary research
runner. For each original image, record detector boxes and scores plus the
recognizer's text and confidence **before** RapidOCR's final-output filtering.
This adds no detector or recognizer inference to the initial pass and does not
change product code or output. The full 113-image run took about 91 seconds.

For every detector box with an empty recognition, try two separate local
readings of its crop with one box-height of context: bicubic 2x and
green-minus-red followed by bicubic 2x. These crop retries are independent
observations; they are not automatically inserted into the selected OCR text.
Reference comparison is performed after the readings are produced, for
evaluation only.

## Results

| Observation | Result |
| --- | ---: |
| Images in active suite | 113 |
| Native detector boxes | 3,596 |
| Boxes with empty recognition | 25 across 15 images |
| Boxes with recognizer confidence below 0.5 | 67 across 33 images |
| Boxes with detector confidence below 0.5 | 0 |
| Images with either an empty or low-confidence region | 33 |
| Current-best failures among those 33 images | 7 |
| Current-best passes among those 33 images | 26 |
| Crop OCR calls for the 25 empty boxes | 50 |
| Nonempty crop readings | 16 |

Seven of the 20 remaining current-best failures had an empty or low-confidence
detector region; the signal would miss the other 13. Of its 33 signaled images,
26 already pass the current reference test. It is a weak trigger on this suite,
and many detector boxes appear to be graphics or other non-text content.

Of the three failing images with empty detections, the low-contrast weather
image produced no text in either crop retry. The vendor DPA image produced
`Attached` and symbol-like readings, but neither missing reference item (`04:`
or `SIGNED`). A crop from the benign checklist produced `STATUS`, matching one
missing reference word; many other reference words remained missing, so the
image still failed. Thus the selected pass rate did not improve: **93/113**.
The orange anamorpher example produced no detector boxes at all, so this signal
cannot identify text missed by the detector itself.

## Conclusion and boundary

Keeping the raw box data is cheap during an existing OCR pass, and it may help
diagnose why a region was not transcribed. Empty/weak boxes alone do not make a
useful general retry trigger here: they miss most remaining failures, fire on
many passing images, and localized retries rarely recover the missing payload.
This result does not rule out a separate experiment with a stronger detector;
it does rule out treating raw empty/low-confidence regions as a sufficient
signal for this suite.

The temporary raw records and crop readings are in
`.llm-plans/ocr-missing-text-2026-11-01/`. No reference text was used by the
runtime or to choose a retry; references were used only in the offline
evaluation.
