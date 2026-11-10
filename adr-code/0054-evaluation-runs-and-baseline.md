# ADR 0054: Evaluation runs of product scan configurations against a saved baseline

Status: accepted, 2026-11-09. Implemented in the CLI (`python -m research.evaluate`)
and the workbench.

## Context and sources

The user asked for one simple, unambiguous way to evaluate a change and to
keep a baseline, usable from the workbench and the CLI. Asked on 2026-11-09,
the user chose (1) product scan options only, with no research knobs, and
(2) one baseline mechanism for CLI and UI: run first, then save the run as the
baseline; the comparison happens automatically.

This replaces ADR 0050, removed in
this change. Summary of ADR 0050: `research/contrib_eval/` wrapped the OCR
benchmark for two OCR paths (`ocr/cloud-default`, `ocr/local-speed`) on a
grouped, seeded 80/20 development/test split; a manifest (suite + configuration
identity, product sources excluded) decided whether the latest committed
baseline was fresh; the role (baseline or candidate) was chosen before a run; a
candidate was refused when its inputs differed from the named baseline unless a
mismatch reason was recorded; `compare` wrote a Markdown/JSON comparison;
summaries and comparisons were committed under
`research/ocr_eval/reports/contrib/`. Rationale: a contribution is judged on a
fresh, matched baseline with failures, time, resources, cost and its added
complexity, and repeated contributions do not tune on the test images. Reason
for revision: it measured OCR only, its path names did not match the product's
options, and the role-before-run, `--against` and `--allow-mismatch` steps were
more than the workflow needs. The split itself is unchanged by this ADR; its
current form (algorithm v3, one dataset) is in [ADR 0053](0053-one-evaluation-dataset.md).

## Decision

- **Configurations are product scan options** (`vipi scan`): `local-speed`,
  `local-balanced`, `local-quality`, `cloud-google`, `cloud-openai`,
  `cloud-mistral`. Detector (`auto`) and threshold (80) stay at the product
  defaults (the `-jev` cloud configurations of
  [ADR 0057](0057-jev-detector-configurations.md) set the detector; the model
  registry part covers only used entries, [ADR 0060](0060-model-identity-per-used-entry.md)); evaluation has no threshold setting.
- **One run measures OCR and detection.** The benchmark worker calls
  `vipi.scanner.scan_image` per entry and records the OCR output and the
  verdict. Every split entry is scanned (450 development entries). OCR metrics
  use the entries with reference text; detection uses all entries: benign must
  be `not_flagged`, injection and jailbreak must be `flagged`. Unclear verdicts
  and failed scans count in the denominator as neither. Caller-context cases in
  the catalog are not run, as before. Reported: attack recall, benign
  false-positive rate, accuracy, unclear, no result, overall and per content
  and label.
- **Run, compare, save.** `run <configuration>` writes everything to
  `runs/evaluations/<run-id>/` (report, summary). If a baseline of the same
  configuration and split is saved, the run is compared with it automatically
  (`comparison.md`/`.json` in the run directory); differing inputs are marked
  "not the same inputs" with the changed fields instead of being refused.
  `save-baseline <run-id>` copies the summary to `research/baselines/`, which is
  committed. `status` reports `fresh`, `stale` or `none` for the latest saved
  baseline.
- **Workbench.** Three pages: *Scan an image* (upload, drop or paste; one
  settings line with the product default `local-quality` and threshold 80; a
  "Change settings" panel for run on local/cloud, text recognition and the
  threshold; result: verdict, score, recognized text, OCR passes), *Evaluate*
  (settings, development or test split with an explicit confirmation, the
  baseline state before starting, progress with stop and resume, headline
  metrics with deltas against the baseline, changed-image counts, results per
  content type, "Save as baseline", report and comparison downloads) and
  *Label*. Scans and evaluations share one lock, so one model workload runs at
  a time. Stopping terminates the benchmark worker; the image in progress is
  scanned again on resume. Removed from the workbench: the model comparison,
  OCR profiles, workers, hardware backends, multiple classifiers, the threshold
  editor, the dataset collection toggle, mixed selections, selection batches
  and the two old catalog readers.
- **Unchanged from ADR 0050:** manifest identity and freshness rules,
  implementation identity (commit, dirty tree), psutil resource sampling,
  resumable runs, the test split behind an explicit confirmation, the
  comparison's per-entry changes and value-versus-complexity section, which
  does not accept or reject a change.
- **Removed:** `manifest` and `compare` commands, `--role`, `--against`,
  `--allow-mismatch`, the benchmark report's `--cloud-directory` pairing and
  confidence-split selections (only used by a removed experiment).

## Alternatives and consequences

- *Keep research options (models, profiles, workers, classifiers) behind an
  advanced panel.* More reach for experiments, but two vocabularies and more
  room for ambiguity. Not selected by the user.
- *Separate local workbench baselines next to the CLI's committed ones.* Not
  selected: two mechanisms would disagree.
- *Refuse comparisons with differing inputs.* Safer against misreading, but a
  long run would end without a report. The comparison is written and labeled
  instead.

Consequences: a baseline saved on another machine has no local per-entry
report; the comparison then shows aggregates only and says so. Comparisons of
runs with different inputs cover only shared entries. Detection thresholds are
fixed at the product default, so threshold calibration needs its own work.
Cloud configurations incur provider charges for OCR, decisions and detection.

## Validation boundary

Offline tests cover the configurations, manifest and freshness states, run,
resume, automatic comparison, save-baseline, test-split protection, detection
scoring (unclear and failed scans) and comparison classification and
formatting, the workbench routes (scan, evaluation, stop/resume, baseline) and
benchmark cancellation, with fixture datasets and simulated scans. A dry run on
the real dataset plans 450 development entries. In the browser, the pages,
settings, test-split confirmation, a local run with stop and resume, and the
Label page were checked; local OCR itself failed on this branch because of the
rapidocr 3.10 regression fixed separately. No live run has been executed, so
quality, time, cost and resource figures are not yet observed.
