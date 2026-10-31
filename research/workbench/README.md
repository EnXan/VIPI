# OCR Workbench

Local image-to-text extraction through CLI or a live web interface. The default
**Original only · baseline** profile runs each original decoded image once and
preserves the backend's text without VIPI transformations or assembly. PP-OCR
uses native RapidOCR processing with the pinned model weights. Select
**Previous VIPI pipeline · control** explicitly to replay the existing variant
and assembly profile. Selected dataset images are checked against their annotated
text. See the [candidate inventory and experiment protocol](../ocr_eval/BASELINE.md).

The optional **Jev · adaptive transformations** profile selects a measured
transformation from the image, runs native OCR with the reviewed PDFMiner
grouping, then lets Jev review the image and extracted text. It retains earlier
attempts and permits up to three OCR attempts, each starting from the original.
Set `TYPESAFE_API_KEY` or `JEV_API_KEY` to use it. This explicitly sends image
previews and OCR text to TypeSafe; it is an experimental profile, not the default.

```bash
uv run python -m research.workbench extract path/to/image.png \
  --model ppocr-v6-tiny --ocr-profile adaptive-jev --workers 1 --json
```

Only Jev previews are resized to its documented 280–1568-pixel dimensions;
OCR retains the selected raster's full resolution. Each run saves native and
grouped readings, `attempts.json`, `decisions.json`, request descriptions,
actual preview images and raw responses under `decisions/`. `selection.accepted`
is Jev's opinion, separate from reference-based evaluation. Jev pricing is not
configured, so the total API cost is reported as unknown. See the
[nine-image experiment](../ocr_eval/ADAPTIVE_JEV.md) and
[ADR 0029](../../adr-code/0029-adaptive-ocr-transformation-review.md).

## Setup

Use Python 3.12. Tesseract 5 must be installed separately if using that adapter
(`brew install tesseract` on macOS).

```bash
UV_PROJECT_ENVIRONMENT=.venv-ocr uv sync --python 3.12 --locked --extra ocr --extra research --extra test
.venv-ocr/bin/python -m research.workbench prepare-models
```

PP-OCR and Tesseract model preparation downloads pinned files and verifies
SHA-256 checksums. Document VLM setup uses upstream model caches. API OCR sends
images to its selected provider; local OCR uses the prepared model files.

### Optional document VLMs

The Workbench also offers PaddleOCR-VL 1.6 and Granite-Docling 258M. They run
through their upstream full-page document pipelines and use one worker per run.
On Apple Silicon PaddleOCR-VL uses its official PaddlePaddle CPU path; Docling
uses its official Granite Transformers pipeline. These are available in the
evaluation Workbench only, not in the public `vipi scan` command.

Use a dedicated Workbench environment for the document VLMs. PaddleOCR brings
its own OpenCV distribution, so this environment intentionally omits VIPI's
`ocr` extra (and its separate OpenCV wheel). The Workbench selects the standard
or VLM interpreter per model, so one queue can use both environments.
Upstream model caches are stored under the ignored `models/ocr/` directory by
default (override `HF_HOME`, `MODELSCOPE_CACHE` or `PADDLE_PDX_CACHE_HOME` to
use a different local cache).
Install both runtimes together, then prepare each model once:

```bash
UV_PROJECT_ENVIRONMENT=.venv-ocr-vlm uv sync --locked --python 3.12 --extra research --extra test --extra ocr-paddle-vl --extra ocr-granite-docling --extra ocr-lighton
.venv-ocr-vlm/bin/python -m research.workbench prepare-models --model paddleocr-vl-1.6
.venv-ocr-vlm/bin/python -m research.workbench prepare-models --model granite-docling-258m
.venv-ocr/bin/python -m research.workbench serve
```

The first preparation run downloads model assets through the selected upstream
pipeline and may take time. PaddleOCR-VL supports a local MLX-VLM inference
service as an alternative; configure `PADDLEOCR_VL_SERVER_URL` and optionally
`PADDLEOCR_VL_API_MODEL` to use it. See the official
[PaddleOCR-VL pipeline guide](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL.html),
[Apple Silicon setup](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL-Apple-Silicon.html)
and [Granite-Docling model card](https://huggingface.co/ibm-granite/granite-docling-258M).

LightOnOCR-3 uses its official Transformers classes and image-only transcription
mode. Prepare each required size through the VLM environment:

```bash
.venv-ocr-vlm/bin/python -m research.workbench prepare-models --model lightonocr-3-0.8b
.venv-ocr-vlm/bin/python -m research.workbench prepare-models --model lightonocr-3-1b
.venv-ocr-vlm/bin/python -m research.workbench prepare-models --model lightonocr-3-4b
```

Models use `.venv-ocr` or `.venv-ocr-vlm` from the repository root by default;
override with `VIPI_OCR_PYTHON` and `VIPI_OCR_VLM_PYTHON`. Heavy models run in a
separate process reused across images and released before the next model.
See the official [LightOn 1B](https://huggingface.co/lightonai/LightOnOCR-3-1B)
and [Qwen-based 0.8B/4B](https://huggingface.co/lightonai/LightOnOCR-3-0.8B) cards.

On this Mac, LightOn uses MPS with native eager attention: PyTorch 2.6's fused
SDPA path crashed on its grouped attention tensors. This setting and dtype are
recorded with each result; the official 1B MPS path uses float32.

The API adapters read `MISTRAL_API_KEY`, `GOOGLE_CLOUD_API_KEY` (or
`GOOGLE_API_KEY`), and `OPENAI_API_KEY` through the existing credential resolver.
Google and Luna adapters are shared with the public CLI's `--modus cloud`;
the Workbench keeps explicit model selection for comparisons.
Run the functional **Round 0** check before the full manual baseline:

```bash
.venv-ocr/bin/python -m research.workbench check-models
```

This sends one common image to each active model/API. `--model` is repeatable;
`--image` overrides the synthetic input. Reports are saved in
`runs/reports/ocr-round0/<id>/`; readiness lives in
`models/ocr/workbench-readiness.json`. Failed models show their reason and are
disabled until a successful explicit retry. This check does not measure accuracy.

### Ubuntu with an NVIDIA GPU

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and an NVIDIA
driver compatible with CUDA 12.8 or newer. `nvidia-smi` must show your GPU before
starting. From the project root, use the CUDA extra instead of the CPU extra:

```bash
nvidia-smi
UV_PROJECT_ENVIRONMENT=.venv-ocr uv sync --python 3.12 --locked --extra ocr-cuda --extra research --extra test
.venv-ocr/bin/python -m research.workbench prepare-models --model ppocr-v6
.venv-ocr/bin/python -m research.workbench serve
```

Open http://127.0.0.1:8000, choose **NVIDIA CUDA** and start with **1–2 workers**.
Each worker owns its model sessions and consumes GPU memory. Compare a few scene
images and screenshots before starting a large selection.
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
uv sync --python 3.12 --locked --extra ocr-cuda --extra research --extra test
.venv-ocr\Scripts\python.exe -m research.workbench prepare-models --model ppocr-v6
.venv-ocr\Scripts\python.exe -m research.workbench serve
```

### Move the selected dataset to another computer

Git contains the evaluation code and the pinned dataset revision. On the other
machine, install the research dependencies and download the matching catalog
and images from Hugging Face:

```bash
uv sync --extra research
uv run python -m research.download ocr_eval
```

The catalog and images are local copies ignored by Git. An offline transfer can
copy `research/ocr_eval/catalog.json` and `research/ocr_eval/images/` together.
Create a fresh Python environment and prepare model files on the other machine;
Mac virtual environments are not portable.

For both evaluation suites, download paths and submitting new examples, see the
[image download](../README.md#download-images) and
[image contribution](../README.md#add-images) instructions.

## Web

```bash
.venv-ocr/bin/python -m research.workbench serve
```

Open http://127.0.0.1:8000, choose an image or dataset, then move through **Input**,
**Options** and **Review**. Choose one or more OCR models, hardware backend, worker count
and any combination of Jev, OpenAI Decisions and Prompt Guard 2. Leave all text
classifiers unchecked for OCR only. Detection requires a threshold set version
and one score threshold for every selected check; set each threshold with its slider
or numeric input. A score at or above the threshold is flagged, while lower
complete scores are not flagged.
Without thresholds the scanner can only show scores, not verdicts. The **Scan** tab contains setup, progress, recognized text and detector
results. Dataset reports are shown separately in **Evaluation**; starting a
dataset run opens that tab.

The OCR profile appears in Review and the saved selection report. Baseline uses
one worker because it makes one model call per image. Models may still resize,
locate text and classify orientation inside their native processing. To select
the old research behavior from the CLI, pass `--ocr-profile transforms`;
`--ocr-profile baseline` is the default. Historical reports keep their profiles.

Selected models run sequentially in the displayed order: model A scans every
selected image before model B loads. Both dataset collections can be combined;
all selected detection images receive OCR even with detectors off. Keep the
server running and computer awake for overnight runs; the browser tab may close.
Restarting the server marks an unfinished queue interrupted rather than resuming.

Evaluation includes a per-model comparison and per-image OCR duration, inference
and initialization time, and estimated API cost. Raw usage and pricing assumptions
are retained in JSON and image details. Missing cost remains unknown. Local API
fees are zero, excluding electricity/hardware. Estimates use dated standard list
prices, not invoices: [OpenAI](https://developers.openai.com/api/docs/models/gpt-6-luna),
[Google](https://cloud.google.com/vision/pricing), [Mistral](https://docs.mistral.ai/models/ocr-4-1).
Google free quota and account volume/discounts are unknown. Models without word
positions are **Unscored** for unordered spatial references; compare scored
denominators alongside pass rates. Text, timing and cost are still saved.

The run panel stays visible across both tabs. It shows the current image, scan
phase, and a time estimate based on observed progress. Evaluation reports start
with a compact per-image table; open a row's details for its reference text,
recognized text, detector verdicts and exact scores. Aggregate and category
reports are collapsed until requested.

**View OCR steps** opens a separate detail dialog with adjusted images,
animated OCR boxes, worker states and variant texts. Images are loaded only after
you explicitly open it. Competing readings are available there as well.
Reloading the run URL restores saved results with the detail dialog closed.

**Other CLI options** contains image/context checks, caller context and answer reuse.
These map to the corresponding `research.workbench extract` CLI options. Select
multiple text classifiers by repeating `--text-classifier` on the command line.
The dataset browser and evaluation reports are workbench features; detector and
OCR configuration follows the CLI.
The transformation profile supports 1–8 workers (default 4); baseline uses one.
Each worker has its own OCR instance; CPU threads are divided between workers.
CPU is default. Apple CoreML is experimental on supported Macs, and can place
supported operations on CPU, GPU or Neural Engine. NVIDIA CUDA is available on
supported Linux/Windows installations. Tesseract uses CPU only.

### Stop a scan

**Stop scan** cancels the current uploaded-image scan or its active detector
checks. **Stop batch** also skips the remaining selected images. The button
changes to **Stopping …** until current operations return; native OCR and
provider calls already running finish before cancellation completes. Heavy model
workers owned by the queue are terminated on cancellation. Queued
work does not start after cancellation is observed.

Completed OCR steps, detector answers and earlier images remain saved and
inspectable. Cancelled runs have a separate `cancelled` state and retain that
state after a restart. Cancelled images/cases are reported separately from
technical errors and excluded from evaluation percentages. After stopping
finishes, another scan can start normally.

### Dataset selection and evaluation

Open **Browse dataset** and select images from **ocr_evaluation** and/or
**detection_evaluation**. Switching between the two catalogs keeps the current
selection, so one batch can contain images from both. Filter by category or
search by filename or reference text, then confirm with **Apply selection**.
Images run one after another; each uses the chosen 1–8 OCR workers. Leave all
detector checks off to run OCR only, including on detection-dataset images.
When a detector is enabled, labeled detection cases run only for images selected
from `detection_evaluation`.

Each selection's reference scope, quality, word regions and source details come
from its own catalog: `research/ocr_eval/catalog.json` or
`research/detection_eval/cases.json`. Images and annotations are never modified
or passed to OCR as hints.

Evaluation v4 uses **tolerant word coverage in the final scanner text** as the
primary metric. A case passes when every annotated reference word is covered.
Small spelling errors are accepted: one edit for normalized words of 2–9
characters, and 20% rounded down for longer words; single characters must match.
Coverage normalizes NFKC, case and punctuation. **Exact-word coverage** and its
own image pass rate separately measure literal case-sensitive words, including
attached symbols. Neither metric changes OCR output or detector behavior.

Words are whitespace-delimited units containing word characters. Adjacent OCR
fragments can cover one reference word, including a visually wrapped long string.
Each observed fragment is used once, so missing/repeated words cannot be replaced
by unrelated text or raw word counts. Known reference order is preserved. TextOCR
additionally requires one-to-one word matches in overlapping annotated regions
(at least 50% of the smaller box); global reading order is ignored. Ignored
regions are excluded. When a reference annotates independent regions, word order
is preserved within each region and ignored between regions. An OCR region that
overlaps multiple independent reference regions is reported as a group conflict;
it cannot make the reference pass. Extra background/UI text is allowed and does
not improve coverage unless it matches reference words.
References can cover only the payload; their coverage does not prove every visible
text region was detected.
See [ADR 0028](../../adr-code/0028-independent-ocr-payload-regions.md).

The report separates pipeline detection from final-text retention. It shows
missing reference words, each variant's word coverage and exact-word fidelity,
and paired effect comparisons:
filters versus the same unfiltered view; scaling, rotation and tiles versus the
unfiltered original. Filter effects require an unfiltered version of the same
view. Variants without that control still contribute to OCR coverage, but not
to the paired effect counts. Effect counts describe variant comparisons, not image counts.
The **Evaluation** tab contains the **Dataset OCR evaluation** report with valid, incomplete
and technically failed images; processing continues after individual errors.
Click an image after completion
to inspect its variants. Source/Silver references may themselves be incomplete.
At the end, a category chart shows valid/incomplete/error counts and the valid
share of processed images in this selection. Pending images are excluded;
cancelled images are also excluded, and untested categories have no percentage.
Technical failures count as failed cases. Mean coverages use scored completed
images only. JSON reports retain the evaluation version and matching policy.
Historical reports are labeled as legacy exact-token evaluations and are not
silently rescored; restart the workbench and start a new evaluation for v3.
Click a category to filter the image
report. These counts are also included in `summary.categories` in its JSON.

### Detection evaluation

Choose **detection_evaluation** in **Browse dataset** to select images from
`research/detection_eval/cases.json`. Selection, search, multiple-image scans and
downloads work as above. Categories are **Injection**, **Benign** or
**Context dependent**, according to the expected labels of an image's cases.
Search also includes caller context, techniques and obfuscation labels.

Leave detector checks off for OCR-only scans of these images. To evaluate their
labeled cases, enable one or more detectors before **Start scan**. OCR runs once
per image and the enabled detection checks run without caller context; the same
scanner verdict is compared with every case's expected label. Catalog context
describes the ground truth and is displayed for review; it is never supplied
to the scanner. Manual context settings are also ignored. Expected labels and
payload transcripts are never supplied to OCR or detectors as hints.

Context support is not part of the current scanner evaluation. An image may
therefore be flagged even when its catalog context makes it benign. These
misclassifications are intentional evaluation outcomes and count as ordinary
false positives or false negatives. Contextual cases remain in the scores
with their original labels. Reports record `detection_context_mode: "none"`;
older saved reports retain their original results.

The **Evaluation** tab shows true/false positives and true/false negatives,
unresolved verdicts, errors and pending cases, both overall and per detector.
Accuracy is correct / decided cases. Decision rate is decided / completed cases,
including unresolved verdicts and errors in that denominator. Pending and
cancelled cases are excluded. Without configured
thresholds, scores remain unresolved and accuracy is unavailable. A provider
failure is reported as an error; other cases and images continue.
Expand **Results by image and context**, then click an image to inspect that
image's shared detector check. The JSON selection report stores these results in
each image's `cases` and aggregates them under `detection_evaluation`.

The existing OCR evaluation also compares recognized text with each image's
primary visible payload, including encoded text exactly as cataloged. This
measures payload coverage rather than a full-image transcript. It is reported
separately under **Dataset OCR evaluation** and never substitutes for detection
accuracy.

## CLI

```bash
.venv-ocr/bin/python -m research.workbench extract image.png --model ppocr-v6 --workers 4
.venv-ocr/bin/python -m research.workbench extract image.png --backend coreml --workers 2
.venv-ocr/bin/python -m research.workbench extract image.png --backend cuda --workers 1
.venv-ocr/bin/python -m research.workbench extract image.png --model tesseract --json --output result.json
.venv-ocr/bin/python -m research.workbench reassemble RUN_ID
.venv-ocr/bin/python -m research.workbench extract ANNOTATED_IMAGE --evaluate --json
```

Active model IDs are listed in [the comparison protocol](../ocr_eval/BASELINE.md).
Progress goes to stderr;
recognized text or JSON goes to stdout. `--output` also saves that output.
`extract --workers 1` runs sequentially; the default is 4 and the maximum is 8.
`--evaluate` uses the active annotation for the supplied dataset image. Evaluation
details are included in JSON; the concise verdict goes to stderr.
`reassemble` updates a completed run from its stored OCR results, without running
OCR again or changing the raw step records. Refresh its web page afterwards.
`extract` and `serve` accept `--models-dir` and `--runs-dir`; `reassemble` accepts
`--runs-dir`. The web command also accepts `--port`. These diagnostic commands
run from the repository root; the public `vipi` command keeps its simpler interface.

## Saved results

Workbench reports are saved automatically; downloading them in the browser is
optional. With the default settings, they stay inside the repository's `runs/`
directory, which is excluded by `.gitignore`:

| Report | Repository path |
| --- | --- |
| Single-image OCR | `runs/<run-id>/result.json` |
| Selection evaluation (OCR and optional scanner results) | `runs/batches/<batch-id>/report.json` |
| Scanner check | `runs/<run-id>/detection/<check-id>/result.json` |

Each run has its own identifier, so later runs preserve earlier reports.
`--runs-dir` overrides this location; use a directory inside the repository if
reports should remain there. Separately generated analysis reports can also be
retained under `runs/reports/`.

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
.venv-ocr/bin/ruff check src/vipi/ocr tests
```
