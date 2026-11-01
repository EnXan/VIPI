# Research CLI reference

Run these commands from a source checkout after the
[development setup](development.md). They are separate from the public
[`vipi setup` / `vipi scan`](cli.md) interface. Every command accepts `-h` or
`--help`; help does not start inference or download models.

## Dataset download

```bash
uv run python -m research.download
uv run python -m research.download ocr_eval
uv run python -m research.download detection_eval
```

The optional positional `suite` defaults to `all`. Files come from the immutable
revision in `research/dataset.json`; public downloads use no token. See
[dataset paths and contributions](../research/README.md#download-images).

## OCR workbench

Entry point: `uv run python -m research.workbench COMMAND`.

| Command | Arguments/options | Purpose |
| --- | --- | --- |
| `prepare-models` | `--model ID`, `--models-dir DIR` | Prepare the chosen OCR backend. Without `--model`, prepare all PP-OCRv6 sizes. API backends require credentials, not local OCR weights. |
| `check-models` | Repeatable `--model ID`, `--image FILE`, `--models-dir DIR`, `--reports-dir DIR` | Functional round-0 check on one common image. Defaults to all active models and a generated `Baseline OCR 123` image. |
| `extract IMAGE` | OCR and detection options below | Recognize one image, optionally evaluate its catalog reference and run detectors. |
| `reassemble RUN_ID` | `--runs-dir DIR`, `--json`, `--output FILE` | Rebuild legacy saved OCR assembly without inference. Adaptive runs reject reassembly because they retain a reviewed candidate. |
| `serve` | `--port NUMBER`, `--models-dir DIR`, `--runs-dir DIR`, `--detector-models-dir DIR` | Start the local server on `127.0.0.1`, default port 8000. |

Default directories: OCR models `models/ocr`, runs `runs`, Prompt Guard
`models/detector/prompt-guard-2-86m`, round-0 reports `runs/reports/ocr-round0`.
Active model IDs are listed in the [comparison inventory](../research/ocr_eval/BASELINE.md#comparison-model-inventory).

| `extract` option | Meaning/default |
| --- | --- |
| `--model ID` | OCR backend; default `ppocr-v6` (Medium). The web interface initially selects Tiny. |
| `--ocr-profile baseline|transforms|adaptive-jev` | Default `baseline`: one native original-image call. `transforms`: fixed historical comparison profile. `adaptive-jev`: shared recovery with OpenAI Decisions review. |
| `--backend cpu|coreml|cuda` | Default CPU. CoreML is experimental on compatible Macs; CUDA requires a supported NVIDIA/ONNX environment. Document/cloud backends use their own runtime. |
| `--workers NUMBER` | Transform workers, default 4, supported 1–8. Baseline/adaptive and single-pass backends use one. |
| `--models-dir DIR` | Prepared OCR model directory |
| `--runs-dir DIR` | Persistent run artifacts |
| `--evaluate` | Evaluate against the image's active reference, after OCR selection |
| `--json` | Print full result JSON instead of recognized text |
| `--output FILE` | Also write the selected text/JSON output |

The historical profile name `adaptive-jev` does not select Jev. The research
CLI/web profile uses OpenAI Decisions and needs `OPENAI_API_KEY` when review is
triggered. Product local/cloud routing belongs to `vipi scan`; baseline and
transform controls with local OCR do not need a decision API.

```bash
uv run python -m research.workbench prepare-models --model ppocr-v6-tiny
uv run python -m research.workbench check-models --model ppocr-v6-tiny
uv run python -m research.workbench extract image.png --model ppocr-v6-tiny --ocr-profile baseline --json
uv run python -m research.workbench extract ANNOTATED_IMAGE --ocr-profile adaptive-jev --evaluate
uv run python -m research.workbench reassemble RUN_ID --json --output rebuilt.json
uv run python -m research.workbench serve --port 8000
```

Successful workbench commands return 0; OCR/setup/functional errors return 1.
An extract-then-detect operation returns 2 for failed detector checks or missing
required text evidence. Findings alone do not change the research exit code.

## Detection commands and shared options

Entry point: `uv run python -m research.workbench.detector_cli COMMAND`.

| Command | Arguments/options | Purpose |
| --- | --- | --- |
| `prepare-detector` | Required `--revision COMMIT_SHA`, optional `--detector-models-dir DIR` | Explicitly download and verify an authorized Prompt Guard snapshot. |
| `detect RUN_ID` | `--runs-dir DIR`, `--json`, `--output FILE`, plus shared options below | Check final text from an existing OCR run. Select at least one text/image/context check. |

These options apply to both `detect` and workbench `extract`:

| Option | Meaning/default |
| --- | --- |
| `--text-classifier jev|openai|prompt-guard` | Repeat to select multiple classifiers; omitted means none |
| `--image-check off|openai` | Original-image check, default off |
| `--context-check off|openai` | Combined original image/final OCR/caller-context check, default off |
| `--context-file FILE` | JSON caller context; omitted fields remain unknown |
| `--thresholds-file FILE` | JSON threshold policy; without it, scores have no resolved clean/flagged policy verdict |
| `--detector-models-dir DIR` | Prepared Prompt Guard directory |
| `--no-reuse` | Make fresh checks; default reuses compatible completed answers |

```bash
uv run python -m research.workbench.detector_cli prepare-detector --revision a8ded8e697ce7c355e395a0df51f94adb4a2fd27
uv run python -m research.workbench.detector_cli detect RUN_ID --text-classifier jev --text-classifier openai --json
uv run python -m research.workbench extract image.png --text-classifier jev --thresholds-file thresholds.json
```

The standalone detector returns 0 when checks finish and 2 on operational
failure or missing required text evidence; it is report-only. See
[detection semantics and JSON formats](../research/workbench/DETECTION.md).

## Separate model environments

`VIPI_OCR_PYTHON` selects the standard OCR interpreter; `VIPI_OCR_VLM_PYTHON`
selects the optional document-model interpreter. Otherwise the workbench prefers
`.venv-ocr` / `.venv-ocr-vlm` when present, then the current interpreter. On Windows
these use `Scripts/python.exe`; on macOS/Linux, `bin/python`.

Run optional model preparation with its own interpreter. The corresponding
extras are `ocr-paddle-vl`, `ocr-granite-docling` and `ocr-lighton`; they are not
installed by the standard development sync. The
[comparison protocol](../research/ocr_eval/BASELINE.md) describes model-specific
functional checks. `research.workbench.model_worker` is a private JSON-line
subprocess protocol, not a user-facing scan command. Its required internal
arguments are `--model`, `--models-dir`, `--profile`, `--backend` and `--threads`;
requests/results travel over JSON lines and local files.

For NVIDIA OCR, use the mutually exclusive `ocr-cuda` extra instead of `ocr`
and run the server/CLI in that same environment, for example:

```bash
UV_PROJECT_ENVIRONMENT=.venv-ocr uv sync --python 3.12 --extra ocr-cuda --extra detector-local --extra research --extra test
.venv-ocr/bin/python -m research.workbench serve
```

On Windows, use `.venv-ocr\Scripts\python.exe` and set
`$env:UV_PROJECT_ENVIRONMENT = ".venv-ocr"` before synchronizing. This selects
the runtime; it does not establish trained-model validation on that platform.
