# Ambiguous-character line retry experiment

Date: 2026-11-01. The user requested a complete-suite test of line-level
upscaling for ambiguous characters rather than one call per character. This is
an isolated research experiment, not an active product or adaptive OCR route.

## Protocol

Starting from the guarded 93/113 result, look for an isolated OCR word exactly
`l` in a native line with at least one other word. This is a narrow,
script-specific experimental trigger; it does not cover all `I`/`1`/`0`/`O`
ambiguities or all occurrences within larger words. Require the native line's
text to map uniquely into one existing output group. Unmapped lines retain the
incumbent and incur no retry.

Run local PP-OCRv6 Tiny once per eligible whole line, cropping one line-height
of context and enlarging 2x with Lanczos. Propose a replacement for an isolated
`l` only when the reread has one spatially overlapping word consisting entirely
of `I`, `l` or `1`; retain all other characters, the group ordering and the
incumbent group geometry. Compare actual old and proposed full-line text against
the original source image via Decisions; keep the old text unless the model
explicitly chooses the new one. No reference text, labels or scores enter
routing, OCR or model review. The current payload-reference metric is applied
only after the selection. Correcting text does not repair existing layout group
conflicts.

## Full 113-image result

| Measure | Guarded starting result | Line retry |
| --- | ---: | ---: |
| Reference passes | 93/113 (82.3%) | 93/113 (82.3%) |
| Newly passing / regressed | — | 0 / 0 |
| Images with a detected isolated `l` in a line | — | 12 |
| Extra local line OCR calls | — | 8 |
| Images/lines skipped because text mapping was ambiguous | — | 4 |
| Alternative line readings proposed | — | 3 |
| Extra Decisions requests | — | 3 |
| Estimated additional Decisions API input cost | — | $0.0001847 |

The model accepted two proposals and rejected one. The accepted proposals are
the standard and low-contrast Asteron images: both changed `SOC 2 Type l` to
`SOC 2 Type Il` (capital `I`, lowercase `l`). The reference contains `II`
(two capital `I` characters), so the new reading is **not an exact
transcription**, despite the model preferring it. The existing tolerant metric
counts `Il` as a match for `II` because it permits one edit in a two-character
word. Reference-word coverage consequently moves from 39/40 to 40/40 for each
of the two images, but both remain failed because each still has two group
conflicts. This is neither exact recognition nor an additional passing image.

The third proposal, in a previously passing command-line image, changed a
standalone `l` to `I`; the model kept the original, so its pass was retained.
The other nine images retain their prior outputs. The complete manifest,
actual line texts and decisions are saved under
`.llm-plans/ocr-ambiguous-line-2026-11-01/`.

## Limits

All 113 cases are accounted for using the prior saved chosen OCR and decisions;
only the eight eligible mapped lines were newly OCR-processed. This is not a
fresh 113-image OCR run or an independent held-out test. The signal does not
establish that text is wrong, the model preference does not guarantee exact
characters, and the reference metric covers the approved payload rather than
all image text or security recall. The test does not measure local end-to-end
performance, other scripts, unknown model providers, or production-scale
latency. API pricing is a configured estimate rather than an invoice; local
compute is excluded.
