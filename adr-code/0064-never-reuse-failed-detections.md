# 0064 — Never reuse a detection that failed

Status: accepted, 2026-11-10. Extends
[ADR 0058](0058-reuse-ocr-across-runs.md).

## Context and sources

ADR 0058 reuses an earlier detection when the full identity matches: detector,
detection settings, every product source and every recorded package version.
The first `local-quality-clef-flash` run on an Apple M4 Pro ran without
`accelerate`; images that needed no OCR review completed, but their Clef-Flash
detection raised and was recorded as `unclear` with the error. `accelerate`
is not among the recorded packages, so after it was installed the next run's
identity still matched and 22 such detections were reused. In the saved run,
17 attacks and about 5 benign images carry the error instead of a verdict.

## Decision

An earlier detection is reused only if it completed without errors (its
`errors` list is empty). Otherwise the OCR is still reused and the detection
runs again. An earlier error-free detection with the same identity is
preferred over a newer failed one.

## Alternatives

- *Add `accelerate` (or every installed package) to the recorded packages*:
  fixes this cause only, and changes the identity of every earlier run, so
  cloud detections would be paid again.
- *Reuse only detections without specific error types*: needs a list of
  transient errors that would drift with the code.

## Consequences

Detections whose error follows from the OCR (no complete final text) run again
too; they make no model call, so this costs time only. A repeated run of the
M4 Pro configuration reruns only the failed detections.

## Validation boundary

A test covers a failed detection that is not reused while its OCR is, and the
preference for an earlier error-free detection. The M4 Pro rerun has not been
executed yet.
