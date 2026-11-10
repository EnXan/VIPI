# 0058 — Reuse OCR and detection results across evaluation runs

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
appears in the report, the user chose: original figures, marked. After the
first version (OCR only, detection always again), the user asked the same day
to reuse detection too when one exists for exactly that model and the current
version.

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
- **Full identity**: the OCR identity plus the detection settings
  (`ScanOptions.detection_options()`: detector, threshold, checks), the hashes
  of all files under `src/vipi/` and all recorded package versions except the
  product's own version label (`vipi-scanner`), since its sources are compared
  file by file. Model identifiers are constants in `src/vipi/config.py` and
  `decision_models.json`, so they are covered by the source hashes.
- An image reuses a completed row of any run in the runs folder with the same
  OCR identity and the same image hash, preferring a row whose full identity
  also matches, then the newest. Its artifacts are copied into a new product
  run folder by hard links (a copy across file systems; artifacts are only
  ever replaced atomically, so the earlier run stays unchanged) and
  `result.json` gets the new run ID. With a full match the
  earlier `detection/` is copied too and the earlier detection record is taken
  without any call; otherwise `detection/` is left out and detection runs. If
  the earlier artifacts are missing or `result.json` changed, the image is
  scanned normally. The OCR session opens only for an image that needs OCR.
- Reused rows are marked `ocr_reused_from` (run ID, configuration, product run
  folder name, `detection` true or false) and keep the original time, cost and
  retained usage: the earlier image time with a full match, else the earlier
  OCR time plus this detection. The run's `report.md` gets a **Reused
  results** section and `summary.json` a `reused` entry with the number of
  reused images, how many of them with detection, and the cost not spent
  again. Both are computed in `ocr_reuse.py`, outside the scored report
  (`benchmark_report.py` is a metric source whose hash is part of every
  baseline's identity, so changing it would turn every baseline stale).
- On by default: `research.evaluate run` (`--no-reuse-ocr` turns it off;
  `--dry-run` prints both counts), the workbench checkbox **Reuse results of
  earlier runs** with both counts, and the benchmark option
  `--reuse-ocr-from RUNS_DIR`. The choice is stored in `request.json`; a
  resumed run keeps it. Runs from before this decision resume without reuse.

## Alternatives

- *Match on settings only*: reuses more, but after an OCR code change a run
  would silently score old OCR.
- *Always run detection again*: the first version. Repeating a run on
  unchanged code then paid for detection whose result was known.
- *Report only this run's spend* (reused OCR as 0 s and $0): shows the real
  spend, but time and cost no longer compare with full runs.
- *A separate OCR cache keyed by image*: duplicates what runs already retain
  and needs its own cleanup.

## Consequences

A reuse run measures detection on OCR produced earlier, and a full match
repeats the earlier detection; nondeterministic cloud OCR and cloud detection
are not re-sampled, and a provider-side change of a hosted model behind the
same identifier is not detected. Turn reuse off to measure that variance. Unrelated edits under `src/vipi/` outside the excluded
files (for example `results.py`) prevent reuse until a new full run exists.
Reuse depends on the product run folders in the OS cache
(`~/Library/Caches/vipi/runs/` on macOS); if they are cleared, images are
scanned again. Each reused image adds a run folder of hard links there (about
2 to 9 MB per image if the cache sits on another file system and they are
copied).

## Validation boundary

Tests cover both identities (the OCR identity ignores detector and detection
sources; the full identity counts detector, threshold, every product source
and package but not research sources or the version label), the preference
for full matches, image hash matching, restoring with and without detection
and refusing changed output, the worker paths (no OCR session for reused
images, no detection call for full matches, markers, original time and cost,
session metadata), the report line, the CLI, run and workbench options and
resuming with the stored choice. Against the real runs, `--dry-run` reported
for `cloud-google` and `local-speed` 450 of 450 reusable including detection,
for `cloud-google-jev` 450 OCR only, and 0 for `local-balanced`. A real 3-image
`local-speed` benchmark reused OCR alone with the same OCR text and d1 scores
as the original run (first version), and reused whole results in 1.3 seconds
with identical detection records. A complete `local-speed` evaluation of the
450 development images reused every result in 60 seconds (the baseline run
took 48 minutes), matched the baseline as the same inputs with every OCR and
detection metric unchanged, and left the free disk space unchanged. Both
saved baselines stay fresh. No paid run with reuse has been executed. The workbench
checkbox and both counts were checked in the browser.
