# Development

Use Python 3.12 and uv. From the repository root, create and activate the
project environment:

```bash
uv venv
```

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Then synchronize the product and development dependencies into `.venv`:

```bash
uv sync --extra ocr --extra detector-local --extra research --extra test
```

Then run project commands through `uv run` so they use the synchronized
environment. `uv run` also selects the project environment when it is not
activated.

## Commands

Public product commands:

```bash
uv run vipi setup
uv run vipi scan image.png
uv run vipi scan . --diff origin/main --output report.json
```

Research commands, run from the repository root:

```bash
uv run python -m research.datasets.setup
uv run python -m research.workbench serve
uv run python -m research.workbench extract image.png --model ppocr-v6
uv run python -m research.workbench extract image.png --evaluate
uv run python -m research.workbench reassemble RUN_ID
uv run python -m research.workbench.detector_cli detect RUN_ID --text-classifier jev
uv run python -m research.experiments.ocr.ocr_screening --help
```

The public CLI uses its user cache. Workbench defaults continue to use the
repository's `models/ocr`, `models/detector` and `runs` directories, with its
existing path options. Prepare workbench models separately using
`uv run python -m research.workbench prepare-models --model ppocr-v6`.

## Releases and versioning

Update the package version with `uv` when preparing a release. For example, a
backward-compatible bug fix uses:

```bash
uv version --bump patch
```

Use `uv version --bump minor` for a new feature. VIPI is currently before
`1.0.0`: while the public interface is still developing, use a minor bump for
intentional breaking changes as well, and describe those changes in the release
notes. After `1.0.0`, follow Semantic Versioning: patch for compatible fixes,
minor for backward-compatible features, and `uv version --bump major` for
breaking changes. The version command updates `pyproject.toml` and keeps
`uv.lock` in sync.

Include the version change in a pull request. After that commit has been merged
to `main` and CI passes, tag the commit with the same version, prefixed with
`v`, and push the tag:

```bash
git switch main
git pull --ff-only
git tag -a v0.1.1 -m "Release v0.1.1"
git push origin v0.1.1
```

Pushing a tag that starts with `v` starts the release workflow. It verifies the
tag against the project version, runs CI, builds the distributions, and
publishes them to PyPI using Trusted Publishing. Merging to `main` alone does
not publish a release. Each PyPI release needs a new version and tag; do not
reuse a version that has already been published.

## Verification

```bash
uv run pytest -q tests/unit tests/integration
uv run pytest -q tests/research
uv run ruff check src/vipi research/workbench research/evaluation research/datasets/catalog.py tests
uv build
```

The research tests use temporary catalog fixtures rather than rebuilding or
modifying the active dataset. Raw source datasets and current OCR indexes stay
under `research/datasets/data/`; catalog access and dataset tools live in
`research/datasets/`. Follow `AGENTS.md` and the
[catalog guide](../research/datasets/data/catalog/README.md) before changing them.

Windows and Linux have not been tested; see the [platform status](cli.md#platform-validation-status).
No live paid provider calls are required by the automated suite.
