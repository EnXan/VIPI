# 0065 — Clef-Flash replaces Clef

Status: accepted, 2026-11-10. Replaces ADR 0059; amends the local `quality`
mapping of [ADR 0044](0044-product-research-recovery.md).

## Previous decision (ADR 0059, deleted)

ADR 0059 ("Clef-Flash as an optional local decision model") added
`Cloudflare/clef-flash` (post-trained from Qwen/Qwen3.5-9B, 19 GB BF16 files,
revision `fb4417d3`, `joint_schema_model.py` byte-identical to Clef's) as a
third local decision provider next to Clef and d1. Registry entries gained a
`runtime` field (`clef` or `d1`) that selects loading and file checks. Clef
stayed the local `quality` default because no VIPI evaluation supported a
change; the `local-quality-clef-flash` evaluation configuration was added to
produce that evidence. Its rationale: Clef (27.36B parameters, about 55 GB of
weights on MPS/CUDA, about 109 GB on CPU) runs on no available machine, and
quantizing it needed unverified MPS tooling or third-party code. It recorded
the user's decision that Clef-Flash replaces Clef if it evaluates well, after
the one-time test split confirmation.

Reason for revision: on 2026-11-10 the user decided to replace Clef now,
because Clef is too large to run.

## Context and sources

The `local-quality-clef-flash` development run (450 images) completed on an
Apple M4 Pro with 48 GB (Clef-Flash on MPS/FP16, median 14.7 s per image):
75.5 % tolerant word coverage, 13.7 % of attacks and 0 % of benign images
flagged, 55.1 % detection accuracy. 22 of its detections were reused from an
attempt that failed without `accelerate` (fixed by ADR 0064), so its
detection figures are slightly understated. Clef itself has never run on the
VIPI dataset, so no comparison with Clef exists. The test split confirmation
named in ADR 0059 has not been run.

## Decision

- Local `quality` uses `clef-flash` for OCR review and, with detector `auto`,
  for injection detection. The name stays `clef-flash`.
- Clef is removed: its registry entry, the `clef` decision provider and
  detector choice, the `local-quality` evaluation configuration and its
  workbench label. `--decision-provider clef` and `--detector clef` are
  rejected; the error lists `clef-flash`.
- The Clef-family runtime (`"runtime": "clef"`) stays: Clef-Flash uses it.
- `local-quality-clef-flash` stays the evaluation configuration for local
  quality under its name and explicit provider, so its saved baseline stays
  comparable; it is the workbench default. `local-quality-prompt-guard` now
  reviews OCR with Clef-Flash.
- Cached Clef weights (`decisions/clef`) are not deleted automatically.

## Alternatives

- *Wait for the test split confirmation and a Clef comparison*: the agreed
  order in ADR 0059, but a Clef run needs hardware that is not available, so
  the comparison could not be produced.
- *Keep Clef as a non-default option*: keeps a provider no available machine
  can run, with its 55 GB setup path.
- *Quantize Clef*: see ADR 0059; not pursued.
- *Rename `local-quality-clef-flash` to `local-quality`*: shorter, but the
  existing baseline would no longer match.

## Consequences

`vipi setup` for `quality` downloads about 19 GB instead of 55 GB. Local
`quality` memory estimates fall from about 96 GB unified memory / 128 GB RAM
to about 48 GB. Users who passed `clef` must switch to `clef-flash`. The
default's detection quality on the VIPI dataset is weak (13.7 % recall on the
development split); that is a measured property of the new default, not of
this change. Earlier OCR results are not reused, because this change edits
`config.py` (ADR 0058). The product version stays 0.7.0, which is not yet
released.

## Validation boundary

Tests cover the registry (only `clef-flash` and `d1`), the `quality` default,
the rejection of `clef`, setup preparing `clef-flash` for `quality`, the
evaluation configurations and the workbench default and labels. The four saved
baselines stay `fresh`. Clef-Flash inference was validated by the M4 Pro
development run above; CUDA, CPU-only and Windows/Linux runs are untested.
