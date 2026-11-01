# 0036: Revert signal-context experiment and test a layout repair route

Status: Research trial, 2026-11-01.

## Supersedes

ADR 0035 tested supplying the first OCR-quality signal and a corresponding crop
to visual assessment while retaining the existing correction policy. It was
chosen to investigate whether the decision model would recognize missed defects.
The 113-image comparison found the same 92/113 reference passes and word counts,
with more OCR and API work. The user requested reverting that implementation;
the historical report and measurements remain available in
[OCR_SIGNAL_CONTEXT.md](../research/ocr_eval/OCR_SIGNAL_CONTEXT.md). Remove its
optional code path and tests, and retain the adaptive gate and research-only
signal cascade then defined in ADR 0032/0034. ADR 0032 was later superseded by
[ADR 0044](0044-product-research-recovery.md).

## Decision and validation

As the first separately testable repair family, test whether an overlapping-group
signal can select a native-line layout candidate without changing OCR characters.
Use the actual original image and both groupings for model comparison, and do
not supply reference labels before selection. Keep the experiment isolated from
the adaptive and product defaults. This does not implement other repair types.

On the existing 113-image suite, model-selected layout variants reduced the
reference pass count from 92 to 90 and caused two regressions. Preserved
character counts did not protect within-group word order; the model selected
some wrong orderings. See [OCR_LAYOUT_ROUTE.md](../research/ocr_eval/OCR_LAYOUT_ROUTE.md)
for the exact protocol, results and limits. Do not adopt this candidate as a
quality improvement. The evaluation reuses baseline and selected OCR outputs,
is not a fresh 113-image inference run and does not establish attack recall.
