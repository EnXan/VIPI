# Contributing

Thanks for helping improve VIPI. Contributions are welcome through GitHub pull
requests.

## Before you start

For a substantial change, open an issue first to discuss the approach. For a
small bug fix or documentation improvement, you can open a pull request
directly. Please keep changes focused and avoid including unrelated cleanup.

## Development setup

VIPI development uses Python 3.12 and [uv](https://docs.astral.sh/uv/).
From the repository root, install the project and the dependencies used by the
development checks:

```bash
uv sync --extra ocr --extra detector-local --extra research --extra test
```

See [Development](docs/development.md) for available commands and setup details.

## Project boundaries

- Product code belongs under `src/vipi/`.
- Research tools belong under `research/` and may import `vipi`; product code
  must not depend on research tools or Flask.
- Preserve dataset source files, reference transcripts, and provenance when
  working with research data. Read the relevant `AGENTS.md` and dataset
  catalog guide before changing datasets or dataset tooling.
- Do not commit API keys, credentials, downloaded model weights, or generated
  run artifacts.

## Pull requests

1. Create a branch for your change (or work in a fork).
2. Make the smallest focused change that addresses the issue.
3. Run the relevant checks and include their results in the pull request.
4. Open a pull request targeting `main` and complete the pull request template.
5. Respond to review feedback and make sure required checks pass before merge.

The project uses automated checks and requires an approving review before a
pull request can be merged. GitHub requests review from the repository's
CODEOWNER for pull requests targeting `main`.
