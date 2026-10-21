# ADR 0008: Research layout and dataset identity

Status: accepted, 2026-10-20

## Context and sources

- The working agreement requires the smallest structure that expresses current
  responsibilities, one concept per review, and evidence-based decisions.
- The research tree mixed dataset reference loading with web formatting and
  kept the detector command outside the workbench that owns its interface.
- The experiment directory grouped OCR rounds beside a separate Anamorpher
  folder named after one probe context.
- Dataset paths moved under `research/datasets/data/`, while catalog IDs hash
  image paths. The seven default screening IDs then matched zero active records;
  hashing the former logical `datasets/<path>` identity matched all seven.
- The active OCR index and its source transcripts are data records and are not
  changed by this layout decision.

## Decision

- `research/datasets/catalog.py` owns active index access, safe image paths,
  stable IDs and evaluation reference construction.
- `research/workbench/datasets.py` owns browser search presentation, category
  labels, API URLs and thumbnails.
- Detector CLI modules live under `research/workbench/`. The standalone module
  remains separate from the OCR workbench entry point so detector-only commands
  do not import the OCR runtime or Flask.
- Evaluation metrics and the evaluated OCR adapter stay under
  `research/evaluation/`.
- OCR experiments live under `research/experiments/ocr/`; Anamorpher image
  constructions and probes live under `research/experiments/anamorpher/`.
  Generated reports remain under the ignored `research/experiments/reports/`.
- Catalog IDs hash the logical image path rooted at `datasets/`, even when the
  current file is stored at `research/datasets/data/`. This preserves saved
  selection identifiers without changing the active index schema or paths.

## Alternatives

- Keeping catalog presentation in the dataset module would retain the current
  mix of data access and web concerns.
- Moving detector argument handling into the OCR CLI would load OCR dependencies
  for detector-only commands.
- Rewriting index paths or adding identifier fields would change active dataset
  data to compensate for a repository layout move.
- A plugin registry or shared experiment framework has no current requirement;
  the existing experiment rounds retain their distinct protocols.

## Consequences

Imports, command paths, tests and current guides follow the new directories.
The catalog IDs remain stable across the storage move. Newly prepared experiment
manifests record the new source paths. Existing local runs, reports and frozen
snapshots remain untouched and are not rerun by this refactor.

## Validation boundary

Validate catalog selection, reference construction, workbench browsing, detector
CLI help/import boundaries, and the seven default screening IDs against the
active catalog. No OCR inference, catalog rebuild, dataset generation or paid
provider call is required. Windows and Linux behavior remains unverified.
