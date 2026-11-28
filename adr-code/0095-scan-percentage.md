# ADR 0095 — Scan percentage in the CLI status line

Status: accepted for implementation and review, 2026-11-28.

## Context

`vipi scan` showed a spinner with the current file (`[1/3] Scanning …`) but no
percentage. The scanner reports OCR passes and detection checks as events,
but a real scan of one screenshot spent about 1 s in its OCR pass and up to
25 s afterwards selecting and assessing text without reporting a step. A
percentage from those counts jumped to almost full and then stood still.
The user asked for a simple percentage, nothing more.

## Decision

- `scan()` takes `on_file_started(index, total)`, called before each file.
- `vipi.scan_progress.ScanPercent` turns that into a whole percentage: done
  files count fully; the running file moves by time against the average
  duration of the files finished in this run, 15 s for the first file. It
  eases (80 % of the file at the expected duration), stops at 97 % of the file
  until the next one starts, and never moves back.
- The CLI status line shows `NN % · <current message>`, refreshed four times a
  second. Reports and JSON output are unchanged.

## Alternatives and consequences

- Counting OCR passes and checks: rejected for the jumps described above.
- Storing durations between runs (the workbench does this in the browser):
  not chosen to keep the CLI stateless; the first file of every run uses the
  15 s estimate, so a one-file scan is a rough estimate that may wait near
  the end or finish early.
- A full progress bar: not requested.

## Validation boundary

Unit tests cover the percentage with a fake clock and the per-file callback.
The status line was checked in a macOS terminal; Windows/Linux terminals are
unverified.
