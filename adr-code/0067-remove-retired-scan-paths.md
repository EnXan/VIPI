# ADR 0067: Product boundaries without retired scan paths

Status: Accepted, 2026-11-10. Replaces ADR 0002 and ADR 0045.

## Context and sources

The maintainer requested removal of the unused OCR pipeline, unused functions
and detector modes identified in the project audit, together with unused
dependencies and corresponding documentation/onboarding corrections in one PR.
The public commands remain `vipi setup` and `vipi scan`.

The repository's scanner, workbench and benchmark all use
[`OcrSession`](../src/vipi/ocr/session.py) and shared
[`recovery.pipeline`](../src/vipi/ocr/recovery/pipeline.py). Only tests called the
old fixed-transform runner, per-view metric aggregators and detector comparison,
image/context and saved-run replay paths. [ADR 0055](0055-workbench-without-research-model-tools.md)
had already removed their research application interfaces.

### Superseded decisions

- **ADR 0002, Product and research boundaries** (2026-10-19): consolidated the
  former product packages into `vipi`, separated research/UI/data tools from
  product code and introduced typed scan results. It retained explicit saved-run
  detector replay and shared file/event operations to avoid filesystem handoffs
  while supporting the then-current research interfaces. The package boundaries
  and direct result flow remain; replay has no current application consumer and
  is removed. Its former two-catalog paths were subsequently replaced by ADR 0053.
  Its historical validation covered 215 fixture tests, packaging and an OCR
  smoke run with a simulated detector, not present-day provider quality.
- **ADR 0045, Explicit ownership of shared OCR recovery** (2026-11-01): grouped
  promoted recovery modules under `vipi.ocr.recovery`, removed research aliases,
  kept engines/transforms/assembly/costs shared and left the fixed-transform
  runner for workbench comparisons. The rationale was clear ownership and direct
  imports. Ownership remains; the runner no longer serves the workbench and is
  removed. Its historical checks covered 458 tests, packaging and executable-AST
  parity of the moved recovery functions, not new live model measurements.

These summaries carry forward the previous rationale before their files are
removed. This decision does not replace the recovery policy in ADR 0044 or the
explicit retention of experiment operators in ADR 0055.

## Decision

- Publish one `vipi` package. Keep input selection, OCR, detection, reporting
  and storage distinct. Research/workbench/evaluation/curation tools import
  product code; product code imports neither research nor Flask. Model weights,
  datasets, run artifacts and the workbench stay outside the wheel.
- Use typed OCR/detection/scan results and pass fresh OCR directly to one final
  text detector. Keep recovery orchestration, attempts, selection, layout,
  decisions, probes, tile retries and retention under `vipi.ocr.recovery`.
  Engines, raster transformations, assembly and API-cost accounting stay shared
  under `vipi.ocr`; no new registry or abstraction is introduced.
- Remove the fixed-transform OCR runner/reassembly API, its non-native RapidOCR
  mode, retired resize backends/profile catalog, old per-view/category evaluation
  aggregators, detector multi-provider/image/context modes and saved-run replay.
  Remove their unused event iterators, detector-store readers and helper fields.
  Keep active event callbacks and persisted diagnostic artifacts.
- Keep dataset scoring in `research.ocr_eval.benchmark_report`, using the shared
  final-word/geometry comparison. Evaluation run comparison and successful
  OCR/detection reuse remain in `research.evaluate` and `research.ocr_eval.ocr_reuse`.
- Remove TensorFlow and the direct Research SciPy dependency after checking
  project use and the hash-verified pinned d1/Clef-Flash sources. Their deleted
  paths were resize experiments and removed research analysis. Keep PyTorch in
  `detector-local`, where local inference needs it, and remove it from OCR extras.
- Preserve current scanner defaults, provider payload/policy, OCR recovery
  decisions, CLI reports and exit codes. Internal detector input/result artifacts
  use schema version 3 after removal of replay/context/comparison fields.
  Historical baselines, transcripts and measured results remain unchanged.

## Alternatives and consequences

Keeping test-only application paths would preserve ambiguous interfaces and
unnecessary installation dependencies. Compatibility shims or reintroducing
workbench controls would add code without a current requirement; neither is
selected. External scripts importing retired internal functions must migrate to
`scan_image` or the documented research commands.

The wheel has one OCR workflow. Cloud OCR installation does not need PyTorch or
TensorFlow. The diagrammed product flow and product/research boundary already
describe this workflow and remain accurate. Documentation identifies the active
entrypoints and distinguishes current measurements from historical reports.

Baseline freshness and reuse compare whole source files. Removing unused code
from metric/product files can therefore invalidate an earlier identity despite
unchanged scoring or scan behavior. Do not rewrite saved baseline hashes to hide
that difference; refresh measurements separately when a future comparison needs
them. This cleanup makes no quality or latency improvement claim.

## Validation boundary

Fixture-based product, integration and research checks exercise the retained
recovery, text detector, geometry/word metrics, cloud transports and local model
adapters. Relevant old tests migrate to active interfaces; tests exclusively for
retired behavior are removed. Dependency installation/build checks and frozen
output comparisons are recorded in the PR.

These checks do not establish trained-model accuracy, calibrated scores, fresh
provider behavior or Windows/Linux inference support. Local model code is checked
at pinned hashes without downloading weights or making paid inference requests.
