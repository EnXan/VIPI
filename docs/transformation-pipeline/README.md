# Transformation Pipeline

Local image-to-text extraction through CLI or a live web interface. Each image
passes through the fixed scaling, rotation, tiling and filter sequence. OCR runs
and saves its result after every adjustment. At the end, matching text locations
are combined into one primary reading; disagreements remain separate. Selected
dataset images can be checked against their annotated text.

## Setup

Use Python 3.12. Tesseract 5 must be installed separately if using that adapter
(`brew install tesseract` on macOS).

```bash
UV_PROJECT_ENVIRONMENT=.venv-ocr uv sync --python 3.12 --locked --extra ocr --extra test
.venv-ocr/bin/python -m ocr_pipeline prepare-models
```

Model preparation downloads pinned files and verifies SHA-256 checksums.
Extraction and the bundled VIPI web interface work locally without downloads.

### Ubuntu with an NVIDIA GPU

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and an NVIDIA
driver compatible with CUDA 12.8 or newer. `nvidia-smi` must show your GPU before
starting. From the project root, use the CUDA extra instead of the CPU extra:

```bash
nvidia-smi
UV_PROJECT_ENVIRONMENT=.venv-ocr uv sync --python 3.12 --locked --extra ocr-cuda --extra test
.venv-ocr/bin/python -m ocr_pipeline prepare-models --model ppocr-v6
.venv-ocr/bin/python -m ocr_pipeline serve
```

Open http://127.0.0.1:8000, choose **NVIDIA CUDA** and start with **1–2 workers**.
Each worker owns its model sessions and consumes GPU memory. Compare a few scene
images, screenshots and Anamorpher images before starting all 1,676 records.
The default remains CPU; CUDA is always selected explicitly.

The CUDA extra installs `onnxruntime-gpu` and its NVIDIA CUDA/cuDNN libraries.
The application preloads those libraries before creating sessions and rejects a
detector or recognizer that falls back entirely to CPU. An available provider
alone does not confirm a working driver; the first model load performs this check.
CUDA permits individual unsupported operations to run on CPU. Provider lists and
per-step timings are saved with the results. See the
[ONNX CUDA requirements](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html).
TF32 is disabled, and convolution selection uses HEURISTIC to avoid exhaustive
benchmarking for each image size. GPU readings can still differ from CPU readings.

`ocr` and `ocr-cuda` are mutually exclusive: both runtime packages provide the
same Python module and must not be installed together. `uv sync` selects the
appropriate one from the lockfile. PyTorch uses CPU wheels for resizing under
Linux/Windows, and TensorFlow resizing uses CPU with its GPU devices hidden so
that it does not reserve the OCR GPU's memory. The transformation sequence,
image dimensions, sampling methods and reference annotations remain the same.

### Windows with an NVIDIA GPU

The same CUDA extra works in native Windows. In PowerShell:

```powershell
nvidia-smi
$env:UV_PROJECT_ENVIRONMENT = ".venv-ocr"
uv sync --python 3.12 --locked --extra ocr-cuda --extra test
.venv-ocr\Scripts\python.exe -m ocr_pipeline prepare-models --model ppocr-v6
.venv-ocr\Scripts\python.exe -m ocr_pipeline serve
```

### Move the selected dataset to another computer

Git contains code, the active OCR index, reports and manifests. Local data under
`datasets/external/` and `datasets/derived/`, downloaded models and scan runs are
excluded. Copy the two data directories separately, preserving paths relative
to the repository root. The active index can be used as a file list if copying
only the selected images. For example, on the Mac:

```bash
.venv/bin/python -c 'import json; from pathlib import Path; print("\n".join(item["image"] for item in json.loads(Path("datasets/catalog/ocr/ocr_metadata.json").read_text())))' > /tmp/vipi-ocr-images.txt
rsync -av --files-from=/tmp/vipi-ocr-images.txt ./ /path/to/PC/VIPI/
```

Replace the destination with your mounted transfer directory or an SSH
destination. This copies exactly the active images, including filter variants
and Anamorpher originals; the Git-tracked index retains their transcriptions.
Do not regenerate the dataset to move it. Create a fresh Python environment on
the PC and prepare model files there; Mac virtual environments are not portable.

## Web

```bash
.venv-ocr/bin/python -m ocr_pipeline serve
```

Open http://127.0.0.1:8000. Upload, drop or paste an image and select PP-OCRv5,
PP-OCRv6 medium (default) or Tesseract. Choose 1–8 parallel workers (default: 4).
Each worker has its own OCR instance. Click a worker to follow its live steps.
The CPU thread budget is divided between workers (on an 8-core CPU: 4×2 or 8×1).
Select **Apple CoreML** on supported Macs to let Apple place supported model parts
on CPU, GPU or Neural Engine; other parts can run on CPU. Tesseract uses CPU only.
CPU remains the default. CoreML is experimental: model compilation/first inference
can be slow, and speed and OCR readings must be checked for the chosen images.
On NVIDIA-equipped Linux/Windows installations, select **NVIDIA CUDA**.
Watch each adjusted image, its OCR boxes
and extracted text. Open completed variants during processing; return with Live.
The final view includes every variant and the combined text, with TXT/JSON
downloads. Expand Abweichende Lesarten to inspect competing readings. Reloading
the run URL restores its saved state.

### Dataset selection and evaluation

Open **Datensatzbilder auswählen**, filter by source category or search by filename
or reference text. Select individual images or all matching results, then start.
Images run one after another; each uses the chosen 1–8 OCR workers.

The active selection comes from `datasets/catalog/ocr/ocr_metadata.json`; reference
scope, quality and word regions come from `ocr_selection_report.json`. Raw images
and annotations are never modified or passed to OCR as hints.

Valid means the full reference is recognized in a variant or the assembled text.
Extra OCR text is allowed, including background/UI text. Comparison normalizes
Unicode, case and whitespace, preserves punctuation and spelling, and allows
extra tokens between reference tokens. TextOCR uses one-to-one exact token matches
in overlapping word-region bounds (at least 50% of the smaller box), ignoring
global reading order; words found across variants can complete the reference.
Ignored regions are excluded.

The report separates pipeline detection from final-text retention. It shows
missing reference tokens, each variant's coverage and paired effect comparisons:
filters versus the same unfiltered view; scaling, rotation and tiles versus the
unfiltered original. Effect counts describe variant comparisons, not image counts.
The selection report lists valid, incomplete and technically failed images;
processing continues after individual errors. Click an image after completion
to inspect its variants. Source/Silver references may themselves be incomplete.
At the end, a category chart shows valid/incomplete/error counts and the valid
share of processed images in this selection. Pending images are excluded;
untested categories have no percentage. Click a category to filter the image
report. These counts are also included in `summary.categories` in its JSON.

## CLI

```bash
.venv-ocr/bin/python -m ocr_pipeline extract image.png --model ppocr-v6 --workers 4
.venv-ocr/bin/python -m ocr_pipeline extract image.png --backend coreml --workers 2
.venv-ocr/bin/python -m ocr_pipeline extract image.png --backend cuda --workers 1
.venv-ocr/bin/python -m ocr_pipeline extract image.png --model tesseract --json --output result.json
.venv-ocr/bin/python -m ocr_pipeline reassemble RUN_ID
.venv-ocr/bin/python -m ocr_pipeline extract ANNOTATED_IMAGE --evaluate --json
```

Model IDs: `ppocr-v5`, `ppocr-v6`, `tesseract`. Progress goes to stderr;
recognized text or JSON goes to stdout. `--output` also saves that output.
`extract --workers 1` runs sequentially; the default is 4 and the maximum is 8.
`--evaluate` uses the active annotation for the supplied dataset image. Evaluation
details are included in JSON; the concise verdict goes to stderr.
`reassemble` updates a completed run from its stored OCR results, without running
OCR again or changing the raw step records. Refresh its web page afterwards.
`extract` and `serve` accept `--models-dir` and `--runs-dir`; `reassemble` accepts
`--runs-dir`. The web command also accepts `--port`. `vipi-ocr` provides the same
commands when the environment is activated.

## Saved results

Each run writes `runs/<run-id>/`: `images/` contains every adjusted PNG,
`steps.jsonl` the immediately saved text, native boxes, input-coordinate mappings
and OCR preprocessing details. `events.jsonl` supports live event replay;
`status.json` records progress. Completed runs add `result.txt` and `result.json`.
A failed/interrupted run retains prior steps and has no completed result.
Evaluated results include the reference snapshot and coverage/effect report under
`evaluation`. Selection runs write `runs/batches/<batch-id>/report.json`, updated
after each image and downloadable in the web interface. Reloading the selection
URL restores its progress and individual run links.
Workers process views concurrently, preserving adjust → OCR → save within each
worker. A selection batch reuses one OCR instance per executor thread across
images; an inference failure discards that thread's instance before the next
image. Completed run event histories are released from the batch's memory and
can be restored from disk when opened. Steps are saved on completion; the overview and final assembly use the
fixed variant order. More workers require more model memory. CPU threads are
bounded per worker (Tesseract via its subprocess environment; RapidOCR via ONNX).
OpenCV uses one thread because image variants already run concurrently.
Results record `backend`, `threads_per_worker`, wall-clock `elapsed_seconds` and
per-step transformation, PNG-save and OCR times. RapidOCR records each session's
provider list; this does not prove every operation used GPU/Neural Engine.
CoreML caches compiled model parts in `models/ocr/coreml-cache/`.

Assembly aligns observed lines in input coordinates and uses Levenshtein
similarity, agreement across views and native OCR confidence to select a reading.
Filters of one view contribute at most one vote. Recognized words outside a
partially covered line can extend it when they share a spatial/text anchor.
No dictionary rewrites names, codes or unknown words. The main text is a selected
reading, not a guarantee of correctness; other readings remain in
`regions[].alternatives` and all raw texts in `variants`. Consumers needing every
reading, including a different payload exposed by scaling, should inspect these
alternatives too. `assembly_version` identifies the result format.

Supported inputs: static PNG/JPEG/WebP, up to 40 MP; required views must fit
80 MP. EXIF orientation is applied before transformations; coordinate mappings
refer to that decoded input. Alpha is composited on white. RapidOCR only resizes
detection input to multiples of 32 and records recognition crop resizing.
The sequence has 160 full-image OCR passes plus five per tile; larger images
produce more tiles and require more processing time, storage and model memory.

## Functional checks

```bash
.venv-ocr/bin/pytest -q
.venv-ocr/bin/ruff check src/ocr_pipeline tests
```
