# VIPI — Visual Prompt Injection Scanner for Images

<p align="center">
  <img src="https://raw.githubusercontent.com/EnXan/VIPI/main/assets/motion/vipi-reveal.gif" alt="Animated VIPI logo reveal" width="720">
</p>

<p align="center">
  A Python CLI and GitHub Action that use OCR to detect prompt injections in images.
</p>

<p align="center">
  <a href="https://github.com/EnXan/VIPI/blob/main/pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white"></a>
  <a href="https://github.com/EnXan/VIPI/blob/main/docs/cli.md#platform-validation-status"><img alt="macOS supported" src="https://img.shields.io/badge/macOS-tested-2ea44f"></a>
  <a href="https://github.com/EnXan/VIPI/blob/main/docs/cli.md#platform-validation-status"><img alt="Linux supported" src="https://img.shields.io/badge/Linux-tested-2ea44f"></a>
  <a href="https://github.com/EnXan/VIPI/blob/main/docs/cli.md#platform-validation-status"><img alt="Windows supported" src="https://img.shields.io/badge/Windows-tested-2ea44f"></a>
</p>

VIPI transforms each image through a multi-view OCR pipeline, then checks the
final recognized text with Jev, OpenAI Decisions or the local Prompt Guard model.
The public interface is a small command-line tool that can scan files,
directories and committed image changes. Because detection evaluates OCR text,
images that yield no recognized text may still contain visual prompt injections.

Evaluation images, OCR references and detection labels are available in the
[VIPI Evaluation dataset](https://huggingface.co/datasets/EnXan/VIPI-evaluation).
See how to [download the pinned images](https://github.com/EnXan/VIPI/blob/main/research/README.md#download-images)
or [contribute new examples for review](https://github.com/EnXan/VIPI/blob/main/research/README.md#add-images).

## Installation

VIPI requires Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Install the CLI from [PyPI](https://pypi.org/project/vipi-scanner/) with
`uv tool install`. Choose the install path for the detector you plan to use.
Both paths include the OCR dependencies. OCR uses the local models by default;
you can explicitly select Mistral OCR for hosted image recognition.

### Cloud API detector

For Jev or OpenAI, install VIPI with its OCR extra:

```bash
uv tool install --python 3.12 'vipi-scanner[ocr]'
vipi setup
```

Set the credential for the detector you will use before scanning. Jev accepts
`TYPESAFE_API_KEY` (or the alias `JEV_API_KEY`); OpenAI uses `OPENAI_API_KEY`.
For example, set one in your shell before running `vipi scan`:

```bash
# macOS / Linux
export TYPESAFE_API_KEY="your-typesafe-api-key"

# Windows PowerShell
$env:TYPESAFE_API_KEY = "your-typesafe-api-key"
```

For OpenAI, set `OPENAI_API_KEY` in place of `TYPESAFE_API_KEY`. The default
detector is Jev; select OpenAI with `--detector openai`.

```bash
vipi scan image.png
```

### Cloud OCR

Local OCR is the default. Select `--modus cloud` to send each image to Google
Cloud Vision, or choose another OCR provider explicitly. The downstream detector
is selected independently.

```bash
export GOOGLE_CLOUD_API_KEY="your-google-cloud-api-key"
vipi setup --modus cloud
vipi scan image.png --modus cloud --output report.json

# Alternatives: configure OPENAI_API_KEY or MISTRAL_API_KEY respectively
vipi scan image.png --modus cloud --ocr-provider openai
vipi scan image.png --modus cloud --ocr-provider mistral
```

Cloud providers are `google` (Google Cloud Vision, default), `openai` (GPT-6
Luna), and `mistral` (Mistral OCR 4.1). They are provider choices, not quality
tiers. Cloud OCR uses one original-image request per image, with no automatic
retries or fallback. Setup skips local OCR downloads; credentials are checked
at scan time. Keep keys in the environment or an ignored `.env` file; VIPI
does not write them into reports. Provider usage charges apply.

### Local Prompt Guard detector

To run the detector locally, install the OCR and local-detector extras, then
prepare Prompt Guard and its model weights:

```bash
uv tool install --python 3.12 'vipi-scanner[ocr,detector-local]'
vipi setup --detector prompt-guard
vipi scan image.png --detector prompt-guard
```

Prompt Guard weights require authorized access to the
[Prompt Guard model](https://huggingface.co/meta-llama/Prompt-Guard-86M). Visit
its model page and accept Meta's access terms first. If you need a Hugging Face
token, install the [Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/guides/cli)
and run `hf auth login`; the Hugging Face Hub client will use the saved login
when downloading the model. You can also provide a token through `HF_TOKEN`.
OCR model setup downloads the pinned PP-OCRv6 files for both install paths;
scanning does not download models.

If `vipi` is not found after installation, run `uv tool update-shell` and
restart your terminal so uv's tool directory is added to `PATH`.

## Usage

```bash
# Scan one or more images
vipi scan label.png screenshot.jpg

# Scan a directory recursively and save a JSON report
vipi scan ./images --output report.json

# Choose a speed/quality mode or a specific supported model
vipi scan ./images --ocr-mode speed
vipi scan ./images --ocr-mode balanced
vipi scan ./images --ocr-model ppocr-v6-medium

# Scan committed images added or modified on a branch
vipi scan . --diff origin/main --output report.json

# Choose a detector and adjust the finding threshold
vipi scan image.png --detector openai --threshold 90
```

The interface has two commands, `vipi setup` and `vipi scan`. `--modus local`
is the default. Local profiles map `speed` to PP-OCRv6 Tiny, `balanced` to Small
and `quality` to Medium; `quality` is the default and `fast` remains an alias
for `speed`. `--ocr-model` selects a supported model directly; an explicit
execution mode must match it. `vipi setup` prepares all three local models by
default. The default detector is Jev with a threshold of 80 on a
0–100 score scale. A score at the threshold counts as a finding; it is not a
calibrated probability of an attack.

See the [CLI guide](https://github.com/EnXan/VIPI/blob/main/docs/cli.md) for provider configuration, GitHub Actions
examples, branch-diff behavior, cache paths and report details.

## Results and automation

Exit codes support CI use:

| Code | Meaning |
| --- | --- |
| `0` | Scan completed without detections, or no images were selected |
| `1` | At least one image was detected |
| `2` | An error or incomplete scan occurred; errors take precedence |

## GitHub Actions

Add this workflow at `.github/workflows/vipi-scan.yml` to scan images added or
modified in pull requests targeting `main`:

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

      - uses: EnXan/VIPI@v0.5.0
        with:
          detector: prompt-guard
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}

      - name: Upload scan report
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: vipi-report
          path: vipi-report.json
```

This example uses the local Prompt Guard detector; inference runs on the GitHub
runner. Accept the model terms and add `HF_TOKEN` as a repository Actions secret
so the runner can download the gated weights. Fork pull requests do not receive
repository secrets, so a cache miss for those weights makes the scan fail
closed. Jev and OpenAI are also available and need their API keys; see the
[CLI guide](https://github.com/EnXan/VIPI/blob/main/docs/cli.md#branch-and-pr-scans) for other detectors, scan inputs,
diff behavior and report details.

## Documentation

- [CLI usage and platform validation](https://github.com/EnXan/VIPI/blob/main/docs/cli.md)
- [Package architecture](https://github.com/EnXan/VIPI/blob/main/docs/architecture.md)
- [Development setup and checks](https://github.com/EnXan/VIPI/blob/main/docs/development.md)
- [Research workbench and datasets](https://github.com/EnXan/VIPI/blob/main/research/README.md)
- [Decision records](https://github.com/EnXan/VIPI/blob/main/adr-code/README.md)

A built wheel contains the `vipi` package. Research tools, datasets, model
weights and run artifacts remain outside the runtime package.

## License

VIPI's original code, documentation and project assets are licensed under the
[Apache License, Version 2.0](https://github.com/EnXan/VIPI/blob/main/LICENSE). Third-party models, dependencies,
datasets and other third-party material retain their own license terms; see
their respective notices and source projects.
