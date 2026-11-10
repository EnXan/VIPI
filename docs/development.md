# Development

Use Python 3.12 and uv. From the repository root:

```bash
uv sync --extra ocr --extra detector-local --extra research --extra test
```

`uv run` uses the synchronized `.venv` without activation. Use `uv add` and
`uv remove` for dependencies and keep `uv.lock` synchronized. Additional OCR
model environments are described in the
[research CLI reference](research-cli.md#separate-model-environments).

## Commands and checks

The [product CLI reference](cli.md) and [research CLI reference](research-cli.md)
document the complete command sets. Common development commands:

```bash
uv run vipi setup --ocr-mode balanced
uv run vipi scan image.png --ocr-mode balanced
uv run python -m research.download
uv run python -m research.workbench serve
```

The CLI and the workbench use the platform user cache for models and scan
runs; evaluation runs go to the repository's ignored `runs/evaluations/`.
Dataset downloads and contributions are described in the
[research guide](../research/README.md). Preserve exact transcripts and provenance.

```bash
uv run pytest -q tests/unit tests/integration tests/research
uv run ruff check src/vipi research tests
uv build
```

Changes that claim a quality or efficiency improvement also need a matched
baseline/candidate comparison; see
[evaluating improvements](../CONTRIBUTING.md#evaluating-improvements).

Tests use temporary catalogs, fixture engines and simulated provider responses;
they require no paid API calls. Builds and help smoke tests do not establish
trained-model accuracy. Report the actual operating system/model tested; see
[platform validation](cli.md#platform-validation-status).

## Releases

Include a version bump in the same PR as release-worthy changes:

```bash
uv version --bump patch
```

Use minor for new features and pre-1.0 intentional breaking changes. After 1.0,
use major for breaking changes. Update current documentation/examples referring
to the previous version; preserve clearly historical references. The version
command updates `pyproject.toml` and `uv.lock`.

After the version PR merges and CI passes, update `main` and push an annotated
tag matching `uv version --short`. For version 0.6.1:

```bash
git switch main
git pull --ff-only
git tag -a v0.6.1 -m "Release v0.6.1"
git push origin v0.6.1
```

The `v*` tag starts CI, builds distributions and publishes to PyPI through
Trusted Publishing. A merge alone does not publish. Verify the tag workflow
and publication; never reuse a published version.
