# PP-OCRv6 Medium detector benchmark

Date: 2026-11-01. Compare the installed PP-OCRv6 Medium detector with the
Tiny detector on all 113 images in the active evaluation suite. The selected
OCR result remains 93/113 passes. This run evaluates detector boxes only: it
does not call a recognizer and does not retry weak OCR boxes.

## Method

Run both detectors on the original image with native RapidOCR preprocessing,
CPU execution and one thread. Tiny boxes come from the fresh full-suite raw
detector run. Medium boxes are produced by the Medium detector only. Count a
Medium box as additional when its overlap with every Tiny box is less than
50% of the smaller box area. This spatial rule is a comparison heuristic;
additional boxes do not necessarily mean additional text.

For the 15 annotated payload regions in the suite, count a region as detected
when at least half of a detector box lies inside it. Most images have no
payload-region annotations, so this localization comparison covers only those
15 regions. A temporary visual review compared Medium-only boxes in several
remaining failures.

## Results

| Measure | Tiny | Medium |
| --- | ---: | ---: |
| Images | 113 | 113 |
| Detector boxes | 3,596 | 3,825 |
| Detector time, summed | 37.6 s | 439.8 s |
| Mean detector time per image | 0.33 s | 3.89 s |
| Annotated payload regions detected | 15/15 | 15/15 |

Medium produced 358 boxes without a matching Tiny box across 42 images. None
overlapped an annotated payload region under the stated comparison rule.
Medium-only boxes appeared on 11 of the 20 currently failing images, but they
also appeared on 31 passing images. The orange anamorpher failure still had
zero boxes from either detector.

Visual review was mixed. On the low-contrast beach image, two new Medium boxes
appear to align with faint overlaid text; on the low-contrast cat image, three
new boxes also align with visible payload lines. These look promising, but no
recognition was run on them, so text recovery and pass-rate impact are unknown.
In two notebook images, 70 and 72 extra boxes mostly trace ruled lines and
page margins. They are false detections. The box count alone is therefore not
a reliable measure of text recall.

The Medium detector took about **11.7 times** the Tiny detector time on this
CPU setup. This is detector inference time only; model initialization was
about 0.6 seconds. No OCR reading or suite pass status changed in this
detector-only test.

## Conclusion

Medium does not provide a generally better detector at an acceptable cost for
the local pipeline: it is much slower, adds many non-text boxes, and did not
increase coverage of the annotated payload regions. The two low-contrast
examples are possible exceptions worth a separate test that recognizes only
new Medium detections. That would be a new experiment; no weak OCR box was
used as a retry trigger here.

Raw per-image records and the visual overlays are in
`.llm-plans/ocr-missing-text-2026-11-01/`.
