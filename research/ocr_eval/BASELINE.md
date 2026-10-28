# OCR baseline and improvement protocol

The current comparison uses the existing catalogs: 1,000 OCR images and 113
detection images. No new freeze, split or holdout setup is required for these
exploratory rounds. Reports retain actual input/reference hashes and reference
snapshots; source data stays intact.

## Active models

| Model ID | Execution |
| --- | --- |
| `ppocr-v6` | Local PP-OCRv6 Medium, native RapidOCR/ONNX |
| `ppocr-v6-small` | Local PP-OCRv6 Small, native RapidOCR/ONNX |
| `ppocr-v6-tiny` | Local PP-OCRv6 Tiny, native RapidOCR/ONNX |
| `tesseract` | Local Tesseract English, tessdata_best |
| `paddleocr-vl-1.6` | Local official PaddleOCRVL pipeline |
| `granite-docling-258m` | Local official Docling VlmPipeline |
| `mistral-ocr-4-1` | Mistral OCR API |
| `google-cloud-vision` | Google DOCUMENT_TEXT_DETECTION API |
| `gpt-6-luna` | OpenAI Responses API, image transcription |
| `lightonocr-3-0.8b` | Local official Transformers Qwen3.5 pipeline |
| `lightonocr-3-1b` | Local official Transformers LightOnOcr pipeline |
| `lightonocr-3-4b` | Local official Transformers Qwen3.5 pipeline |

GPT-6 Sol, Florence-2, Surya OCR 2 and PP-OCRv5 are excluded from active
selection at the user's request. Historical reports remain intact. olmOCR
remains deferred. Downstream detectors are separate from the OCR comparison.
An available model or cached weight file is not evidence of accuracy.

## Round 0: functional verification

Run each model on **one common image**, with no detectors. This checks loading,
inference, text output, timing and available cost metadata, not dataset quality.
The default image says `Baseline OCR 123`; `--image` can replace it.

```bash
.venv-ocr/bin/python -m research.workbench check-models
# Retry one model after fixing its runtime:
.venv-ocr/bin/python -m research.workbench check-models --model lightonocr-3-1b
```

Reports and the actual PNG are saved under ignored
`runs/reports/ocr-round0/<id>/`. Readiness is stored in
`models/ocr/workbench-readiness.json`; failed checks disable that model in the
Workbench with its error. Rerunning the check can clear the failure. A
nonempty incorrect transcription is a functional result, not an accuracy pass.

## Round 1: manually started baseline

In the Workbench, select images from either or both catalogs, select one or
more OCR models, keep **Original only · baseline**, and leave detectors off.
Selecting both complete catalogs scans all **1,113 images per model**, including
the OCR step for detection images. Start the run manually when ready.

Models run sequentially in the displayed order. Each model finishes the image
selection before the next model loads. One worker reuses the model across images.
Heavy backends run in isolated processes, releasing their memory between models.
Keep the server running and the computer awake; the browser tab may close.
Reports are updated after each image, but restarting the server does not resume
an interrupted queue automatically.

Baseline sends one original decoded image per model. It applies no VIPI scaling,
rotation, mirroring, crop/filter passes, assembly or text repair. Models retain
their required native preprocessing. EXIF orientation and alpha compositing
are part of input decoding; saved PNGs record the exact decoded input.
The previous `transforms` profile remains an explicit historical control.
The public scanner keeps its existing release processing.

## Measurements and interpretation

The target remains **90% image pass rate** for tolerant reference-word coverage;
literal exact-word fidelity is separate. Record model errors and per-image
latency, including mean, median and P95. Initialization and inference times are
reported separately so cold startup does not masquerade as steady-state speed.
API usage, dated price assumptions and estimates are saved with each result.
Unknown costs remain unknown. Local API fees are zero, excluding hardware and
electricity. Estimates are not provider invoices.

Evaluation v3 requires word locations for references without known reading
order, including TextOCR. Transcription-only models cannot be ranked on that
spatial metric. Nonempty results without coordinates are marked **Unscored**,
with raw text, duration and cost retained. The scored-image denominator
must accompany comparisons. No page-wide word coordinates are fabricated and
no model-specific matching rule is substituted. A comparable text-only metric
for these references requires a separate agreed change before a full quality
ranking across all model types.

## Later rounds

Inspect actual misses, remove clearly weak models early, then add a targeted
transformation supported by those failures. Rerun the remaining models on the
same selection and compare gains, regressions, latency and cost. Do not add a
transformation stack speculatively. Model combinations follow only if measured
complementary strengths justify their extra processing.

These iterative results describe the current images and annotation scope;
repeated tuning on them does not establish generalization to unseen images.
