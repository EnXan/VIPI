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

VIPI uses signal-driven OCR recovery and checks the final text for prompt
injections. `--modus local` runs OCR, visual decisions and injection detection
locally. `--modus cloud` uses the selected hosted OCR and decision providers.
The CLI scans files, directories and committed image changes. Images with no
recognized text can still contain visual prompt injections.

Evaluation images, OCR references and detection labels are available in the
[VIPI Evaluation dataset](https://huggingface.co/datasets/EnXan/VIPI-evaluation).
See how to [download the pinned images](https://github.com/EnXan/VIPI/blob/main/research/README.md#download-images)
or [contribute new examples for review](https://github.com/EnXan/VIPI/blob/main/research/README.md#add-images).

## Installation

VIPI requires Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/).

### Fully local scans

```bash
uv tool install --python 3.12 'vipi-scanner[ocr,detector-local]'
vipi setup --modus local --ocr-mode balanced
vipi scan image.png --modus local --ocr-mode balanced
```

Local `quality` uses PP-OCRv6 Medium and Clef; `balanced` uses Small and d1-3B;
`speed`/`fast` uses Tiny and d1-3B. Quality is the default. Clef is a 27B model
and needs substantially more memory than d1-3B. Setup downloads pinned models;
scanning loads prepared local files. The selected decision model reviews OCR
and performs the final injection check. Local Prompt Guard remains an explicit
alternative for that final check via `--detector prompt-guard`.

### Cloud scans

```bash
uv tool install --python 3.12 'vipi-scanner[ocr]'
export GOOGLE_CLOUD_API_KEY="your-google-cloud-api-key"
export OPENAI_API_KEY="your-openai-api-key"
vipi setup --modus cloud
vipi scan image.png --modus cloud --output report.json
```

Cloud mode defaults to Google OCR and OpenAI Decisions for visual review and
injection detection. Choose OCR with `--ocr-provider google|openai|mistral` and
decisions with `--decision-provider openai|jev`. Jev uses `TYPESAFE_API_KEY`
(or `JEV_API_KEY`); Mistral uses `MISTRAL_API_KEY`. Use environment variables or
an ignored `.env` file. In PowerShell, set a key with
`$env:OPENAI_API_KEY = "your-openai-api-key"`.

Recovery can make additional billable OCR and decision requests. Reports save
usage, selection decisions and known fee estimates. A provider failure produces
an incomplete scan; providers are not switched automatically. See
[the recovery flow and measurement boundary](docs/ocr-recovery.md) and
[CLI options](docs/cli.md).

If `vipi` is not found, run `uv tool update-shell` and restart your terminal.

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
vipi scan image.png --modus cloud --detector openai --threshold 90
```

The interface has two commands, `vipi setup` and `vipi scan`. `--modus local`
is the default. Local profiles map `speed` to PP-OCRv6 Tiny, `balanced` to Small
and `quality` to Medium; `quality` is the default and `fast` remains an alias
for `speed`. `--ocr-model` selects a supported model directly; an explicit
execution mode must match it. `vipi setup` prepares all three local models by
default. The default detector follows the selected local/cloud decision model, with a threshold of 80 on a
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

      - uses: EnXan/VIPI@v0.7.0
        with:
          detector: prompt-guard
          modus: local
          ocr-mode: balanced
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}

      - name: Upload scan report
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: vipi-report
          path: vipi-report.json
```

This example uses d1-3B for OCR review and the local Prompt Guard detector.
The runner needs enough memory for the local d1 runtime; Clef quality needs
considerably more memory. Accept the model terms and add `HF_TOKEN` as a repository Actions secret
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
