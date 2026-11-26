# ADR 0086: Load local weights sequentially and stop benchmark workers on interrupt

Status: Accepted for implementation and review, 2026-11-26.

## Context and sources

The `local-quality-wolf-defender` development evaluation on an Apple M4 Pro
(macOS 26.7, transformers 5.22.2, safetensors 0.8.0, torch 2.11.0) stopped three
times without an error. Each time the image in progress was the first image of a
fresh benchmark worker, and its last event was `ocr_assessing`, the first
Clef-Flash decision. The worker used 0 % CPU, and its `decisions/0001` folder
stayed empty. The images differed (`07aba5fd2474aae1`, `bdfd7cc02d388545`,
`b763e4b2e51cbef0`), and each one scans normally in other runs.

macOS `sample` of two hung workers (one from 2026-11-23 that was still alive three
days later, one from 2026-11-26) showed the same deadlock while weights loaded:

- transformers loads weights in a thread pool of up to four threads
  (`transformers/core_model_loading.py`) unless `HF_DEACTIVATE_ASYNC_LOAD` is
  true, disk offloading is used or weights are quantized on the fly;
- one loader thread was inside safetensors `PySafeSlice.__getitem__`,
  initializing a `OnceLock`, and was waiting to reacquire the GIL;
- a second loader thread was waiting for that `OnceLock` while holding the GIL;
- the main thread was waiting for the GIL.

The race depends on thread timing. It struck a few times in several hundred
model loads, so it can also hang a `vipi scan` that loads Clef-Flash, d1 or
Prompt Guard.

Ctrl+C did not end a hung worker. SIGINT reaches the worker, but Python handles
it only in the main thread, which needs the GIL. The benchmark parent then exited
and left the worker and its resource tracker running as orphans.

## Decision

- `vipi.weight_loading.load_weights_sequentially()` sets
  `HF_DEACTIVATE_ASYNC_LOAD=1` unless the environment already sets the variable.
  `LocalDecisionModel` (Clef-Flash, d1) and the Prompt Guard detector call it
  before they import torch and load weights. transformers reads the variable on
  each `from_pretrained()` call, so the process-wide setting applies to every
  later load.
- `research.ocr_eval.benchmark.run_configuration` terminates a still-running
  worker with SIGTERM when an exception, including `KeyboardInterrupt`, ends the
  wait for that worker, and then re-raises. SIGTERM ends the process without
  running Python code, so a worker without the GIL also ends. The image in
  progress stays unrecorded, and a resumed run scans it again, as before.

## Alternatives

- Upgrade or pin safetensors or transformers: whether a newer release fixes the
  race was not checked, and a dependency change would also change evaluation
  provenance.
- Load each model under a timeout and restart the worker: this detects a hang
  only after the timeout and adds a limit without a measured value; avoiding the
  race is simpler.
- Document the variable for users only: every `vipi scan` would still be
  exposed by default.

## Consequences

- Weights load with one thread. On the M4 Pro, Clef-Flash (760 tensors) took
  about 4 s per load with threads (162–173 tensors/s) and 5–6 s sequentially
  (126–140 tensors/s), from the transformers progress bars in the run log. A
  scan loads each model once; the benchmark loads it once per four images.
  Inference per image is unchanged.
- A user who sets `HF_DEACTIVATE_ASYNC_LOAD` explicitly keeps that value.
- An interrupted benchmark leaves no worker processes behind.

## Validation boundary

Unit tests check that the variable is set, that an explicit value is kept, that
both loaders set it before importing torch, that the locked transformers version
still reads this switch, and that an interrupted run terminates its worker. The
deadlock itself was not reproduced in a test because it depends on thread timing.
With `HF_DEACTIVATE_ASYNC_LOAD=1` set in the shell, the resumed
`local-quality-wolf-defender` run finished its remaining 133 images on the M4
Pro without a hang; this is the same switch, but not this code path, and too
few loads to prove the race gone. Windows and Linux are unverified.
