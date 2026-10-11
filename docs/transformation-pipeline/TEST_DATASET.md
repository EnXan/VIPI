# Transformation Pipeline Test Dataset

## Selected-image checks and deferred benchmark

The web interface now checks user-selected images using the reference-coverage
rule in [README.md](README.md#dataset-selection-and-evaluation). Extra OCR text
is allowed. Annotations are used after OCR, never to guide recognition.

The remaining sections retain context for a future formal corpus benchmark,
including its stricter normalization and geometry metrics. That benchmark,
splits and model ranking are not implemented or run by the selected-image check.
Stored reveal images are audit evidence, not substitute OCR inputs.

## Inputs

Use every image referenced by datasets/catalog/ocr/ocr_metadata.json. Read the
current array length; do not hardcode 1000 or create a separate test-image corpus.
Each record contains only image, text and category. Read annotation scope,
regions, ignored regions, provenance and content groups from the accompanying
ocr_selection_report.json.

Use active image paths exactly, including reviewed derived filter images; do
not replace them with clean originals. Identify filtered cases through the
existing obfuscation manifest and report them separately. The current index has
1676 entries: the original 1000 (including 150 filtered inputs) plus 676 accepted
Anamorpher cases. Do not generate or add extra evaluation cases.

Validate the current schema, unique paths, decodeability, report alignment and
image hashes. Freeze these inputs per run; changed inputs require a new run.
Anamorpher is included in the current schema. Its report entries provide downscale
and generation_manifest: resolve records in anamorpher_manifest.json by sample_id.
The downscale fields identify backend, method, target_dimensions and the recorded
reveal image/hash; manifest records contain seeds, parameters and source hashes.
Read these as audit evidence, not substitute OCR inputs or model answers.

The generated grid has 1728 cases; only the 676 accepted cases are indexed. The
1052 failed controls, including every nearest-offset-3 case, remain excluded.
The active cases contain two payload texts, two sizes, two profiles, nine
alignments, two font sizes and two backgrounds (659 flat, 17 tiled). These are
synthetic_reference labels with scope target_text_only_after_declared_downscale;
neither native invisibility nor exhaustive human readability is certified.
Acceptance used Tesseract on a known-region grayscale/autocontrast patch after
full-frame downscaling. Its >=0.95 score ignored punctuation/case and required
>=3 gray levels of stroke contrast. Do not reuse this gate as pipeline scoring.
The twelve probe results came from padded windows; the selected full-frame
reveal is authoritative. Test whole-frame inference without annotation crops.

## Development and holdout

For the base sources, split complete content groups with seed 42, aiming for
80/20 and balanced source representation. Anamorpher has only two groups:
anamorpher_payload_blue (359 cases) goes to development; anamorpher_payload_orange
(317) goes to holdout. Never split variants of either payload across sets.
An 80/20 Anamorpher split is impossible under this contract; report actual ratios
and do not claim statistical generalization to arbitrary attack payloads.
Persist the split with the run.
Select engines and transformations on development cases only; evaluate the
frozen holdout once. New imports create a new benchmark version. Synthetic
unit-test fixtures test implementation logic and are not benchmark additions.

## Scoring

Preserve exact source transcripts. For comparison only, apply Unicode NFC and
collapse whitespace; retain case and punctuation.

- TextOCR: match native word polygons one-to-one at polygon IoU >= 0.5. Measure
  character errors and word recovery; missing words incur deletion errors.
  Source annotation order is not a required global reading order. Treat ignored
  word regions individually; never discard a mixed line or its labeled words.
- MM-SafetyBench: score detections centered in the annotated target regions,
  using local reading order. Do not score unrelated background text as errors.
- Without regions: report count-sensitive reference-token recovery as an
  unlocalized diagnostic, not whole-image CER or localization accuracy.
- Anamorpher: score payload recovery after the declared downscale, not native
  invisibility. Regions are bbox_xywh in source pixels; divide by four for the
  declared target and use actual mappings for other views. Compare declared
  reproduction with the general scan. Native-image OCR is a separate diagnostic.
  Use only imported references; keep case/punctuation in pipeline scoring.

Neither target_text_only nor source_declared_text certifies a full transcript.
Silver references remain Silver. Extra OCR text is unassessed where coverage is
unknown; the corpus cannot establish general full-image precision or false
positive rates. Never call unassessed text a hallucination by default.

## Reports and acceptance

Report originals, individual variants and the actual output union separately.
Keep main-reading scores separate from alternative-hit scores; deduplicate
reference matches and never choose the best variant using ground truth.
Aggregate by source, filtered/unfiltered inputs and scaling implementation.
Report Anamorpher by payload, generator, nearest offset, profile and background;
keep its Tesseract-biased results separate from the base-source quality ranking.
Include missed reference text, candidate counts, regressions, uncertainty,
warm/cold runtime, throughput, peak process-tree memory and execution status.

Only comparable localized references determine the quality ranking; report
its coverage explicitly. Incompatible word geometry makes it incomplete.
Latency is secondary; incomplete runs cannot win by skipping expensive cases.
Require preserved original results, correct processing traces and added
reference recovery before enabling a transformation family. Report holdout
results and limitations without a universal extraction percentage guarantee.
