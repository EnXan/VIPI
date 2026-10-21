# ADR 0004: OCR references and evaluation scope

Status: Accepted from existing user instructions. Recorded: 2026-10-19.

## Context and sources

The current dataset instructions distinguish image transcripts, target-only
references, research evaluation and attack detection. Sources are the
[scoped dataset rules](../research/datasets/data/AGENTS.md), [catalog documentation](../research/datasets/data/catalog/README.md)
and [active schema](../research/datasets/data/catalog/ocr/ocr_metadata.schema.json).

## Decision

Keep the simplified index limited to `image`, exact source `text` and source
`category`. Keep provenance, quality, regions, ignored regions and content groups
in separate reports. Preserve raw sources and source transcripts. Treat target
references according to their declared scope; source word order is not a
reconstructed global reading order. Keep related variants together in future splits.

Preserve the full transformation/OCR flow. Text detectors receive the final
assembled OCR reading; dataset references and raw variant readings are not
classifier evidence. Retain variant evidence for inspection and research.
Anamorpher references apply after declared downscaling and do not certify native
visibility. FigStep remains excluded from the current OCR selection.

## Alternatives

Using goals or expected model responses as transcripts would invent image text.
Treating partial references as whole-image transcripts would mis-score unrelated
text. Mixing reference labels into detection would leak evaluation evidence.
Restoring legacy rich-catalog rules would change the agreed simplified contract.

## Consequences

OCR reference quality and attack-detection quality remain separate evaluations.
Research can inspect alternatives and source coverage without changing production
classifier input or raw datasets. Historical selections and Gold claims do not
replace the current catalog.

## Validation boundary

For this guidance change, the active JSON index was read and its 1,676-record
count, category distribution and three-key shape checked. No dataset was rebuilt,
retranscribed or visually reviewed. This does not certify annotation accuracy,
whole-image coverage, attack labels, native Anamorpher visibility or training rights.
