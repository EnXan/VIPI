# Architecture

Accepted package boundaries are recorded in [ADR 0002](../adr-code/0002-product-and-research-boundaries.md).
The public scan contract is recorded in [ADR 0003](../adr-code/0003-public-cli-contract.md).
The current OCR behavior and evaluation boundary are recorded in [ADR 0007](../adr-code/0007-reduced-ocr-transforms.md).
Research module ownership and dataset distribution are recorded in
[ADR 0012](../adr-code/0012-hugging-face-evaluation-dataset.md).

VIPI is one installable Python package, `vipi`, with the public commands
`vipi setup` and `vipi scan`. The repository also contains a separate research
environment, tests and dataset tools. Model weights, run artifacts, datasets and
the research web UI are not included in the wheel.

## Product boundaries

| Module | Owns |
| --- | --- |
| `vipi.cli` | Argument parsing, terminal interaction and process exit codes |
| `vipi.scanner` | A shared image scan and sequential scans of selected inputs |
| `vipi.inputs` | File discovery and immutable Git branch-diff inputs |
| `vipi.ocr` | Transformations, OCR engines, assembly and reusable model sessions |
| `vipi.detection` | Evidence, provider checks, score policies and saved-run replay |
| `vipi.results` | `OcrResult`, `DetectionResult` and `ScanResult` at component boundaries |
| `vipi.config` | Public defaults, validated `ScanOptions`, cache paths and credential resolution |
| `vipi.model_setup` | Explicit preparation of the release-pinned models |
| `vipi.reporting` | Conversion to the CLI report schema and its exit policy |
| `vipi.storage` | Atomic JSON, file hashes, run artifacts and transport-independent events |

The data flow is:

```text
CLI -> file/Git inputs -> scanner.scan_image
                           -> OCR -> OcrResult
                           -> detection -> DetectionResult
                           -> ScanResult -> report/exit code
```

`scan_image()` accepts image bytes or a path. It needs no existing OCR run,
dataset catalog or web application. Model sessions and providers can be reused
across an image selection. Scans continue to save input copies, transformed
images and reproducible detection artifacts; partial OCR failures retain their
artifact location in the report.

The detector's `detect(evidence, image=...)` path can operate in memory without
filesystem artifacts. `detect_ocr()` consumes an `OcrResult` directly, avoiding a
JSON write/read handoff. `detect_saved_run()` is the explicit adapter for loading
previous runs and replaying compatible provider answers. Both adapters share the
same detection and verdict implementation. Only final OCR text enters text
detectors; dataset references never become classifier evidence.

## OCR replacement

`OcrEngine.recognize(image)` returns text and regions in raster coordinates.
Transformation/assembly code uses this contract rather than a provider-specific
result. `OcrSession` owns the engine pool, model verification and artifact details.
`OCR_MODES`, `REQUIRED` and `model_files.json` map the public speed/quality modes
to checksum-pinned models. Setup and scan use that same description. A model
replacement changes this package/adapter, not input selection or detector code.

## Research boundary

`research/` imports `vipi`; `vipi` must not import `research` or Flask. Package
initializers and model metadata imports do not load inference frameworks.

- `research/workbench/`: local Flask UI, dataset browsing, uploads, batches, SSE
  and diagnostic commands.
- `research/ocr_eval/`: active OCR reference catalog, evaluation metrics and
  the adapter used by the workbench.
- `research/detection_eval/`: reviewed image prompt-injection cases, labels and
  ignored local image files.

OCR and detector stores keep their distinct states. Shared atomic writes, hashes
and event iteration are consolidated; SSE encoding is a workbench adapter.
Persisted JSON schemas and run directory layouts are shared across the product
and research tools. OCR paths, source transcripts and local image data live
under `research/ocr_eval/images/`, indexed by `research/ocr_eval/catalog.json`.
The catalogs and image files are downloaded from the Hugging Face dataset at
the commit pinned in `research/dataset.json`; GitHub tracks evaluation code.

## Dependencies and tests

`ocr` and `ocr-cuda` select alternative OCR runtimes. `detector-local` supplies
Prompt Guard and its model-download client. `research` supplies Flask for the
local workbench; `test` supplies pytest and Ruff. The published CLI does not
install Flask by selecting `ocr`.

Tests are grouped into `tests/unit`, `tests/integration` and `tests/research`.
Boundary tests prevent imports from the product into research/web frameworks and
verify direct detection without reading a saved OCR run. The wheel includes only
`src/vipi`; source distributions include the product tests and their fixtures.
