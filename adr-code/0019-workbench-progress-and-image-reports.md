# 0019: Show scan progress and per-image evaluation details

Status: Accepted for the workbench UI.

## Context and sources

The user asked for the current image and scan phase to remain visible while a
run is active, including an estimated duration, an OCR-complete state and a
color-coded detector outcome. They also found the Evaluation page too dense and
asked for a short per-image table with text, reference and exact detector
scores available on demand. The active UI and report shape are implemented in
[`research/workbench`](../research/workbench/README.md), with batch state in
[`batch.py`](../research/workbench/batch.py).

## Decision

- Keep the run panel visible across Scan and Evaluation. Animate a scan beam
  over the current image while OCR or detection is active, mark OCR completion,
  and tint the image red for flagged, green for not flagged, and amber when the
  detector result is unclear.
- Estimate remaining time from completed OCR steps, detector checks, or batch
  images divided by elapsed time. Present this as an estimate, not a runtime
  guarantee.
- Make the Evaluation page's primary table per image and keep aggregate
  detector metrics, per-case tables, effects and category views collapsed.
- Store each selected image's reference and recognized text with the batch
  report. Show those texts and detector scores at full stored precision in the
  row details.

## Alternatives

Keeping every aggregate and case table open preserves the existing dense report
but makes the primary per-image outcomes hard to scan. Fetching text only when
opening each row would require additional report-loading requests; storing the
two strings with the selected batch keeps its saved report self-contained.

## Consequences

Batch report files include reference and recognized text per selected image.
The live estimate improves as work completes and may change as the observed
throughput changes. OCR and detection use separate estimates because detector
work totals are only known when that phase starts.

## Validation boundary

The workbench renderer, batch report and local styling are changed. JavaScript
syntax, Python syntax and whitespace checks are the static validation boundary;
browser layout and live model behavior still require manual review.
