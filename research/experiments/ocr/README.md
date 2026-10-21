# OCR experiments

These tools evaluate OCR transformations against the active dataset references.
They do not change the public scan workflow or dataset files. Read
[`research/datasets/data/AGENTS.md`](../../datasets/data/AGENTS.md) before
changing catalog data or references.

Run the experiments from the repository root in the OCR environment described
in the [workbench guide](../../workbench/README.md). The reusable screening
command freezes its image selection, model and source hashes in a new run
directory:

```bash
.venv-ocr/bin/python -m research.experiments.ocr.ocr_screening --help
.venv-ocr/bin/python -m research.experiments.ocr.ocr_screening prepare runs/ocr-screening/NAME
.venv-ocr/bin/python -m research.experiments.ocr.ocr_screening run runs/ocr-screening/NAME --stage views
.venv-ocr/bin/python -m research.experiments.ocr.ocr_screening report runs/ocr-screening/NAME
.venv-ocr/bin/python -m research.experiments.ocr.ocr_screening plan-filters runs/ocr-screening/NAME
.venv-ocr/bin/python -m research.experiments.ocr.ocr_screening run runs/ocr-screening/NAME --stage filters
.venv-ocr/bin/python -m research.experiments.ocr.ocr_screening report runs/ocr-screening/NAME
```

Inspect the selected images and source references before running OCR. Record
reference concerns in the run's review files; keep source transcripts and the
active index unchanged. A report is complete only when every planned view has a
saved observation. The report separates the emitted text from diagnostic token
coverage across views.

Each run stores its manifest, source snapshot, selected inputs, OCR observations
and analysis under `runs/ocr-screening/NAME/`. Resource measurements and
reference audits are local experiment outputs. `research/experiments/reports/`
holds local summaries and is ignored by Git.

Round-specific drivers implement fixed OCR protocols. Their available commands
are:

```bash
.venv-ocr/bin/python -m research.experiments.ocr.ocr_round2 --help
.venv-ocr/bin/python -m research.experiments.ocr.ocr_round3 --help
.venv-ocr/bin/python -m research.experiments.ocr.ocr_round4 --help
.venv-ocr/bin/python -m research.experiments.ocr.ocr_round5 --help
```

The raw model comparison isolates OCR model quality from the transformation
pipeline. It selects unfiltered images from held-out content groups, runs one
direct OCR call per image, and reports results by source. New candidate screens
exclude Tesseract. The earlier fixed comparison is retained as a historical run
and is not part of future candidate sets. Anamorpher is excluded from raw-image
screens because its reference applies only after its declared downscale.

```bash
.venv-ocr/bin/python -m research.experiments.ocr.ocr_candidate_screen prepare runs/ocr-model-comparison/NAME --models ppocr-v6-small ppocr-v6-medium lightonocr-3-0.8b lightonocr-3-1b lightonocr-3-4b florence-2-base-ft florence-2-large-ft --count-per-source 2 --seed 20261020
.venv-ocr/bin/python -m research.experiments.ocr.ocr_candidate_screen run runs/ocr-model-comparison/NAME
.venv-ocr/bin/python -m research.experiments.ocr.ocr_candidate_screen report runs/ocr-model-comparison/NAME
```

The first candidate screen uses two images per source (10 total) to keep inference
manageable on CPU. Preparation pins the selected Hugging Face model revisions,
freezes the sample, model hashes and environment in the run manifest, and reuses
reviewed references from the prior 49-image holdout when image and reference data
match exactly. Inspect generated `contact-*.jpg` sheets and review any remaining
pending references before running inference.

The local CPU screen includes PP-OCRv6 Small/Medium, three LightOnOCR-3 sizes,
and Florence-2 Base/Large fine-tuned. Surya OCR 2 remains registered, but this
environment lacks its documented `surya-ocr` inference runtime and `llama-server`;
the generic Transformers call produced layout output rather than OCR and is
blocked from being scored. A candidate failure is recorded and does not stop the
other models. The run records model revisions and file hashes,
environment, input hashes, per-image OCR output, source-aware coverage, wall time
and peak memory. It does not invoke VIPI transformations or assembly. LightOnOCR
runs in its documented transcription-only mode. When an unordered TextOCR
reference has no predicted word boxes, the report labels its score as
`unordered_token_multiset`; it measures token coverage without imposing a
reading order and does not measure localization. Generative candidates use
bounded output lengths in this screen to avoid runaway OCR decoding on CPU.

Florence-2's pinned Transformers implementation requires these additional
packages in the local OCR environment:

```bash
uv pip install --python .venv-ocr/bin/python torchvision==0.21.0 timm==1.0.20 einops==0.8.1
```

Use a new run directory when preparing a new experiment. Do not overwrite or
recompute completed local runs. The `analyze_ocr_screening` and
`analyze_ocr_round*` commands summarize saved observations; they do not run OCR.
