# 0058 — Reuse OCR results across evaluation runs

Status: accepted, 2026-11-10.

## Context and sources

An evaluation run scans every image of a split: OCR, OCR review, then
detection. Comparing detectors on the same OCR
([ADR 0057](0057-jev-detector-configurations.md), e.g. `cloud-google-jev`
after `cloud-google`) repeated the paid cloud OCR although its result was
already known. In the `cloud-google` development run of 2026-11-10, OCR and
review cost about $0.0046 per image and detection about $0.00004. The user
asked on 2026-11-10 to reuse known OCR results, with a checkbox that is on by
default and must be turned off to run everything. Asked how strict a match
must be, the user chose: same settings and same OCR code. Asked how reused OCR
appears in the report, the user chose: original figures, marked.

Every benchmark run already retains what reuse needs: per-file hashes of
`src/vipi/**` and package versions (`benchmark/manifest.json` provenance), the
image hash per entry, and per row the OCR artifacts (`result.json`,
`input.png`, OCR steps and review decisions) with the hash of `result.json`.

## Decision

- **OCR identity** (`research/ocr_eval/ocr_reuse.py`): resolved OCR model, OCR
  mode, review (decision) provider; hashes of all files under `src/vipi/`
  except those that only serve detection, input selection or the CLI
  (`detection/` other than `detection/providers/http.py`, `inputs/`,
  `__main__.py`, `cli.py`, `model_setup.py`, `reporting.py`, `scanner.py`);
  Pillow and numpy versions, plus rapidocr, onnxruntime, torch and
  transformers for local configurations. The detector is not part of it.
- An image reuses the newest completed row of any run in the runs folder with
  the same OCR identity and the same image hash. Its artifacts are copied
  (without `detection/`) into a new product run folder, `result.json` gets the
  new run ID, and only detection runs. If the earlier artifacts are missing or
  `result.json` changed, the image is scanned normally. The OCR session opens
  only for an image that needs OCR.
- Reused rows are marked `ocr_reused_from` (run ID, configuration, product run
  folder name), keep the original OCR time, cost and retained usage, and add
  this run's detection time. The report states the number of reused images and
  the OCR cost not spent again.
- On by default: `research.evaluate run` (`--no-reuse-ocr` turns it off;
  `--dry-run` prints the reusable count), the workbench checkbox **Reuse OCR
  results from earlier runs** with the count, and the benchmark option
  `--reuse-ocr-from RUNS_DIR`. The choice is stored in `request.json`; a
  resumed run keeps it. Runs from before this decision resume without reuse.

## Alternatives

- *Match on settings only*: reuses more, but after an OCR code change a run
  would silently score old OCR.
- *Report only this run's spend* (reused OCR as 0 s and $0): shows the real
  spend, but time and cost no longer compare with full runs.
- *A separate OCR cache keyed by image*: duplicates what runs already retain
  and needs its own cleanup.

## Consequences

A reuse run measures detection on OCR produced earlier; nondeterministic cloud
OCR is not re-sampled. Unrelated edits under `src/vipi/` outside the excluded
files (for example `results.py`) prevent reuse until a new full run exists.
Reuse depends on the product run folders in the OS cache
(`~/Library/Caches/vipi/runs/` on macOS); if they are cleared, images are
scanned again. Each reused image adds a copy of its OCR artifacts there.

## Validation boundary

Tests cover the identity (detector and detection sources ignored; OCR
settings, OCR sources, the shared HTTP client and local packages counted), the
newest-candidate choice, image hash matching, restoring without detection and
refusing changed output, the worker path (no OCR session for reused images,
marker, original time and cost, session metadata), the report line, the CLI,
run and workbench options and resuming with the stored choice. Against the
real runs, `--dry-run` reported 450 of 450 reusable for `cloud-google-jev`,
`cloud-google` and `local-speed`, and 0 for `cloud-mistral` and
`local-balanced`. A real 3-image `local-speed` benchmark with reuse produced
the same OCR text and the same d1 scores as the original run. The workbench
checkbox and count were checked in the browser. No paid run with reuse has
been executed.
