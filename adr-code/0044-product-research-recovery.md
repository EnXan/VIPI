# 0044: Product recovery pipeline and complete local/cloud execution

Status: Accepted for implementation, 2026-11-01.

## Supersedes

ADR 0043 promoted Decisions with local tiles only in the Research Workbench,
leaving the public scanner unchanged. It retained ADR 0032's original-OCR gate
and targeted corrections to reduce the exhaustive candidate loop's OCR/API cost. That scope was a misunderstanding: the
maintainer explicitly requested the product `vipi scan` pipeline and the full
workflow behind the 95/113 research result, rather than the later 92/113 route.

ADR 0021 selected native CLAHE and color contrast in a fixed local transform
profile after measuring improved OCR coverage. Its fixed-pass default is
replaced by the selected signal-driven recovery workflow.

ADR 0027 mapped local OCR speed/quality profiles and explicit cloud OCR
providers, with Google as cloud default. It allowed OCR execution and detector
selection to be independent. The maintainer now defines local execution as the
entire scan, including transformation decisions and injection detection; this
replaces that independent-routing decision while preserving the OCR model IDs
and provider choices. Google was selected after the earlier 113-image provider
comparison; named providers avoided implying unsupported quality/price tiers.

## Context and sources

The 95/113 artifact combined the signal-gated research result, guarded 2× OCR,
local 1.5× insertion correction and tiles protected by both confident-token and
all-token retention. It was not an entirely local inference benchmark: the
prerequisite recorded Decisions stages made 73 requests. A fresh 190-tile replay
with matching geometry reproduced all texts and 95/113 passes. The transfer
protocol, costs, exact operators and measurement boundary are documented in
[Product OCR recovery](../docs/ocr-recovery.md). Temporary evidence is under
`.llm-plans/product-research-promotion/`.

Official runtime contracts are the [Clef model card](https://huggingface.co/Cloudflare/clef)
and [d1-3B model card](https://huggingface.co/LiquidAI/d1-3B). The chosen local
quality mapping is a user requirement, not evidence that Clef has the best VIPI
score. The implementation uses pinned revisions and verifies executable model
code before local loading.

## Decision

Move the selected recovery algorithms into `src/vipi/`; research imports that
implementation. The Workbench retains original-only as its default comparison
control and exposes the shared adaptive workflow explicitly. Product code imports no research modules or Flask. Use the
existing session, engine, result and storage contracts.

`--modus local` selects local OCR plus Clef for quality and d1-3B for
balanced/speed/fast. The injection detector defaults to that same local model;
explicit local Prompt Guard remains supported. `--modus cloud` selects cloud
OCR and defaults to OpenAI Decisions for visual review and injection detection;
Jev is selectable. Contradictory cross-mode provider choices fail before
inference. Python image adjustments execute in process in both modes.

Setup explicitly downloads pinned local models. Scanning requires prepared
files and has no hosted fallback. The two decision roles share one local model
runtime. Clef's upstream encoder is preflighted against its backbone context
without silently truncating the supplied state. Cloud decision calls retain
the existing three-attempt transient-error backoff.

The actual 16 GB Apple MPS run exposed incompatible grouped-query attention
under PyTorch 2.6 and out-of-memory failures on eight orientation previews and
five-image OCR comparisons. Local multi-image decisions therefore use 512 px
previews per view while retaining the complete OCR text and geometry in state;
single-image assessment keeps its requested preview size. A live five-image
local comparison took 147 seconds. Reducing it to two images alone still took
155 seconds because the prompt repeated OCR groups and box coordinates. Local
comparisons now pass the source and candidate images and each complete text
group once, without duplicate geometry. On the logger image this reduced the
decision from 10,052 input tokens and 155 seconds to 2,318 tokens and 6.5
seconds. Cloud review keeps the full visual comparison. Use the supported PyTorch 2.11/TorchVision 0.26
pair. On MPS, load d1 in FP16, encode independent vision tiles serially, and
compute causal attention in query chunks while retaining the entire key/value
context. The work batch reuses the pinned runtime’s existing 1024-query chunk;
it is not an input restriction. CPU and CUDA retain native execution. Tests
compare chunked attention and serial vision with their full batched results;
the inference code releases unused MPS memory after each request. See the
[PyTorch attention contract](https://docs.pytorch.org/docs/2.11/generated/torch.nn.functional.scaled_dot_product_attention.html).

Retain the measured signal thresholds, the 8-million-original-pixel boundary of
the 2× research probe and the measured tile geometry for this transfer. The
8-million boundary reproduces the selected research protocol, rather than
claiming a model/API requirement. Removing it or changing the operators needs
a separate measured comparison. Benchmark references never enter selection. A single weak OCR box is not an independent region-retry
trigger. Unavailable signals remain explicit.

## Alternatives and consequences

Keeping the research-only 92/113 route did not meet the clarified requirement.
Using the legacy 15-pass product profile would also omit the selected research
improvements. Shipping saved per-image choices would reproduce a benchmark
artifact but would not implement inference on new images, and is not selected.

Local model loading adds dependencies and setup downloads; Clef's 27B model
needs considerable memory. Cloud OCR can multiply billable OCR calls during
recovery. Reports preserve actual model identity, decisions, variants, counts,
known fee estimates and unknown costs. Live decisions can differ from recorded
ones, so the historical 95/113 score is a target and transfer reference, not an
automatic guarantee for every provider or model profile.

## Validation boundary

The unit, integration and research suites pass (459 passed, one optional skip),
and Ruff and `git diff --check` pass. An all-image replay with recorded decision
responses reproduces 95/113, but this does not validate live model decisions.

The product CLI was also run on all 113 images with local fast mode (PP-OCRv6
Tiny and d1-3B), using a fresh process every four images to avoid cumulative
MPS memory exhaustion. It completed 111 scans, passed 91/113 reference texts,
and matched 4,016/4,155 words; two scans returned no complete OCR evidence.
This is a measured result for that mode, not the quality profile or a guarantee
that the 95/113 historical replay transfers to live inference. Clef quality,
cloud OCR/decision providers, the wheel build in this local environment, and
Windows/Linux execution remain unverified. The PR CI workflow builds and smoke
tests the wheel and source distribution.
