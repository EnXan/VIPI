# Models and hardware

The public scanner first extracts text, uses visual decisions when OCR recovery
needs review, and then checks the final text for prompt injections. The
[README](../README.md#models-at-a-glance) gives the short overview; this page
keeps model identifiers, override rules and hardware estimates.

## Local profiles

| Local profile | Text detection and recognition | Visual OCR review | Default injection detector |
| --- | --- | --- | --- |
| `quality` (default) | PP-OCRv6 Medium: `PP-OCRv6_det_medium.onnx` + `PP-OCRv6_rec_medium.onnx`; ID `ppocr-v6` (`ppocr-v6-medium` alias) | `Cloudflare/clef-flash` | Same Clef-Flash model |
| `balanced` | PP-OCRv6 Small: `PP-OCRv6_det_small.onnx` + `PP-OCRv6_rec_small.onnx`; ID `ppocr-v6-small` | `LiquidAI/d1-3B` | Same d1 model |
| `speed`, legacy alias `fast` | PP-OCRv6 Tiny: `PP-OCRv6_det_tiny.onnx` + `PP-OCRv6_rec_tiny.onnx`; ID `ppocr-v6-tiny` | `LiquidAI/d1-3B` | Same d1 model |

RapidOCR runs the local PP-OCRv6 models through ONNX Runtime. All local profiles
also prepare `ch_PP-LCNet_x0_25_textline_ori_cls_mobile`, the native text-line
orientation classifier. Production uses RapidOCR's native pipeline; the legacy
research transform control disables its classification stage.

## Cloud components

| Cloud component | Model/service | Purpose |
| --- | --- | --- |
| `--ocr-provider google` (default) | Google Cloud Vision `DOCUMENT_TEXT_DETECTION`, ID `google-cloud-vision` | OCR text and word geometry |
| `--ocr-provider openai` | `gpt-6-luna`, Responses API | Full-image OCR transcription |
| `--ocr-provider mistral` | `mistral-ocr-4-1`, Mistral OCR API | OCR transcription and available block geometry |
| `--decision-provider openai` (default) | `gpt-6-luna`, OpenAI Decisions API | Visual OCR review and default final injection check |
| `--decision-provider jev` | `jev-1.14.0`, TypeSafe API | Visual OCR review and default final injection check |

## Overrides

`--decision-provider clef-flash|d1` overrides local OCR review. `--detector` overrides
only the final check: local choices are `clef-flash`, `d1` and `prompt-guard`; cloud
choices are `openai` and `jev`. `auto` follows the decision provider.
`prompt-guard` uses `meta-llama/Llama-Prompt-Guard-2-86M` on final OCR text;
it does not perform visual OCR review. `--ocr-model` changes OCR without changing
the local profile's decision model. Local and cloud providers cannot be mixed.
See the [CLI reference](cli.md#commands-and-options) for every option.

`clef-flash` is Cloudflare's smaller Clef variant (post-trained from
Qwen/Qwen3.5-9B). It replaced the 27B Clef as the `quality` model, which needed
about 55 GB of weights in 16-bit and ran on no available machine
([ADR 0065](../adr-code/0065-clef-flash-replaces-clef.md)). Weights of an
earlier Clef setup stay in the cache folder `decisions/clef` until deleted.

## Pinned weights

Setup prepares local weights and verifies pinned code; scanning has no model
download or hosted fallback. Exact OCR hashes are in
[`model_files.json`](../src/vipi/ocr/model_files.json), Clef-Flash and d1 repositories and
immutable revisions in [`decision_models.json`](../src/vipi/decision_models.json),
and the Prompt Guard revision in [`config.py`](../src/vipi/config.py). Clef-Flash
requires substantially more memory than d1. These defaults are configuration
choices, not a measured quality ranking across profiles.

## Hardware

**Most figures below are planning estimates, not tested minimum requirements.**
Only the Apple Silicon figure for `speed` was measured. The estimates do not
guarantee compatibility, completion or performance. They assume one image at a
time, unquantized decision models and each profile's default shared
review/detector model.

| Mode/profile | CPU-only (estimate) | Accelerated alternative | Free disk before setup (estimate) |
| --- | --- | --- | --- |
| `cloud` | Modern 64-bit CPU, about 4 cores and 8 GB RAM; assumption, no model runs locally | No GPU required; internet access needed | About 15 GB |
| Local `speed` / `fast` | Modern 64-bit CPU, about 4 cores and 24 GB RAM | **Measured:** Apple M2 with 16 GB unified memory ([benchmark](ocr-benchmark.md#measured-run-12-november-2026)). Estimate: CUDA GPU with 16 GB VRAM and 16 GB host RAM | About 25 GB |
| Local `balanced` | Modern 64-bit CPU, about 4 cores and 24 GB RAM | Estimate: Apple Silicon with 16 GB unified memory, as `speed` loads the same d1 model; or CUDA GPU with 16 GB VRAM and 16 GB host RAM | About 25 GB |
| Local `quality` | Modern 64-bit CPU, about 8 cores and 48 GB RAM | **Measured:** Apple M4 Pro with 48 GB unified memory (450 images, development split). Estimate: CUDA GPU with 24 GB VRAM and 32 GB host RAM | About 45 GB |

The model cards state no memory requirements. The estimates derive from the
upstream model sizes at the pinned revisions and VIPI's loading precision:

| Model | Upstream size (pinned revision) | Weights on CPU (FP32) | Weights on CUDA/MPS (16-bit) |
| --- | --- | ---: | ---: |
| [d1](https://huggingface.co/LiquidAI/d1-3B/tree/051bcc464b01b9f92942b364d9586b0ef5912432) | 3.12B parameters, BF16, 6.25 GB files | ~12.5 GB | ~6.3 GB |
| [Clef-Flash](https://huggingface.co/Cloudflare/clef-flash/tree/fb4417d31c1d0f9e7e77f1141b40aaede7491e00) | ~9.5B parameters, BF16, 19 GB files | ~38 GB | ~19 GB |
| [Prompt Guard 2](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M) | 279M parameters including embeddings, FP32, 1.1 GB file | ~1.1 GB | not used |

VIPI loads decision models in FP32 on CPU, BF16 on CUDA and FP16 on Apple MPS
([`local_decisions.py`](../src/vipi/local_decisions.py)). Weights exclude OCR,
activations, image buffers and operating-system overhead. The measured `speed`
run used MPS/FP16 with fresh processes every four images; it does not certify a
minimum; neither does the measured `quality` run on an M4 Pro (MPS/FP16, median
about 15 s per image). CPU-only inference, especially Clef-Flash, can be very slow. `speed` reduces OCR work but still loads the
same d1 model as `balanced`.

Larger images, longer OCR text or overrides loading a second decision model can
need more memory. Disk estimates cover the runtime and selected weights; allow
extra space for download caches and saved scans. Accelerator figures describe
capacity only, not verified backend support. CUDA requires a compatible
CUDA-enabled PyTorch build; source-checkout defaults use CPU Torch wheels on
Linux/Windows. Cloud mode still processes images locally but hosts the models.
