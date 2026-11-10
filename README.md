<h1 align="center">
  VIPI — Visual Prompt Injection Scanner for Images
</h1>

<p align="center">
  <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/motion/vipi-reveal.gif" alt="Animated VIPI logo reveal" width="720">
</p>

<p align="center">
  <b>Scan images for prompt injections before an AI agent reads them.</b><br>
  A Python CLI and GitHub Action. Runs fully local or with hosted providers.
</p>

<p align="center">
  <a href="https://github.com/EnXan/VIPI/blob/main/pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-0B0C10?logo=python&logoColor=white&labelColor=5C616C"></a>
  <a href="https://pypi.org/project/vipi-scanner/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/vipi-scanner?logo=pypi&logoColor=white&color=0B0C10&labelColor=5C616C"></a>
  <a href="https://github.com/EnXan/VIPI/blob/main/docs/cli.md#platform-validation-status"><img alt="OS Support: macOS | Linux | Windows" src="https://img.shields.io/badge/OS-macOS%20%7C%20Linux%20%7C%20Windows-0B0C10?labelColor=5C616C"></a>
</p>

Images can carry instructions that people overlook but AI models read. VIPI
finds the text in an image, including text that standard OCR misses, and checks
it for prompt injections. It scans single images, folders and committed image
changes.

- **CI/CD and AI code review:** scan pull-request images before AI triage tools
  or coding assistants read them.
- **Image ingestion:** scan uploaded or collected images before they enter an
  AI pipeline.
- **Agents with image input:** check screenshots before an agent decides or acts
  on them.

<p align="center">
  <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/diagrams/vipi-scan-flow.svg" alt="VIPI scans an image before it reaches an AI agent. Clean images continue to the agent; for images with findings, your workflow reports, blocks or allows them." width="900">
</p>

## Quick start

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/).

**Local:** images never leave your machine.

```bash
uv tool install --python 3.12 'vipi-scanner[ocr,detector-local]'
vipi setup --ocr-mode balanced
vipi scan image.png --ocr-mode balanced --output report.json
```

**Cloud:** hosted OCR and decisions. Set `GOOGLE_CLOUD_API_KEY` and
`OPENAI_API_KEY` in the environment or an ignored `.env`
([example](https://github.com/EnXan/VIPI/blob/main/.env.example)).

```bash
uv tool install --python 3.12 'vipi-scanner[ocr]'
vipi setup --modus cloud
vipi scan image.png --modus cloud --output report.json
```

Run `setup` with the same options you scan with. A bare `vipi setup` also
downloads the large `quality` model. If `vipi` is not on `PATH`, run
`uv tool update-shell` and restart the terminal.

## Models at a glance

Every scan runs up to three steps; step 2 runs only when the OCR result is
uncertain. The mode decides who provides the models.

<p align="center">
  <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/diagrams/vipi-scan-pipeline.svg" alt="VIPI reads the text of an image with OCR, has a visual model review uncertain OCR and re-reads the image if text is missing, then checks the final text for prompt injections. The scan ends clean (exit 0), with an injection (exit 1) or incomplete (exit 2)." width="900">
</p>

<details>
<summary>Models and memory per mode</summary>

| Step | Local `quality` (default) | Local `balanced` | Local `speed` | Cloud |
| :-- | :-- | :-- | :-- | :-- |
| 1 · Read text | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/paddlepaddle.svg" width="14" height="14" alt="PaddlePaddle"> PP-OCRv6 Medium<br><sub>or Small · Tiny</sub> | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/paddlepaddle.svg" width="14" height="14" alt="PaddlePaddle"> PP-OCRv6 Small<br><sub>or Medium · Tiny</sub> | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/paddlepaddle.svg" width="14" height="14" alt="PaddlePaddle"> PP-OCRv6 Tiny<br><sub>or Medium · Small</sub> | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/google.svg" width="14" height="14" alt="Google"> Cloud Vision<br><sub>or <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/openai.svg" width="12" height="12" alt=""> OpenAI · <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/mistralai.svg" width="12" height="12" alt=""> Mistral</sub> |
| 2 · Verify OCR visually | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/cloudflare.svg" width="14" height="14" alt="Cloudflare"> Clef-Flash 9B<br><sub>or <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/liquidai.svg" width="12" height="12" alt="Liquid AI"> d1 3B</sub> | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/liquidai.svg" width="14" height="14" alt="Liquid AI"> d1 3B<br><sub>or <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/cloudflare.svg" width="12" height="12" alt="Cloudflare"> Clef-Flash 9B</sub> | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/liquidai.svg" width="14" height="14" alt="Liquid AI"> d1 3B<br><sub>or <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/cloudflare.svg" width="12" height="12" alt="Cloudflare"> Clef-Flash 9B</sub> | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/openai.svg" width="14" height="14" alt="OpenAI"> Decisions API<br><sub>or <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/typesafe.svg" width="12" height="12" alt=""> TypeSafe Jev</sub> |
| 3 · Detect injections | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/cloudflare.svg" width="14" height="14" alt="Cloudflare"> Clef-Flash 9B<br><sub>or <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/liquidai.svg" width="12" height="12" alt="Liquid AI"> d1 3B · <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/meta.svg" width="12" height="12" alt="Meta"> Prompt Guard 2</sub> | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/liquidai.svg" width="14" height="14" alt="Liquid AI"> d1 3B<br><sub>or <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/cloudflare.svg" width="12" height="12" alt="Cloudflare"> Clef-Flash 9B · <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/meta.svg" width="12" height="12" alt="Meta"> Prompt Guard 2</sub> | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/liquidai.svg" width="14" height="14" alt="Liquid AI"> d1 3B<br><sub>or <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/cloudflare.svg" width="12" height="12" alt="Cloudflare"> Clef-Flash 9B · <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/meta.svg" width="12" height="12" alt="Meta"> Prompt Guard 2</sub> | <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/openai.svg" width="14" height="14" alt="OpenAI"> Decisions API<br><sub>or <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/providers/typesafe.svg" width="12" height="12" alt=""> TypeSafe Jev</sub> |
| Memory, Apple Silicon or GPU&nbsp;¹ | 48 GB unified memory (measured)<br><sub>or 24 GB VRAM</sub> | ~16 GB unified memory<br><sub>or 16 GB VRAM</sub> | 16 GB unified memory (measured)<br><sub>or 16 GB VRAM</sub> | ~8 GB RAM<br><sub>no GPU needed</sub> |
| Memory, CPU only&nbsp;¹ | ~48 GB RAM | ~24 GB RAM | ~24 GB RAM | ~8 GB RAM |

¹ Estimates with the defaults; measured were `speed` on an Apple M2 with 16 GB and
`quality` on an Apple M4 Pro with 48 GB.
Decision models load unquantized: 16-bit on Apple Silicon and CUDA, 32-bit on CPU.
Clef-Flash 9B needs ~19 GB in 16-bit and ~38 GB in 32-bit. Disk space,
model IDs and pinned revisions are in [Models and hardware](https://github.com/EnXan/VIPI/blob/main/docs/models.md).

</details>

## Latest results

Development split of the
[VIPI evaluation dataset](https://huggingface.co/datasets/EnXan/VIPI-evaluation):
227 images with a prompt injection, 223 benign, default threshold 80.

- **Detection rate:** injection images reported as an injection. Higher is better.
- **False positive rate:** benign images wrongly reported. Lower is better.
- **Words recognized:** words in the images VIPI recognized, tolerating a
  small typo. Higher is better.

<p align="center">
  <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/diagrams/vipi-results.svg" alt="Bar charts of detection rate, false positive rate and words recognized: cloud configurations detect 74 to 85 percent of injections with 0.4 to 4.5 percent false positives and recognize 83 to 95 percent of words; local configurations detect 15 to 19 percent with 0 to 2.2 percent false positives and recognize 69 to 76 percent of words. Exact values and models are in the expandable tables below." width="900">
</p>

<details>
<summary>Exact values and models</summary>

| Cloud OCR | Detector | Detection rate | False positive rate | Words recognized |
| :-- | :-- | --: | --: | --: |
| Mistral OCR 4.1 | TypeSafe Jev 1.14 | 81.5% | **0.4%** | 83.2% |
| Mistral OCR 4.1 | OpenAI GPT-6 Luna (Decisions API) | **85.0%** | 4.5% | 83.2% |
| OpenAI GPT-6 Luna | OpenAI GPT-6 Luna (Decisions API) | 83.3% | 4.5% | **94.5%** |
| OpenAI GPT-6 Luna | TypeSafe Jev 1.14 | 78.9% | 1.3% | **94.5%** |
| Google Cloud Vision | OpenAI GPT-6 Luna (Decisions API, default) | 78.4% | 3.6% | 87.4% |
| Google Cloud Vision | TypeSafe Jev 1.14 | 74.0% | 0.9% | 87.4% |

| Local OCR | Detector | Detection rate | False positive rate | Words recognized |
| :-- | :-- | --: | --: | --: |
| PP-OCRv6 Medium (`quality`) | Clef-Flash 9B (default) | 16.7% | **0%** | **75.5%** |
| PP-OCRv6 Medium (`quality`) | Prompt Guard 2 86M | **19.4%** | 1.8% | **75.5%** |
| PP-OCRv6 Small (`balanced`) | d1 3B | 15.4% | 0.4% | 71.3% |
| PP-OCRv6 Small (`balanced`) | Prompt Guard 2 86M | 16.7% | 1.8% | 71.3% |
| PP-OCRv6 Tiny (`speed`) | d1 3B | 15.0% | 0.4% | 69.3% |
| PP-OCRv6 Tiny (`speed`) | Prompt Guard 2 86M | 18.5% | 2.2% | 69.3% |

</details>

## Usage

```bash
vipi scan label.png screenshot.jpg
vipi scan ./images --verbose --output report.json
vipi scan ./images --exclude 'generated/' --exclude '*.webp'
vipi scan . --diff origin/main --output report.json
vipi scan image.png --modus cloud --detector openai --threshold 90
```

| Format | Extensions | Notes |
| :-- | :-- | :-- |
| PNG | `.png` | Static images only; animated PNGs are rejected |
| JPEG | `.jpg`, `.jpeg` | EXIF orientation is applied |
| WebP | `.webp` | Static images only; animated WebPs are rejected |

Extensions are matched case-insensitively. Local inputs are limited to 40
megapixels; hosted inputs follow provider limits. Other file types in scanned
folders or diffs are skipped and listed in the report.

A score at or above the threshold (default 80/100) is a finding. Scores are not
calibrated probabilities, and a score below the threshold does not prove an
image is safe. Cloud scans can make additional billable requests.

| Exit code | Result |
| :-- | :-- |
| <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/readme/status-clean.svg" width="10" height="10" alt=""> `0` | Scan complete, no findings |
| <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/readme/status-injection.svg" width="10" height="10" alt=""> `1` | Injection found, every image completed |
| <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/readme/status-review.svg" width="10" height="10" alt=""> `2` | Error or incomplete scan; wins over findings |

Every option, credential and report field is in the
[CLI reference](https://github.com/EnXan/VIPI/blob/main/docs/cli.md).

## GitHub Actions

Scan the images a pull request adds or changes. This example uses the local
`balanced` profile with Meta Prompt Guard as the injection detector:

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
      - uses: EnXan/VIPI@v0.7.2
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

The runner needs enough memory for the chosen models, and Prompt Guard requires
accepted model terms on Hugging Face. Fork PRs normally get no secrets. For
hosted models, set `modus: cloud` and the provider keys; see
[Action inputs](https://github.com/EnXan/VIPI/blob/main/docs/cli.md#github-action).

## Documentation

- [CLI reference and platform validation](https://github.com/EnXan/VIPI/blob/main/docs/cli.md)
- [Models and hardware](https://github.com/EnXan/VIPI/blob/main/docs/models.md)
- [OCR recovery and measured limits](https://github.com/EnXan/VIPI/blob/main/docs/ocr-recovery.md)
- [Architecture](https://github.com/EnXan/VIPI/blob/main/docs/architecture.md) and [development](https://github.com/EnXan/VIPI/blob/main/docs/development.md)
- [Research CLI](https://github.com/EnXan/VIPI/blob/main/docs/research-cli.md), [workbench](https://github.com/EnXan/VIPI/blob/main/research/workbench/README.md) and [datasets](https://github.com/EnXan/VIPI/blob/main/research/README.md)
- [Decision records](https://github.com/EnXan/VIPI/blob/main/adr-code/README.md)

## License

VIPI's code, documentation and assets use the
[Apache License 2.0](https://github.com/EnXan/VIPI/blob/main/LICENSE). Models,
dependencies, datasets and provider marks keep their own terms.
