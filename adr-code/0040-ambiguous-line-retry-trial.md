# 0040: Test a line-level retry for ambiguous OCR characters

Status: Research trial, 2026-11-01.

## Context and decision

A standalone `l` can be an OCR misreading of another narrow character even
when its reported OCR confidence is high. The user requested testing zooming
at the line level to avoid one OCR call for each character. In research only,
trigger on an isolated lowercase `l` in a uniquely mapped native line and
rerun that complete line at 2x. Propose changes only to a spatially matching
`I`/`l`/`1`-family token, preserving other text and group geometry. An
independent visual decision chooses whether to retain the original reading.
Reference transcripts and scores never enter this process.

## Result and boundary

On the current 113-image development suite, eight line OCR calls and three
Decision requests left the pass count unchanged at 93/113 with no reference
pass regressions. The two Asteron cases changed `l` to `Il`, while their
reference has `II`; the tolerant metric counts the new word as matching but
both images still fail because of group conflicts. See
[OCR_AMBIGUOUS_LINE.md](../research/ocr_eval/OCR_AMBIGUOUS_LINE.md). This is not
proof of exact transcription, full-image correctness, general language
coverage or safety. Do not introduce it into the public or default adaptive
flow based on this trial alone.
