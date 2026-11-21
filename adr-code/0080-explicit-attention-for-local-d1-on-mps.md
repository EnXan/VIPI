# ADR 0080: Explicit attention for local d1 on MPS

Status: Accepted, 2026-11-21. Amends the MPS runtime of
[ADR 0044](0044-product-research-recovery.md).

## Context and sources

A folder scan runs many images in one process. With d1 as the local decision
model on a 16 GB Apple M2 (PyTorch 2.11, MPS/FP16), three SVG measurement runs
failed after 13–15 `OcrSession.extract` calls with `MPS backend out of memory
(MPS allocated: 6.79 GiB, other allocations: 13.3–14.0 GiB)`. ADR 0044 already
worked around the same exhaustion by starting a fresh process every four
images. `LocalDecisionModel.ask` calls `torch.mps.empty_cache()` after every
request, so the growth is not held by tensors in PyTorch's cache.

Measurements on 2026-11-21 (M2, no other GPU process):

- Direct d1 visual decisions (completeness assessment and the eight-view
  orientation review) on dataset images ≤ 2080×880: tensors stayed at
  5.82 GiB (the weights), while MPS driver memory after `empty_cache()` rose
  from 7.08 GiB to 11.65 GiB in 15 requests. It rose only for requests with
  new input shapes; repeating a shape added nothing.
- Masked `scaled_dot_product_attention` alone (32 heads, 1024 queries, key
  lengths 3000–3400): driver memory grew by about 1.1 GiB per new key length
  (5.9 GiB after five shapes) and stayed after `empty_cache()`. The same
  computation as explicit matmul and softmax kept 0.001 GiB.
- The SigLIP2 vision tower's SDPA (16 heads, 700–1010 patches) kept about
  0.1–0.18 GiB per new patch count. A tile has up to 1024 patches.

The retained memory belongs to the MPS SDPA kernel, not to VIPI or d1 state.
The causal attention in `vipi.local_attention` (ADR 0044) called it once per
1024-query chunk with an explicit mask, and the key length changes with every
image and question.

## Decision

On MPS only:

- `local_attention.causal_attention` computes each query chunk as
  `softmax(scale·QKᵀ, masked) V` with explicit tensor operations, the softmax
  in FP32. Keys that a chunk cannot see (later tokens, or outside the sliding
  window) are not multiplied; they would only contribute masked zeros. The
  chunk size and full key/value context are unchanged.
- The d1 vision tower uses transformers' `eager` attention
  (`set_attn_implementation("eager")`), the same computation with explicit
  operations.

CPU, CUDA and Clef-Flash are unchanged. `runtime_policy` in the model identity
is unchanged; it records the policy in reports and is not a reuse key.

## Alternatives

- *Call `empty_cache()` more often*: already done after each request; it does
  not release this memory.
- *Pad queries and keys to a few fixed shapes*: bounds the number of kernel
  shapes, but each still keeps about 1 GiB, and padding changes the pinned d1
  attention inputs.
- *Restart the process every few images* (ADR 0044's measurement workaround):
  reloads 6 GB of weights per restart and does not fit `vipi scan` on a folder.
- *Wait for a PyTorch fix*: no release is known that frees it.

## Consequences

Driver memory over 30 direct d1 decisions settled at 6.8–7.5 GiB instead of
reaching 11.65 GiB after 15, and the first 15 requests took 115 s instead of
144 s. Temporary score memory per chunk is in the same range as SDPA's
(FP16 scores and FP32 softmax weights for one chunk). Answers differ from SDPA
only by FP16 kernel rounding: on five dataset images all 20 assessment and
orientation choices were identical, with at most 0.006 difference in a choice
probability.

## Validation boundary

`tests/unit/test_product_recovery.py` checks the exact causal result with and
without a window (CPU) and, on MPS only, that causal attention over five key
lengths and eager SigLIP2 attention over five patch counts keep less than
64 MiB of driver memory; both MPS tests fail with the previous code (5.3 GiB,
0.46 GiB). The end-to-end loop above ran on an Apple M2 with 16 GB. A full
`vipi scan --modus local` of a large folder, M-series machines with other
memory sizes and other PyTorch versions are untested. Other MPS ops may keep
small per-shape state; the measured remainder levelled off at about 7.4 GiB.
