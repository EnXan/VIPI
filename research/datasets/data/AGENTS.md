# Dataset instructions

These instructions apply to dataset work and the corresponding tools under
`research/datasets/`. Follow the root working agreement as well. The authoritative
current layout and rebuild workflow are described in
[catalog/README.md](catalog/README.md).

## Current OCR contract

- The active index is `research/datasets/data/catalog/ocr/ocr_metadata.json`, an array containing
  only `image`, `text` and `category`. Its schema is
  `research/datasets/data/catalog/ocr/ocr_metadata.schema.json`.
- Image paths are repository-relative references to originals, reviewed global
  filter variants or Anamorpher originals. `text` is the exact source transcript;
  `category` identifies the source. Do not infer missing image text from goals,
  prompts, judge questions, expected answers or surrounding metadata.
- Inspect the actual catalog and source records before reporting counts or
  quality. The selection checked on 2026-10-19 contains 1,000 base images plus
  676 Anamorpher cases. The base is 500 TextOCR images and 125 each from
  CyberSecEval3, MM-SafetyBench, Dagger7164 and VPI-Bench. FigStep and FigStep-Pro
  are excluded. Sampling is without replacement and deduplicates identical bytes;
  it does not assign difficulty or presumed attack-frequency rankings.
- Keep provenance, source scope, reference quality, regions, content groups and
  usage information in `ocr_selection_report.json`. Source references are Silver;
  Anamorpher references are `synthetic_reference`.
- A target-only reference is not a whole-image transcript. Do not score unrelated
  background/UI text as an OCR error. Keep variants of the same content group
  together in any future split. OCR eligibility is not training permission.
- TextOCR words retain source order and newline separators; they have no guaranteed
  global reading order. Exclude `.` placeholders from text but retain their
  `ignored_regions`. Evaluate word-region matches rather than an invented
  image-wide reading order. Local sources are `TextOCR_0.1_train.json` and
  `train_images/` under `research/datasets/data/external/text-ocr/`.
- CyberSecEval3 cases without `image_text` (100 CAPTCHA judge targets) and the
  locally missing `4.png` are excluded. Do not invent transcripts for them.

## Images and generation

- Preserve raw data under `research/datasets/data/external/`; never use Trash or cache as a
  substitute source. Inspect a new source's suitability, coverage and gaps before
  importing it; import only within an authorized dataset task.
- The base references 150 reviewed whole-image filter variants under
  `research/datasets/data/derived/ocr_obfuscation/v1/images/`, selected with seed 20261004:
  30 each for Gaussian blur, motion blur, noise, JPEG artifacts and resolution
  loss. The remaining 850 base records reference originals. Text, category,
  dimensions and raw sources stay unchanged.
- `ocr_obfuscation_manifest.json` records parameters, visual review and hashes.
  `.clean.json` snapshots preserve the pre-filter selection. `render` resets
  visual review; never activate regenerated variants without review. Visual review
  is not a Gold transcription of every hard-to-read word.
- Anamorpher has three generators (Nearest with all four offsets), two profiles,
  two target sizes, nine alignments, two font sizes, two text-free backgrounds and
  two texts: 1,728 generated combinations. Precheck all twelve downsampler
  combinations and OCR-check the selected whole-image reveal again. Keep failed
  cases as controls outside the index; do not launch concurrent generator runs.
- Its reference scope is `target_text_only_after_declared_downscale`, not proof
  of native visibility. Keep seeds, parameters, hashes and results in
  `research/datasets/data/catalog/ocr/anamorpher_manifest.json`; variants of one payload share
  a content group. The 1,052 failed controls remain available outside the index.

## Rebuild and inventory

For a fresh checkout, install the raw sources for the active OCR selection from
the repository root:

```bash
uv sync --extra research
uv run python -m research.datasets.setup
```

The setup command reads the active source IDs from `catalog/ocr/ocr_datasets.csv`
and their URLs/paths from `catalog/datasets.csv`. It skips sources that already
have their required files and downloads missing raw data under `data/external/`.
External and generated dataset files are ignored by Git. The command does not
rebuild the selected catalog or regenerate derived images.

Run these steps only for an authorized rebuild, from the repository root:

```bash
.venv/bin/python research/datasets/build_ocr_metadata.py --count 1000 --seed 42 --textocr-share 0.5
.venv/bin/python research/datasets/obfuscate_ocr_images.py apply
.venv-anamorpher/bin/python research/datasets/generate_anamorpher_ocr.py append
.venv/bin/python research/datasets/inventory_datasets.py
```

`apply` uses reviewed variants; it is not a substitute for reviewing a new
`render`. Check the catalog state and coordinate shared changes before rebuilding.
`research/datasets/data/catalog/ocr/ocr_datasets.csv` lists the six current sources;
`research/datasets/data/catalog/datasets.csv` is the full inventory, including FigStep's OCR
exclusion. The full inventory describes available local sources; the active OCR
selection is defined only by `ocr_metadata.json` and its selection report.
