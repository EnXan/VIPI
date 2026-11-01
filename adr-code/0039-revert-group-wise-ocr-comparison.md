# 0039: Revert group-wise OCR comparison

Status: Accepted, 2026-11-01.

## Supersedes

ADR 0038 tested comparing uniquely overlapping OCR groups against image crops,
selecting individual readings while recording uncertain alternatives. This was
intended to recover a better text group without replacing the entire page. On
the 113-image development suite, the trial decreased reference passes from 93
to 92, including one regression, and did not recover the targeted encoded
text. The user requested reverting the implementation. The historical results
and validation boundary remain in [OCR_GROUP_MERGE.md](../research/ocr_eval/OCR_GROUP_MERGE.md).

## Decision

Remove the group-comparison implementation, its Decision adapter and its tests.
Keep the earlier guarded upscaling research and the default adaptive and product
flows unchanged. Do not treat the prior exploratory comparison as evidence that
all region-specific approaches or separately checked alternatives cannot work.
