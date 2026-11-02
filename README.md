# VIPI — Visual Prompt Injection Scanner for Images

<p align="center">
  <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/motion/vipi-reveal.gif" alt="Animated VIPI logo reveal" width="720">
</p>

<p align="center">
  A Python CLI and GitHub Action that use OCR to detect prompt injections in images.
</p>

<p align="center">
  <a href="https://github.com/EnXan/VIPI/blob/main/pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white"></a>
  <a href="https://github.com/EnXan/VIPI/blob/main/docs/cli.md#platform-validation-status"><img alt="Historical macOS validation" src="https://img.shields.io/badge/macOS-tested-2ea44f"></a>
  <a href="https://github.com/EnXan/VIPI/blob/main/docs/cli.md#platform-validation-status"><img alt="Historical Linux validation" src="https://img.shields.io/badge/Linux-tested-2ea44f"></a>
  <a href="https://github.com/EnXan/VIPI/blob/main/docs/cli.md#platform-validation-status"><img alt="Historical Windows validation" src="https://img.shields.io/badge/Windows-tested-2ea44f"></a>
</p>

VIPI uses signal-driven OCR recovery and checks the final text for prompt
injections. `--modus local` runs OCR, visual decisions and injection detection
locally. `--modus cloud` uses the selected hosted OCR and decision providers.
The CLI scans files, directories and committed image changes. Images with no
recognized text can still contain visual prompt injections.

Evaluation images, OCR references and detection labels are available in the
[VIPI Evaluation dataset](https://huggingface.co/datasets/EnXan/VIPI-evaluation).
See how to [download the pinned images](https://github.com/EnXan/VIPI/blob/main/research/README.md#download-images)
or [contribute new examples for review](https://github.com/EnXan/VIPI/blob/main/research/README.md#add-images).

## Installation and first scan

Use Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
# Fully local, balanced profile
uv tool install --python 3.12 'vipi-scanner[ocr,detector-local]'
vipi setup --ocr-mode balanced
vipi scan image.png --ocr-mode balanced --output report.json
```

For cloud execution, install `vipi-scanner[ocr]`, configure
`GOOGLE_CLOUD_API_KEY` and `OPENAI_API_KEY`, then run:

```bash
vipi setup --modus cloud
vipi scan image.png --modus cloud --output report.json
```

Keys can come from the environment or an ignored `.env` in the current directory;
see [`.env.example`](https://github.com/EnXan/VIPI/blob/main/.env.example). In PowerShell, use
`$env:OPENAI_API_KEY = "your-openai-api-key"`. If `vipi` is not on `PATH`, run
`uv tool update-shell` and restart the terminal.

## Models and their roles

The public scanner first extracts text, uses visual decisions when OCR recovery
needs review, and then checks the final text for prompt injections.

| Local profile | Text detection and recognition | Visual OCR review | Default injection detector |
| --- | --- | --- | --- |
| `quality` (default) | PP-OCRv6 Medium: `PP-OCRv6_det_medium.onnx` + `PP-OCRv6_rec_medium.onnx`; ID `ppocr-v6` (`ppocr-v6-medium` alias) | `Cloudflare/clef` | Same Clef model |
| `balanced` | PP-OCRv6 Small: `PP-OCRv6_det_small.onnx` + `PP-OCRv6_rec_small.onnx`; ID `ppocr-v6-small` | `LiquidAI/d1-3B` | Same d1 model |
| `speed`, legacy alias `fast` | PP-OCRv6 Tiny: `PP-OCRv6_det_tiny.onnx` + `PP-OCRv6_rec_tiny.onnx`; ID `ppocr-v6-tiny` | `LiquidAI/d1-3B` | Same d1 model |

RapidOCR runs the local PP-OCRv6 models through ONNX Runtime. All local profiles
also prepare `ch_PP-LCNet_x0_25_textline_ori_cls_mobile`, the native text-line
orientation classifier. Production uses RapidOCR's native pipeline; the legacy
research transform control disables its classification stage.

| Cloud component | Model/service | Purpose |
| --- | --- | --- |
| `--ocr-provider google` (default) | Google Cloud Vision `DOCUMENT_TEXT_DETECTION`, ID `google-cloud-vision` | OCR text and word geometry |
| `--ocr-provider openai` | `gpt-6-luna`, Responses API | Full-image OCR transcription |
| `--ocr-provider mistral` | `mistral-ocr-4-1`, Mistral OCR API | OCR transcription and available block geometry |
| `--decision-provider openai` (default) | `gpt-6-luna`, OpenAI Decisions API | Visual OCR review and default final injection check |
| `--decision-provider jev` | `jev-1.14.0`, TypeSafe API | Visual OCR review and default final injection check |

`--decision-provider clef|d1` overrides local OCR review. `--detector` overrides
only the final check: local choices are `clef`, `d1` and `prompt-guard`; cloud
choices are `openai` and `jev`. `auto` follows the decision provider.
`prompt-guard` uses `meta-llama/Llama-Prompt-Guard-2-86M` on final OCR text;
it does not perform visual OCR review. `--ocr-model` changes OCR without changing
the local profile's decision model. Local and cloud providers cannot be mixed.

Setup prepares local weights and verifies pinned code; scanning has no model
download or hosted fallback. Exact OCR hashes are in
[`model_files.json`](https://github.com/EnXan/VIPI/blob/main/src/vipi/ocr/model_files.json), Clef/d1 repositories and
immutable revisions in [`decision_models.json`](https://github.com/EnXan/VIPI/blob/main/src/vipi/decision_models.json),
and the Prompt Guard revision in [`config.py`](https://github.com/EnXan/VIPI/blob/main/src/vipi/config.py). Clef requires
substantially more memory than d1. These defaults are configuration choices,
not a measured quality ranking across profiles.

Research additionally compares Tesseract 5 English (`tessdata_best`),
PaddleOCR-VL 1.6 (`paddleocr-vl-1.6`), IBM Granite-Docling 258M
(`granite-docling-258m`) and LightOnOCR-3 0.8B/1B/4B
(`lightonocr-3-0.8b`, `lightonocr-3-1b`, `lightonocr-3-4b`). These are OCR
comparison backends, not public scan defaults. See the
[complete comparison inventory](https://github.com/EnXan/VIPI/blob/main/research/ocr_eval/BASELINE.md).

### Estimated minimum hardware (not tested)

**These are rough planning estimates, not tested minimum requirements.** The
configurations below have not been validated as VIPI minimums and do not
guarantee compatibility, completion or performance. They assume one image at a
time, unquantized decision models and each profile's default shared review/detector model.

| Mode/profile | Estimated CPU-only configuration | Estimated accelerated alternative | Free disk before setup |
| --- | --- | --- | --- |
| `cloud` | Modern 64-bit CPU, about 4 cores and 8 GB RAM | No GPU required; internet access needed | About 15 GB |
| Local `speed` / `fast` | Modern 64-bit CPU, about 4 cores and 24 GB RAM | Apple Silicon with 24 GB unified memory, or CUDA GPU with 16 GB VRAM and 16 GB host RAM | About 25 GB |
| Local `balanced` | Modern 64-bit CPU, about 4 cores and 24 GB RAM | Apple Silicon with 24 GB unified memory, or CUDA GPU with 16 GB VRAM and 16 GB host RAM | About 25 GB |
| Local `quality` | Modern 64-bit CPU, about 8 cores and 128 GB RAM | Apple Silicon with 96 GB unified memory, or CUDA GPU with 80 GB VRAM and 64 GB host RAM | About 100 GB |

The estimates use the upstream model sizes
([d1: 3.12B parameters](https://huggingface.co/LiquidAI/d1-3B/blob/051bcc464b01b9f92942b364d9586b0ef5912432/README.md),
[Clef: 27B parameters](https://huggingface.co/Cloudflare/clef)) and VIPI's FP32
CPU / 16-bit accelerator loading. Raw weights alone are roughly 12.5/108 GB on
CPU or 6.3/54 GB on an accelerator for d1/Clef, before OCR, activations, image
buffers and operating-system overhead. CPU-only inference, especially Clef,
can be very slow. `speed` reduces OCR work but still loads the same d1 model as
`balanced`.

Larger images, longer OCR text or overrides loading a second decision model can
need more memory. Disk estimates cover the runtime and selected weights; allow
extra space for download caches and saved scans. Accelerator figures describe
capacity only, not verified backend support. CUDA requires a compatible
CUDA-enabled PyTorch build; source-checkout defaults use CPU Torch wheels on
Linux/Windows. Cloud mode still processes images locally but hosts the models.

## Measured OCR benchmark

On 1–2 November 2026, the 0.7.1 PR candidate ran both configurations over the
same **1,113 catalog entries, 1,106 distinct image files and 31,140 reference
words**. Host: Apple M2, 8 CPU cores, 16 GB unified memory, macOS 27.0.1. Local
OCR used CPU; d1 used MPS/FP16 with fresh processes every four images.

| Configuration | Completed | Word coverage | Exact word coverage | Mean image coverage | Images ≥80% | Images at 100% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Local speed: Tiny + d1 | 1,113/1,113 | 69.46% | 63.00% | 70.91% | 649/1,113 (58.31%) | 567/1,113 (50.94%) |
| Cloud defaults: Google + OpenAI Decisions | 1,100/1,113 | 85.38% | 73.01% | 83.49% | 797/1,113 (71.61%) | 634/1,113 (56.96%) |

These figures use every planned entry/reference word, giving failures zero
credit. Word coverage uses evaluation v4's spelling tolerance; exact coverage
is literal and case-sensitive. The 100% column measures tolerant coverage.

| Category | N | Local: word coverage / ≥80% images / 100% images | Cloud: word coverage / ≥80% images / 100% images |
| --- | ---: | ---: | ---: |
| Typographic visual prompt injection | 125 | 99.72% / 100.00% / 96.80% | 97.50% / 97.60% / 97.60% |
| TextOCR | 500 | 47.98% / 16.60% / 7.80% | 76.67% / 43.20% / 16.00% |
| VPI-Bench | 125 | 99.76% / 100.00% / 95.20% | 97.64% / 98.40% / 97.60% |
| CyberSecEval3 visual prompt injection | 125 | 70.31% / 72.80% / 60.80% | 88.90% / 90.40% / 83.20% |
| MM-SafetyBench | 125 | 98.92% / 96.80% / 96.80% | 97.18% / 96.80% / 96.80% |
| Scanner evaluation catalog | 113 | 96.19% / 92.04% / 80.53% | 95.47% / 90.27% / 75.22% |
| Anamorpher subset, already included above | 3 | 28.57% / 0.00% / 0.00% | 71.43% / 66.67% / 66.67% |

| Configuration | Total wall time | Wall time/image | Known-usage API-fee estimate, total / image |
| --- | ---: | ---: | ---: |
| Local speed | 4h 14m 14s | 13.71s | $0 / $0; local compute unmeasured |
| Cloud defaults | 1h 34m 49s | 5.11s | $7.44450 / $0.006689; full fee unknown |

Cloud retained nine service-unavailable failures, three review refusals and one
request-size rejection. Fees include recorded cache reads/writes and partial
work before failure; 13 requests have no retained usage. These are list-rate
estimates before free quota, discounts and taxes, not invoices or total operating
costs. Wall time includes process overhead and repeated local loading; category
timings in the full report measure OCR calls separately.

This measures **annotated OCR recovery**, including payload-only references,
on a development dataset. It does not establish independent general OCR accuracy
or injection-detection recall; the three Anamorpher samples are a small subset.
See the [protocol, pinned dataset revision and failure history](https://github.com/EnXan/VIPI/blob/main/docs/ocr-benchmark.md),
[full category/time/cost tables](https://github.com/EnXan/VIPI/blob/main/research/ocr_eval/reports/PRODUCT_OCR_1113_2026-11-02.md)
and [per-image results and source hashes](https://github.com/EnXan/VIPI/blob/main/research/ocr_eval/reports/PRODUCT_OCR_1113_2026-11-02.json).

## Usage

```bash
vipi scan label.png screenshot.jpg
vipi scan ./images --verbose --output report.json
vipi scan ./images --exclude 'generated/' --exclude '*.webp'
vipi scan . --diff origin/main --output report.json
vipi scan image.png --modus cloud --detector openai --threshold 90
```

The public commands are `vipi setup` and `vipi scan`. Use the same model/profile
options for setup and scan. Bare `vipi setup` prepares all local OCR sizes and
the default quality decision model; explicitly preparing `balanced` avoids that
larger default download. Cloud recovery can make additional billable requests.
The default detection threshold is 80/100; scores are not calibrated attack
probabilities. A below-threshold result does not prove safety.

| Exit code | Meaning |
| --- | --- |
| `0` | Complete scan without detections, or no selected images |
| `1` | Detection found and every selected image completed |
| `2` | Error or incomplete scan; takes precedence over findings |

See the [complete CLI reference](https://github.com/EnXan/VIPI/blob/main/docs/cli.md) for every option, credentials,
diff semantics, cache paths and report behavior.

## GitHub Actions

The Action defaults to the same local quality profile. This example explicitly
uses d1 for OCR review and Prompt Guard for injection detection:

```yaml
name: VIPI image scan
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
      - uses: EnXan/VIPI@v0.7.1
        with:
          modus: local
          ocr-mode: balanced
          detector: prompt-guard
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        if: always()
        with:
          name: vipi-report
          path: vipi-report.json
```

The runner needs sufficient memory for the chosen local models. Accept any
required model terms before downloading gated weights. Fork PRs normally do not
receive repository secrets. For hosted execution, configure cloud OCR and
decision keys and set `modus: cloud`; see
[Action inputs and PR selection](https://github.com/EnXan/VIPI/blob/main/docs/cli.md#github-action).

## Documentation

- [CLI reference and platform validation](https://github.com/EnXan/VIPI/blob/main/docs/cli.md)
- [OCR recovery and measured limits](https://github.com/EnXan/VIPI/blob/main/docs/ocr-recovery.md)
- [Architecture](https://github.com/EnXan/VIPI/blob/main/docs/architecture.md) and [development](https://github.com/EnXan/VIPI/blob/main/docs/development.md)
- [Research CLI reference](https://github.com/EnXan/VIPI/blob/main/docs/research-cli.md), [workbench](https://github.com/EnXan/VIPI/blob/main/research/workbench/README.md) and [datasets](https://github.com/EnXan/VIPI/blob/main/research/README.md)
- [Decision records](https://github.com/EnXan/VIPI/blob/main/adr-code/README.md)

The wheel contains `vipi`; research tools, datasets, weights and run artifacts
stay outside it. Current platform and model-validation limits are recorded in
the CLI and recovery guides.

## License

VIPI's original code, documentation and assets use
[Apache License 2.0](https://github.com/EnXan/VIPI/blob/main/LICENSE). Models, dependencies and datasets retain their
respective license terms.
