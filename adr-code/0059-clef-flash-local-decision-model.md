# 0059 — Clef-Flash as an optional local decision model

Status: accepted, 2026-11-10.

## Context and sources

Local `quality` uses Clef (`Cloudflare/clef`, 27.36B parameters, 55 GB BF16
files), which VIPI loads unquantized: about 55 GB of weights on Apple MPS and
CUDA, about 109 GB on CPU (`docs/models.md`). It therefore does not run on
typical laptops, including the user's M4 Pro with 48 GB. The user asked on
2026-11-10 whether Clef can be quantized. The investigation
(`.llm-plans/clef-memory.md`) found:

- Clef is a fine-tune of Qwen/Qwen3.8-27B plus a small joint schema head; one
  forward pass returns option probabilities, no text generation.
- Cloudflare publishes `Cloudflare/clef-flash` (post-trained from
  Qwen/Qwen3.5-9B, 19 GB BF16 files, Apache-2.0). At revision
  `fb4417d3`, its `joint_schema_model.py` is byte-identical to Clef's pinned
  runtime code (same SHA-256). Its model card reports Decision Index results
  close to Clef's (higher on many benchmarks, lower on e.g. PhishNChips 75.0
  vs 79.6); these are vendor results, not VIPI measurements.
- Quantizing Clef is possible (its loader forwards `from_pretrained` keyword
  arguments; the output embedding must stay unquantized because the head reads
  its rows), but on Apple MPS the tooling and speed are unverified, and
  community quantizations bring third-party code.

The user chose to try Clef-Flash first.

## Decision

- `clef-flash` is a third local decision provider, pinned in
  `src/vipi/decision_models.json` with its revision and the same code hash as
  Clef. Each entry now names its `runtime` (`clef` or `d1`); runtime-specific
  loading and file checks (joint head) follow the runtime instead of the name.
- It is selectable for OCR review and detection
  (`--decision-provider clef-flash`, `--detector clef-flash`) and prepared by
  `vipi setup` with the same options. Defaults are unchanged: Clef for local
  `quality`, d1 for `balanced` and `speed`.
- The evaluation gets `local-quality-clef-flash` (quality OCR, Clef-Flash for
  review and detection); the workbench offers it as detector Clef-Flash for
  local Quality.
- Code that listed `clef` and `d1` explicitly now uses
  `LOCAL_DECISION_PROVIDERS`.

## Alternatives

- *Quantize Clef* (transformers quantization config, MLX, or a community
  conversion): keeps the larger model, but needs unverified MPS tooling or
  third-party code, and a Clef reference run that no available machine can
  produce. Deferred until Clef-Flash is evaluated.
- *Make Clef-Flash the `quality` default now*: no VIPI evaluation supports it.

## Consequences

The product version rises to 0.7.0. Saved baselines stay `fresh`, because the
evaluation identity now covers only the registry entries a configuration uses
([ADR 0060](0060-model-identity-per-used-entry.md)). Earlier runs' results are
not reused, because ADR 0058 requires identical OCR sources and this change
edits `config.py` and OCR modules.

If Clef-Flash evaluates well, the user decided on 2026-11-10 that it replaces
Clef: it becomes the local `quality` default under its own name `clef-flash`,
and Clef is removed (registry entry, provider choice, evaluation configuration,
documentation). That change needs its own evaluation evidence, including the
one-time test split confirmation before a default changes.

## Validation boundary

Tests cover the registry entry (repository, 40-character revision, runtime,
identical code hash), option resolution and the local/cloud conflict, the
joint-head check for Clef-runtime models, the evaluation configuration and the
workbench label. The pinned `joint_schema_model.py` hash was computed from the
downloaded file at the pinned revision. Clef-Flash weights were not downloaded
and no Clef-Flash inference has run: the 16 GB development Mac cannot hold
them. Inference, memory use on Apple MPS and quality on the VIPI dataset need
a run on a larger machine (planned: M4 Pro, 48 GB).
