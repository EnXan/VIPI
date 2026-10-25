# ADR 0002: Product and research boundaries

Status: Accepted. Recorded: 2026-10-19.

## Context and sources

The user approved consolidation of the previous `vipi`, `ocr_pipeline` and
`detector` packages and separation of research tools, then asked to place the
remaining dataset scripts with research code. Those scripts handle data
import, generation, review, catalog building and inventory; none are part of
the public runtime. The implementation is shown by [package configuration](../pyproject.toml),
[scanner](../src/vipi/scanner.py), [OCR evaluation](../research/ocr_eval/)
and [architecture documentation](../docs/architecture.md).

## Decision

Publish one `vipi` package. Keep input selection, OCR, detection, reporting and
storage distinct. Put the local web workbench, reference evaluation and
experiments in `research/`, importing the product in one direction only. The
current OCR catalog and evaluation support live in `research/ocr_eval/`; the
workbench lives in `research/workbench/`; image-detection fixtures live in
`research/detection_eval/`. Dataset import and generation tools are no longer
retained in the repository.
Use typed OCR/detection/scan boundaries and pass fresh OCR results directly to
text detection. Keep saved-run replay as an explicit adapter. Share small file
and event operations while preserving distinct OCR and detection states.

## Alternatives

Keeping three top-level packages and file-based handoffs would retain coupling.
Separate services or a general plugin framework would add machinery without a
current requirement. Merging all stores would hide their different state models.
Keeping dataset utilities in a separate top-level `scripts/` directory would
split research implementation across two roots.

## Consequences

The product wheel excludes research UI, dataset tools and data, models, and run
artifacts. A future API can call the existing image scan. Research commands run
from the checkout using paths under `research/`; the public CLI keeps its agreed
interface. PP-OCRv6 can be replaced through the engine contract and pinned
model description.

## Validation boundary

The preceding implementation turn passed 215 tests, Ruff, package build and
installation outside the repository, and a complete 170-pass OCR smoke run with
real weights and a simulated detector. Those are historical validation results,
not tests rerun by this documentation change. See [boundary tests](../tests/unit/test_architecture.py)
and [scanner integration tests](../tests/integration/test_vipi_cli.py).
Windows/Linux execution and live provider quality remain unverified.
