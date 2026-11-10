# 0063 — Backfill execution records from recorded data

Status: accepted, 2026-11-10. Extends
[ADR 0062](0062-record-execution-devices.md).

## Context and sources

ADR 0062 records host and per-component devices for new runs. The baselines
saved before it (local-speed and cloud-google on an Apple M2,
cloud-google-jev, and a local-quality-clef-flash run on an Apple M4 Pro)
lack that record. Running them again costs hours of local compute and, for
cloud configurations, provider charges. The user asked on 2026-11-10 to add
the hardware without running anything again.

Two recorded sources exist:

- Every summary has a `host` block with the platform and, on macOS, the CPU
  name, core counts and memory (`sysctl`).
- `vipi.ocr.recovery.decision_adapters` writes `decision_device`, read from
  the loaded decision model's parameters, into every local review request in
  the run artifacts. The injection detector uses the same loaded model in the
  same worker process.

## Decision

- `python -m research.evaluate backfill-execution` adds `execution` to every
  saved baseline and run summary that lacks it, and leaves the others
  unchanged. `--dry-run` only prints.
- The host comes from the summary's host block. The device of local decision
  models comes from the recorded review requests; its dtype follows the load
  rule of `vipi.local_decisions` for that device. OCR, Prompt Guard and API
  components follow from the scan options as in ADR 0062.
- Without local artifacts (a run copied from another machine) or with more
  than one recorded device, the device stays `null` and the GPU "not
  recorded". Nothing is inferred from the platform.
- The record carries `backfilled` with the time, the number of review requests
  read and the devices found.

## Alternatives

- *Rerun every baseline*: exact, but hours of compute and provider charges for
  data already recorded.
- *Infer the device from the platform* (Apple Silicon means MPS): plausible but
  unverified; rejected in favour of the recorded device or none.
- *Use the recorded device for new runs as well*: more precise than the rule
  of ADR 0062, but changes the new-run path; left for a later change.

## Consequences

Earlier baselines show the hardware they ran on. A backfill must run on the
machine with the run's artifacts to recover the device. Editing a baseline's
`execution` changes neither its manifest nor its staleness.

## Validation boundary

Tests cover devices read from review requests, unknown and mixed devices,
the host conversion, the command's dry run, a second run that changes nothing
and cloud summaries. A dry run on the Apple M2 found MPS in 321 review
requests of the local-speed baseline. Linux and Windows hosts, whose summaries
have no hardware block, are untested.
