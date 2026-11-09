# Evaluation

Evaluate one product scan configuration on a frozen split of the dataset and
compare it with the saved baseline. The workflow for changes is in
[CONTRIBUTING.md](../../CONTRIBUTING.md#evaluating-improvements); the design is
recorded in [ADR 0054](../../adr-code/0054-evaluation-runs-and-baseline.md).

## Configurations

A configuration is a set of `vipi scan` options. Detector and threshold stay
at the product defaults (`auto`, 80).

| Configuration | Scan options |
| --- | --- |
| `local-speed`, `local-balanced`, `local-quality` | `--modus local --ocr-mode <mode>` |
| `cloud-google`, `cloud-openai`, `cloud-mistral` | `--modus cloud --ocr-provider <provider>` |

Local configurations run offline (network blocked) and need the models from
`vipi setup`. Cloud configurations need the provider API keys and incur
charges for OCR, decisions and detection.

## Splits

[`../splits.json`](../splits.json) assigns all 554 dataset entries to two
disjoint splits: 450 `development` and 104 `test`. Entries sharing content
stay together: byte-identical images, the same source `content_group_id`, the
same visible text, texts sharing at least 80% of their words (template
variants that differ in a slot word), the same scenario family of former
detection fixtures (filename stem without obfuscation suffixes such as
`_low-contrast` or `_none`) and listed matched benign controls
(`CONTROL_GROUPS` in `splits.py`). Groups are ranked by seeded SHA-256 per
label × content stratum and the test split is filled up to 20% of each
stratum.

- Use `development` for every evaluation.
- Use `test` only once, to confirm a change before a default changes. Do not
  iterate or tune on it.

Regenerate after the pinned dataset revision changes, and verify that the
committed file still matches the downloaded dataset:

```bash
uv run python -m research.evaluate split
uv run python -m research.evaluate split --check
```

Regenerating may move entries between splits. Test entries that were already
used for development work would then no longer be unseen; review the diff
before committing a regenerated split.

## Run, compare, save

```bash
uv run python -m research.evaluate status local-speed
uv run python -m research.evaluate run local-speed --dry-run
uv run python -m research.evaluate run local-speed
uv run python -m research.evaluate save-baseline <run-id>
```

- `status` reports whether the latest saved baseline of the configuration
  still matches this checkout: `fresh`, `stale` with the changed fields, or
  `none`. It exits non-zero unless fresh. Identity covers the dataset revision,
  catalog, split file, selected entries with image/reference hashes, metric
  sources, scan options and declared model identity; product source code is
  excluded because a change differs from its baseline by design.
- `run` scans every entry of the split with the configuration (OCR and
  detection) and writes `runs/evaluations/<run-id>/` (ignored by Git):
  benchmark outputs, `report.json`/`report.md`, `summary.json` and
  `operations.json`. It records the commit, whether the working tree was dirty
  and hashes of uncommitted/untracked changes. Resume an interrupted run with
  `--run-id <id>`; completed and failed attempts are kept. The test split
  requires `--confirm-test-split`.
- If a baseline of the same configuration and split is saved, `run` compares
  with it and writes `comparison.md`/`.json` into the run directory. Runs with
  different inputs are labeled "not the same inputs" with the changed fields.
- `save-baseline` copies a complete run's summary to
  `research/baselines/<run-id>.json`. Commit that file. Save the baseline on
  unmodified code, before changing anything.

## Metrics

- **OCR** (entries with reference text): tolerant and exact word coverage,
  image pass rates, failures; see the [OCR evaluation guide](../ocr_eval/README.md).
- **Detection** (all entries): benign entries must be `not_flagged`, injection
  and jailbreak entries `flagged`. Reported: attacks flagged (recall), benign
  flagged (false-positive rate), accuracy, unclear verdicts and scans without
  result. Every entry is in the denominator. Caller-context cases are not run.
- **Cost and resources**: per-image time, estimated API cost, run wall time,
  CPU time and peak memory from `psutil` sampling every 0.5 s. CPU time is a
  lower bound because short-lived workers can exit between samples. GPU/MPS
  memory is allocated inside worker processes and is recorded as unavailable.

The comparison lists every entry whose scan newly failed or recovered, whose
OCR coverage regressed or improved, and whose verdict became wrong or right,
plus the files changed between the two runs' commits. It does not decide
whether a change is accepted. Without the baseline's local report (a baseline
saved on another machine) it compares aggregates only.
