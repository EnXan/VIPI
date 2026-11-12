# ADR 0071: Binary scan verdict with a separate final OCR completeness flag

Status: Accepted, 2026-11-12. Steps 1 (binary verdict, `injection_probability`,
`threshold`, report schema version 2), 2 (`ocr_incomplete`) and 3 (research
scoring and workbench evaluation page) are implemented in code. The 12 saved
baselines are not rescored yet: they hold the old verdicts, and their metric
hashes no longer match the changed scoring code. Amends the detection scoring in
[ADR 0054](0054-evaluation-runs-and-baseline.md).

## Context and sources

Every scanned image currently gets one of three verdicts from
[`detection/verdict.py`](../src/vipi/detection/verdict.py): `flagged`,
`not_flagged` or `unclear`. `unclear` mixes unrelated situations:

- **Empty final OCR text.** [`detection/pipeline.py`](../src/vipi/detection/pipeline.py)
  passes `evidence_complete = ocr_complete and bool(readings)`. An image without
  text has no readings, so it can never be `not_flagged`.
  [`results.py`](../src/vipi/results.py) then adds the error "No complete final
  OCR text evidence is available", the file gets `status: error` and the scan
  exits with code 2 ([`reporting.py`](../src/vipi/reporting.py)). A text-free
  photo therefore fails a CI check as an incomplete scan.
- **Long text split into chunks.** Text above 16,000 JSON bytes is split by
  [`detection/evidence.py`](../src/vipi/detection/evidence.py); every chunk
  carries `partial_context`, which `summarize` treats as unclear even when all
  chunks score below the threshold.
- **Detector failures.** Errors, refusals and missing thresholds also end as
  `unclear`.

None of these says whether readable text is missing from the OCR. That question
is answered today only before recovery: the visual review in
[`ocr/recovery/decisions.py`](../src/vipi/ocr/recovery/decisions.py) asks for
`completeness` (`complete`, `missing_text`, `uncertain`) about the first OCR
attempt, and [`ocr/recovery/selection.py`](../src/vipi/ocr/recovery/selection.py)
uses it to choose repairs. After recovery the final text can differ, and images
whose OCR was clear skip the review entirely, so that assessment cannot describe
the final text unchanged.

The detection evaluation of ADR 0054 counts `unclear` verdicts as neither
flagged nor cleared. Saved baselines record them, for example 7 of 450 for
local `balanced` and 20 for local `speed` with Prompt Guard. How many of these
come from empty OCR has not been measured.

The proposal came from the maintainer on 2026-11-12: a binary verdict, a native
model confidence and an `ocr_incomplete` flag that refers to the final OCR text.

## Decision

Each completed file record carries three independent fields:

| Field | Values | Meaning |
| :-- | :-- | :-- |
| `verdict` | `injection_detected`, `no_injection_detected`, `null` | Detector result for the final OCR text. `null` only when a required detector check did not complete. |
| `injection_probability` | 0–1 or `null` | Highest native injection probability over all completed checks and chunks; `null` when there was no text to check. The threshold that produced the verdict is reported next to it. |
| `ocr_incomplete` | `true`, `false`, `null` | Model judgment whether readable image text is missing from the final OCR text. `null` when it was not judged or could not be judged. |

Rules:

- **Empty OCR is not incomplete by itself.** Empty final text has nothing to
  check, so no detector is called and the verdict is `no_injection_detected`
  with `injection_probability: null`. `ocr_incomplete` reports whether the model
  sees readable text that OCR missed. Emptiness itself is visible from the text
  and needs no flag.
- **Chunks do not make a result unclear.** A verdict is `injection_detected` if
  any chunk reaches the threshold and `no_injection_detected` if all chunks
  completed below it.
- **Errors stay errors.** If a detector check fails, is refused or has no
  threshold, the file keeps `status: error`, lists the error and `verdict` is
  `null` unless another completed check already reached the threshold.
- **Exit codes:** 2 for errors or not scanned files, otherwise 1 if any file is
  `injection_detected`, otherwise 0. `ocr_incomplete` does not change the exit
  code; it is reported per file and counted in the summary so callers decide.
- **Final completeness judgment:**
  - If recovery kept the assessed attempt as the final text, the existing
    `completeness` answer is reused (`missing_text` → `true`, `complete` with
    sufficient reviewability → `false`, otherwise `null`).
  - If recovery changed the final text, one additional review call compares the
    final text with the original image using the same question.
  - If the OCR was clear and no review ran, `ocr_incomplete` is `null`. No call
    is added to clear scans.
- **Naming:** the existing `review_required` field is removed; the report schema
  version increases.

For ADR 0054: detection scoring uses `injection_detected` and
`no_injection_detected`; a `null` verdict counts in the denominator as neither,
as `unclear` did. Reports additionally count `ocr_incomplete` values per label.

## Alternatives and consequences

- **Keep `unclear` and only exclude empty OCR from it.** Smallest change, but the
  verdict would still mix detector failures, chunking and OCR doubts, and
  callers could not tell "no injection, text may be missing" from "check failed".
- **Report the confidence of the chosen answer** (the maintainer's first
  wording). With the threshold at 0.8, a probability of 0.6 becomes "no
  injection detected" with confidence 0.4, which reads as a contradiction; the
  native values are not calibrated, and chunked text has several. Reporting the
  injection probability and the threshold avoids both.
- **Always ask for final completeness.** Gives a value for every image, but adds
  a model call to every scan: minutes per image locally on CPU, a billable
  request in cloud mode. Rejected until a need is shown.
- **Fail the scan when `ocr_incomplete` is true.** Would recreate the current
  CI failures for uncertain cases. A caller option can be added when needed.

Consequences: the report schema, CLI output, Action documentation, workbench,
evaluation scoring and comparison change together. The 12 saved baselines need
rescoring or new runs, because their detection counts use the old verdicts.
This is a breaking report change and needs a minor version bump.

## Validation boundary

Step 1 is covered by unit tests for the verdict rules and an integration test
that a text-free image scans with exit 0; steps 2 and 3 are not implemented or
measured yet. `research/ocr_eval/benchmark_report.py` maps retained old verdicts onto the new
names (`unclear` becomes no result), so old baselines stay readable but cannot
show the effect of the new verdict rules or any `ocr_incomplete` values.
To validate:

- Step 2: tests with a fake decider cover reused, re-asked, not reviewed and
  failed re-ask; the added time and cost of the extra call is unmeasured.
- Unit tests for the verdict rules: empty text, chunked text below and above the
  threshold, detector error, refusal, missing threshold.
- Integration test: a text-free image scans with exit 0 and
  `no_injection_detected`.
- On the development split, compare `ocr_incomplete` with the reference
  transcripts (word coverage below 100 %) to measure how often the flag is
  right, separately for reused and newly asked judgments.
- Measure the added time and cost of the extra review call after recovery for
  local `balanced` and cloud Google.
