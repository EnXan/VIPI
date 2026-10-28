# 0026: Sequential OCR comparisons and one-image readiness checks

**Status:** Implemented for review

## Context and superseded decision

This replaces ADR 0025, "Original-image baselines for research OCR comparisons."
That decision made native original-image OCR the research default, preserved
raw backend text, retained transformations as an explicit control, and rejected
source/reference changes after selection. Its rationale was to separate native
model quality from VIPI processing and keep comparisons reproducible. The user
now keeps the existing images, declines additional freeze/split work, defines
Round 0 as a one-image functional check, and requests sequential multi-model
overnight comparisons with per-image latency and cost. The freeze gate is
removed; native baselines and provenance recording remain.

Sources: the user request, inspected adapters and environments, official
[LightOn model cards](https://huggingface.co/lightonai/LightOnOCR-3-1B),
[OpenAI model/pricing documentation](https://developers.openai.com/api/docs/models/gpt-6-luna),
[Google pricing](https://cloud.google.com/vision/pricing), and
[Mistral pricing](https://docs.mistral.ai/models/ocr-4-1).

## Decision

Use one active research registry with the requested model removals. Round 0
checks one common image and persists readiness, output, time and available cost.
Failed checks disable selection until an explicit successful retry. Nonempty
output demonstrates execution only; accuracy is separate.

Keep `baseline` as research default: one original decoded image, native backend
preprocessing, no VIPI transformations or assembly, raw text preserved. PP-OCR
uses stock RapidOCR with pinned weights. Granite receives lossless PNG input
through Docling. LightOn uses the official Transformers classes and image-only
transcription prompt. Its generation bound is remaining model context, not an
application token cap. The public scanner retains its release processing.

Real checks found that PyTorch 2.6 MPS fused SDPA crashes on the LightOn
grouped-attention shapes. Use native eager attention on MPS and record this
setting. All three sizes completed the same-image check after this change.

Persist a model/image queue. Finish all images for one model before loading the
next. Heavy models run in their own interpreter process, reused across images,
then closed to release native memory. Cancellation kills the owned heavy worker.
Initialization failure skips the remaining images for that model and continues
with subsequent models. Ordinary image failures remain isolated. Closing the
browser does not stop the server; server interruption does not resume a queue.

Record OCR elapsed time, overall scan time, initialization and inference times,
raw provider usage, and dated list-rate estimates per image. Missing usage is
unknown, including uncertain charges after failures. Preserve known charges
from saved steps when subsequent evaluation/cancellation fails. Local API fees
are zero, excluding hardware/electricity. Estimates do not claim account billing.
Aggregate measurements separately for each model.

Do not fabricate coordinates for transcription-only models. Unordered spatial
references without returned word positions are unscored with a visible reason;
the evaluation policy is not silently changed for an individual model.

## Alternatives and consequences

Loading all models in the server mixes dependencies and retains native memory.
A process per image repeatedly pays initialization cost. A persistent process
per model avoids both. Separate manual batches do not meet the overnight queue
requirement. A freeze/holdout requirement now conflicts with the exploratory
workflow; reports instead record the actual source/reference used for each run.
Historical reports remain unchanged.

## Validation boundary

Verify order, reuse and closure, failure continuation, cancellation, mixed
datasets, uploads, persistence, usage/cost arithmetic and UI. Run one real
common-image check per active model. This does not establish dataset accuracy,
a 90% pass rate, billed costs, or Windows/Linux support. Full-dataset Round 1
is explicitly left for the user to start manually.
