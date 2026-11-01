# Layout-specific correction route

Date: 2026-11-01. This research-only trial follows the user's direction to
revert the signal-context assessment and test a repair route suited to layout
errors. The earlier assessment context code is removed; its results are kept in
[OCR_SIGNAL_CONTEXT.md](OCR_SIGNAL_CONTEXT.md).

## Experimental route

For the 113-case signal-gated comparison, consider a separate layout correction
only when the first balanced signal indicates overlapping text groups. From
original native OCR line IDs, construct a candidate in geometric row order.
Each native line remains intact, and the candidate is discarded if it would
add or remove non-whitespace characters. If line membership is unavailable or
no layout differs, retain the incumbent. This character-preservation check does
**not** ensure correct sentence order, inter-line relationships, or semantic
grouping.

For a usable candidate, ask OpenAI Decisions (`gpt-6-luna`) to compare the
original image and the two actual groupings. Explicitly select the candidate
only when it judges the grouping or within-group order improved; otherwise
retain the incumbent. No reference transcript or reference score enters the
candidate construction, routing or model request. Reference scoring happens
after selection. This route performs no new OCR; it reuses the native OCR output
and attempts a layout-only repair. It does not implement local crop re-OCR or
other possible correction routes.

## Full-suite result

The full 113-image comparison is composed using saved outputs from the previous
signal-gated experiment for unaffected cases. Twelve reviewed cases had an
overlap signal: two did not produce a suitable different candidate, ten were
compared by Decisions, and the model selected three alternatives. The request
and selection records are in `.llm-plans/ocr-layout-routing-2026-11-01/`.

| Measure | Previous signal-gated run | Layout route |
| --- | ---: | ---: |
| Reference passes | 92/113 (81.4%) | 90/113 (79.6%) |
| Matched reference words | 4,031/4,175 | 4,022/4,175 |
| Improvements / regressions in passed images | — | 0 / 2 |
| Additional OCR runs | — | 0 |
| Additional Decisions requests | — | 10 |
| Estimated additional API input-token cost | — | $0.0049668 |

The ten extra comparisons are in addition to the previous experiment's 46
Decision requests and estimated $0.0112609. These are configured estimates,
not invoices; local compute and prior development work are excluded.

The two newly failing references illustrate incorrect line order. In
`phantom_deepseek-vl2_1176_jailbreak_none.jpg`, the alternative placed
`specific` after the following line instead of before `racial group`. In the
Base64 invoice, it placed the final encoded line before the middle line,
breaking the encoded string. A third selected candidate also reduced matched
words on a previously failing lab-notebook image. These are actual selected
results, not oracle choices. The model's selection did not reliably prevent
regressions on this sample.

## Decision and limits

This candidate is retained only as an isolated research experiment and is not
connected to the default or experimental adaptive profile. It should not be
adopted as a quality improvement. The result does not rule out a better grouping
algorithm or other specialized correction routes. These 113 cases are the
existing development suite with cached baseline OCR, not an independent
production dataset or a fresh 113-image inference run. The reference metric
covers approved payload text rather than all visible image text or injection
recall. Data, region scores and raw Decision inputs are preserved in the
ignored experiment directory for review.
