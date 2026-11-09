# OCR evaluation

This directory contains the OCR reference catalog and the evaluation code used
by the local workbench. The 1,000 selected images live in `images/`, alongside
the single `catalog.json` index. Both are downloaded from the pinned
[Hugging Face dataset](https://huggingface.co/datasets/EnXan/VIPI-evaluation)
and ignored by Git. From the repository root:

```bash
uv run python -m research.download
```

`evaluation/` owns catalog loading, metrics and the workbench adapter.
The shared scanner recovery lives in `vipi.ocr.recovery`; retained trials live
under `experiments/`. See [product recovery](../../docs/ocr-recovery.md) for the
selected workflow, [the baseline protocol](BASELINE.md) for active comparison
models, [the full product benchmark](../../docs/ocr-benchmark.md) for reproducible
local/cloud runs, and [historical reports](reports/README.md) for measured trial results.

The catalog preserves exact transcripts, source references, rights, reference
scope and word regions. Catalog image paths are relative to this directory.
Downloading on another machine retrieves the same selected images and labels.

Each record contains `id`, `image`, `text`, `category`, `scope`, `quality`,
`reading_order_known`, `regions` and `source`. `source` preserves the upstream
sample identifier, SHA-256 image hash, repository, provenance and usage rights.
`regions` can be null when the source supplies no word positions. Keep the
distinction between a reference covering only target text (`target_text_only`)
and one covering source-declared text (`source_declared_text`).

The workbench reads references without modifying them. Preserve exact source
transcripts, provenance and reference annotations. Submit changes to images and
labels together as a dataset PR following the
[image contribution instructions](../README.md#add-images).

The current improvement goals are a 90% OCR quality line and a separately
measured 90% scanner recall line. These are targets, not achieved quality claims.
Report final payload word coverage per image, exact completion, encoded-text
character fidelity and additional text separately; choose and record aggregation
and test splits before making a target claim. OCR coverage does not measure
scanner recall. Evaluation v4 makes tolerant reference-word coverage in the
final scanner text primary: all reference words covered means a case passes. Literal,
case-sensitive word fidelity is reported separately. Coverage tolerates one edit
for normalized words of 2–9 characters, and 20% rounded down for longer words;
single characters must match. It ignores case and punctuation, preserves known
reference order, requires distinct observations for repeated words, and can join
adjacent OCR fragments within a reference word. Independent annotated regions
ignore order between regions but preserve word order inside each region. An OCR
box spanning multiple independent regions causes a group conflict and prevents a
pass. Exact words retain their literal case and attached symbols. Historical
reports keep their old evaluation version. This measures the annotated reference
scope, which may be only the payload, and does not establish semantic equivalence
or full-image text localization.
See [ADR 0028](../../adr-code/0028-independent-ocr-payload-regions.md) for matching rules,
tradeoffs and validation boundaries, and
[ADR 0044](../../adr-code/0044-product-research-recovery.md)
for the contrast improvement and its measured limits.
