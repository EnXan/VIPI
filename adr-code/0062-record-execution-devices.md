# 0062 — Record where an evaluation run executed

Status: accepted, 2026-11-10.

## Context and sources

Saved baselines are now produced on more than one machine (an Apple M2 with
16 GB and an Apple M4 Pro with 48 GB). Each run summary recorded the host's
platform and, on macOS only, four `sysctl` values, but not which device each
component used. The device is chosen at load time: local decision models (d1,
Clef, Clef-Flash) take CUDA/BF16, Apple MPS/FP16 or CPU/FP32
(`vipi.local_decisions.LocalDecisionModel._runtime`); local OCR runs on CPU
through ONNX Runtime (`vipi.ocr.session`); Prompt Guard is loaded on CPU. The
workbench showed none of it. The user asked on 2026-11-10 to see in every
baseline what it ran on, including the host hardware.

## Decision

- `research/evaluate/execution.py` records, per run, `execution` in
  `summary.json` (and so in a saved baseline): the host (system, CPU name,
  physical and logical CPUs, RAM via `psutil`, and the GPU used, with its
  memory on CUDA) and, for OCR, OCR review and injection detector, the model
  and its device and dtype, or `api` for hosted providers. A hosted OCR
  review or detector records the model ID its provider sends (for example
  `gpt-6-luna` through the OpenAI Decisions API, `jev-1.14.0` through the
  TypeSafe API) with `provider` and `service`, read from the provider class
  so the record follows the code. The cloud baselines saved before this
  change, which held only the provider name (`openai`, `jev`), were updated
  to this form: the IDs match the provider code at each run's commit and the
  model the APIs reported in the run's results.
- The torch device rule is repeated from the product instead of importing a
  new product helper. Any change under `src/vipi/` changes the OCR identity
  and would make every earlier result unusable for reuse (ADR 0058), so cloud
  OCR would be paid again. Torch is only imported when a local torch model is
  used.
- The run report gets an "Execution" section, appended outside
  `benchmark_report.py` so the metric sources and saved baselines stay
  unchanged. The workbench shows "Ran on …" on a run and the baseline's host
  next to its status. Baselines saved before this ADR show their recorded
  `sysctl` host and "devices not recorded".

## Alternatives

- *Record the device inside the worker*: exact for each process, but needs a
  product change (session metadata) with the reuse cost above.
- *Add a product helper for the device rule*: avoids the repetition, same
  reuse cost. Reconsider when `src/vipi/` changes for another reason.
- *Change the existing `host` block*: `compare` reports `host_differs` from it,
  so new fields would mark every comparison with an older baseline as on a
  different host.

## Consequences

Run times and memory can be read against the hardware and devices. The
recorded devices follow the selection rule evaluated in the evaluation process
on the same host, not a reading from the worker; a worker that failed to use
the device would not be detected. GPU/MPS memory use is still not measured.

## Validation boundary

Tests cover local MPS, CUDA with GPU memory, Prompt Guard on CPU, cloud
configurations without importing torch, the report lines, the summary field
and the workbench baseline fields. The real record was checked on an Apple M2.
Linux CPU names come from `/proc/cpuinfo`; Windows and Linux are untested.
