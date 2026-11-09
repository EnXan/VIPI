# ADR 0046: Reproducible product OCR benchmark over both catalogs

Status: accepted for the requested benchmark.

## Context and sources

The user requested OCR coverage, ≥80%/100% image rates, durations and costs over
all 1,113 entries, overall and by category, for README publication. They selected
local speed and default cloud OCR/providers. The source contracts are
`OcrSession`, the pinned revision in `research/dataset.json`, both catalog adapters,
and evaluation v4. The previous live local 113-image trial used four-image
processes after observed MPS memory growth; its retained summary records 111
completed images and 91 full-reference passes. Those historical results do not
validate this new run.

## Decision

Keep the runner and offline scorer under `research/ocr_eval`, importing production
OCR and existing final-output word matching. Run sequentially without final
injection detection. Freeze inputs, sources and runtime metadata; retain raw
artifacts and terminal per-image records. Score after selection, without sending
references to OCR/review. Preserve failures and unscored outputs in image-success
denominators. Distinguish raw 100% coverage from region-integrity passes, and
word-weighted from mean-image coverage. Label overlapping subsets and sample
counts. Record estimated API fees separately from unmeasured local compute costs.

Recycle local workers after four images to reproduce the observed MPS workaround.
This changes cold-loading frequency and latency; report that overhead rather than
presenting it as warm throughput. Do not impose an image cap or silently retry
failed images. Resume only the same frozen selection and executed sources.

See the [protocol](../docs/ocr-benchmark.md) for exact denominators, pricing sources,
reproduction commands and publication boundaries.

## Alternatives and consequences

The workbench adaptive profile defaults to hosted Decisions even with local OCR;
using it unchanged would not measure the requested fully local configuration.
Running `vipi scan` would include final injection-detector time/cost in an OCR
measurement. Reusing historical/replayed decisions would not measure current
live decisions. A single long-lived local worker avoids repeated loading but
previously exhausted MPS memory. Parallel configurations would compete for local
resources and cloud-client processing time. These alternatives are not used.

Process recycling makes results specific to the stated host and protocol.
Retaining artifacts costs disk space. The catalogs include development examples,
related variants and repeated files; their benchmark supports a scoped dataset
claim, not independent general-purpose OCR accuracy or scanner recall.

## Validation boundary

Offline checks cover routing, retained failures, denominators, integer thresholds,
overlapping facets, paired source manifests, interrupted checkpoints, cache fees
and parity with the existing final-output evaluator. The measured run completed
all 1,113 local attempts and all 1,113 corrected cloud attempts (1,100 completions,
13 provider failures). An initial cloud-only polygon/box serialization bug was
fixed before the fresh full cloud trial; original failures and fees remain
separate. Local inference branches were AST-identical. Usage was repriced after
inference to include observed cache writes/reads without changing OCR selection.
See the protocol and linked report for actual counts, source/runtime metadata,
denominators and limits. These observations do not establish holdout accuracy.
