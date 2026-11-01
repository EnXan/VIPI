# Signal-informed OCR assessment experiment

Historical result: the implementation described below was reverted at the
user's request after the full-suite comparison; this report preserves its
protocol and results. The `signal_review` option is no longer available.

Date: 2026-11-01. This opt-in research experiment gives the existing adaptive
Decision assessment the first local OCR-quality signal and, where locatable,
the associated OCR text and an image crop. It does not change the default
adaptive profile or the public OCR flow. It does not route images or apply new
corrections; the existing assessment and correction policies remain unchanged.

`signal_review=True` computes the balanced experimental priority cascade on the
original OCR. The assessment request includes the signal reason and numeric
observations as fallible evidence. For overlapping groups, unknown words in a
group, small regions or low-confidence regions, it supplies recognized texts,
coordinates, and one crop spanning the corresponding regions. A page-level or
short-text signal need not identify a crop. The crop may contain multiple text
regions or span a large area; it is not a guarantee that the missing payload is
inside that crop. No reference transcript or evaluation result is sent.

## Development comparison

All ten failures previously marked for review but assessed as `ready` in the
113-image experiment were retested, along with five previously passing controls
covering overlapping groups, unfamiliar words, small text and short text. Each
image had already been authorized for the preceding Decisions run. The cases
were selected before the test and use the same model, thresholds and correction
policies. The comparison is time-separated, not randomized; model responses
can vary between runs. Outputs and the fixed case selection are in
`.llm-plans/ocr-signal-context-2026-11-01/`.

| Measurement | Earlier assessment | With signal context |
| --- | ---: | ---: |
| Previously failing cases passing reference test | 0/10 | 0/10 |
| Previously passing controls still passing | 5/5 | 5/5 |
| Failing cases assessed as needing contrast correction | 0/10 | 1/10 |
| OCR observations across these 15 cases | 15 | 24 |
| Logical Decision requests across these 15 cases | 16 | 20 |
| Configured API input-token estimate | $0.0021633 | $0.0072580 |

All 15 cases retained exactly the same number of matched reference words as
before. The newly triggered contrast attempt on the failing encoded-text image
found no verified improvement and retained the original OCR. Two of the five
controls were also assessed for contrast, but remained passing. Fourteen cases
had a location-based crop; the short-text control did not have a localized
signal. More image content per request and additional correction attempts
contributed to the larger cost, although this small comparison does not isolate
individual causes. Prices are estimates, not invoices; local costs are excluded.

## Full 113-image comparison

At the user's request the same experimental change was subsequently evaluated
on the full 113-image suite, using the same signal routes as the prior full
experiment. The 15 results above were reused; the other 18 reviewed images were
processed with signal context. The 80 cases without signals retained the same
saved original OCR. Thus all 113 cases are accounted for, but this is not a
fresh original-OCR run for all images.

| Measurement | Previous full experiment | With signal context |
| --- | ---: | ---: |
| Reference passes | 92/113 (81.4%) | 92/113 (81.4%) |
| Image-level improvements or regressions | — | 0 / 0 |
| Reference words matched on the 33 reviewed images | 1,135 | 1,135 |
| OCR observations on reviewed images | 49 | 55 |
| Logical Decision requests | 46 | 47 |
| Configured API input-token estimate | $0.0112609 | $0.0148411 |

All 33 reviewed images have identical matched-reference-word counts to the
previous experiment; the 80 unreviewed images retain identical OCR. Twenty-five
reviewed cases supplied a localized crop. API estimates include the 15 reused
and 18 new signal-context runs, but exclude initial baseline OCR, local compute
and previous development work. The complete manifest is in
`.llm-plans/ocr-signal-context-2026-11-01/full_summary.json`.

These results do not prove that the approach, model or additional context can
never work. The
existing question asks whether an image transformation is warranted, so `ready`
can be consistent with a defect that needs grouping or another recognizer
rather than a contrast or orientation transform. A focused crop can also point
at a signal that does not correspond to the missed reference payload.
Investigating different repair types and more targeted signals is a separate
concept and has not been implemented or evaluated here.
