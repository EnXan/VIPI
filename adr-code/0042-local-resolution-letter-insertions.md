# 0042: Trial local letter additions from a resolution probe

Status: Research trial, 2026-11-01.

## Context and sources

The user requested continued OCR improvement until the suite result improves,
with every optimization evaluated over all 113 images and no retries triggered
by weak OCR boxes. The exact-token guard in ADR 0037 can preserve misspellings
and reject a better resolution reading. A 1.5x Lanczos probe produces
`partition` at the same location as the incumbent `partion`.

## Decision

Keep a separate research guard that permits alphabetic missing-letter
corrections only with original-character retention, spatial overlap, increased
native OCR confidence and increased multilingual wordfreq frequency. Retain
the incumbent page, applying only uniquely mapped supported word corrections.
References remain offline evaluation labels. This extends the research options;
it does not replace ADR 0037 or enable the new route in the product.

## Alternatives and consequences

Keeping exact tokens rejects genuine corrections. Replacing the whole page
can lose unrelated content. Confidence and geometry alone admit a spurious
`requests` to `regquests` insertion; dictionary support rejects that case.
Dictionary preference can still harm names and rare valid words and has
limited language coverage. The probe costs an extra OCR pass, while broad
multilingual frequency data has significant memory cost. Weak OCR confidence
is not a retry trigger.

## Result and validation boundary

The full 113-image comparison improves from 93 to 94 strict passes, with zero
pass regressions and one additional exact reference word. The 80%-coverage
count remains 107. This is post-hoc development-set evidence for a small
correction, not held-out validation or proof of improved attack recall. See
[the experiment report](../research/ocr_eval/reports/OCR_RESOLUTION_INSERTIONS.md).
