# OCR evaluation

OCR metrics and the benchmark that scans the evaluation dataset
(`research/dataset/`, read through [`research/catalog.py`](../catalog.py)).
`evaluation/` holds the word metrics (`metrics.py`, `words.py`),
`benchmark.py` runs the product scan over the dataset and
`benchmark_report.py` scores the retained outputs. Comparisons with a baseline
run through [`research.evaluate`](../evaluate/README.md). Retained trials live
under `experiments/` and [historical reports](reports/README.md) keep measured
results; see [product recovery](../../docs/ocr-recovery.md) for the selected
workflow and [the full product benchmark](../../docs/ocr-benchmark.md).

An entry's OCR reference (`ocr_reference` in the catalog) holds the exact
transcript, its scope (`source_declared_text` or `primary_visible_payload`),
quality, whether the reading order is known and word regions where the source
supplies them. Preserve exact source transcripts, provenance and reference
annotations; change them through the [Dataset page](../workbench/README.md#dataset)
and the [dataset contribution flow](../README.md#add-images).

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
