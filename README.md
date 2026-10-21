# VIPI

<p align="center">
  <img src="assets/motion/vipi-reveal.gif" alt="Animated VIPI logo reveal" width="720">
</p>

<p align="center">
  Scan images for visual indirect prompt injections.
</p>

<p align="center">
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white"></a>
  <a href="docs/cli.md#platform-validation-status"><img alt="macOS smoke-tested" src="https://img.shields.io/badge/macOS-smoke--tested-2ea44f"></a>
  <a href="docs/cli.md#platform-validation-status"><img alt="Linux and Windows not tested" src="https://img.shields.io/badge/Linux%20%2F%20Windows-not%20tested-lightgrey"></a>
</p>

VIPI transforms each image through a multi-view OCR pipeline, then checks the
final recognized text with Jev, OpenAI Decisions or the local Prompt Guard model.
The public interface is a small command-line tool that can scan files,
directories and committed image changes.

## Quick start

VIPI requires Python 3.12 and [uv](https://docs.astral.sh/uv/). Install the OCR
extra, prepare the pinned PP-OCRv6 models once, then provide a Jev API key and
scan an image. Set `TYPESAFE_API_KEY` in the environment, or copy
[`.env.example`](.env.example) to `.env` and fill in the key before scanning:

`uv venv` creates the project environment in `.venv`. `uv sync --extra ocr`
installs VIPI and its OCR dependencies into that environment. Commands run with
`uv run` use `.venv` automatically, so you do not need to activate it yourself.

```bash
git clone https://github.com/EnXan/VIPI.git
cd VIPI
uv venv
uv sync --extra ocr
uv run vipi setup
uv run vipi scan image.png
```

Jev also accepts `JEV_API_KEY`. Model setup downloads and verifies the pinned
OCR files; scanning does not download models.

## Usage

```bash
# Scan one or more images
uv run vipi scan label.png screenshot.jpg

# Scan a directory recursively and save a JSON report
uv run vipi scan ./images --output report.json

# Choose a speed/quality mode or a specific supported model
uv run vipi scan ./images --ocr-mode fast
uv run vipi scan ./images --ocr-mode balanced
uv run vipi scan ./images --ocr-model ppocr-v6-medium

# Scan committed images added or modified on a branch
uv run vipi scan . --diff origin/main --output report.json

# Choose a detector and adjust the finding threshold
uv run vipi scan image.png --detector openai --threshold 90
```

The interface has two commands, `vipi setup` and `vipi scan`. OCR modes map
`fast` to PP-OCRv6 Tiny, `balanced` to Small and `quality` to Medium. `quality`
is the default to preserve the previous Medium behavior. `--ocr-model` selects a
supported model ID directly and overrides the mode. `vipi setup` prepares all
three models by default. The default detector is Jev with a threshold of 80 on a
0–100 score scale. A score at the threshold counts as a finding; it is not a
calibrated probability of an attack.

For local Prompt Guard, install its optional dependencies and prepare its model:

```bash
uv sync --extra ocr --extra detector-local
uv run vipi setup --detector prompt-guard
uv run vipi scan image.png --detector prompt-guard
```

OpenAI uses `OPENAI_API_KEY`. Prompt Guard runs locally and requires authorized
access to its model weights. See the [CLI guide](docs/cli.md) for provider setup,
GitHub Actions examples, branch-diff behavior, cache paths and report details.

## Results and automation

Exit codes support CI use:

| Code | Meaning |
| --- | --- |
| `0` | Scan completed without detections, or no images were selected |
| `1` | At least one image was detected |
| `2` | An error or incomplete scan occurred; errors take precedence |

VIPI provides the CLI for GitHub Actions workflows; this repository does not
currently include a packaged GitHub Action. See the [PR scan example](docs/cli.md#branch-and-pr-scans).

## Documentation

- [CLI usage and platform validation](docs/cli.md)
- [Package architecture](docs/architecture.md)
- [Development setup and checks](docs/development.md)
- [Research workbench and datasets](research/README.md)
- [Decision records](adr-code/README.md)

A built wheel contains the `vipi` package. Research tools, datasets, model
weights and run artifacts remain outside the runtime package.

## License

VIPI's original code, documentation and project assets are licensed under the
[Apache License, Version 2.0](LICENSE). Third-party models, dependencies,
datasets and other third-party material retain their own license terms; see
their respective notices and source projects.
