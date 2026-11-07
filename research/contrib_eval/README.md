# Contribution evaluation

Tools that make a contribution's evaluation comparable: one frozen split of
both pinned catalogs, a freshness check for the latest committed baseline, and
scoped baseline/candidate runs. Comparison reports are not implemented yet.

## Splits

[`../splits.json`](../splits.json) assigns all 1,113 entries of the OCR and
detection catalogs to two disjoint splits, 80% `development` and 20%
`test`. Entries sharing content stay together: OCR entries with the same
source `content_group_id`, detection images with the same payload or the same
filename family (stem without trailing obfuscation tokens such as
`_low-contrast` or `_none`), and byte-identical images, including the images
present in both catalogs. Groups are ranked by seeded SHA-256 per stratum (OCR
category, detection label category) and the test split is filled up to 20% of
each stratum.

- Use `development` for every baseline/candidate comparison.
- Use `test` only once, to confirm a candidate before a default, profile or
  threshold changes. Do not iterate or tune on it.

Regenerate after the pinned dataset revision changes, and verify that the
committed file still matches the downloaded catalogs:

```bash
uv run python -m research.contrib_eval split
uv run python -m research.contrib_eval split --check
```

Regenerating may move entries between splits. Test entries that were
already used for development work would then no longer be unseen; review
the diff before committing a regenerated split.

## Baseline freshness

```bash
uv run python -m research.contrib_eval status ocr/cloud-default
uv run python -m research.contrib_eval manifest ocr/cloud-default --split development
```

The manifest identifies the suite (dataset revision, catalog hashes, split
file, selected cases with image/reference hashes, metric sources) and the
configuration (benchmark configuration, declared model identity). Product
source hashes are excluded because a candidate differs from its baseline by
design. `status` compares the manifest with the latest committed baseline
summary under `research/ocr_eval/reports/contrib/` and reports `fresh`,
`stale` with the changed fields, or `none`. It exits non-zero unless fresh.

## Baseline and candidate runs

`run` performs live inference for one path on one split and may incur provider
charges (a development-split `ocr/cloud-default` run covers 892 entries). Check
the request with `--dry-run` first.

```bash
uv run python -m research.contrib_eval run ocr/cloud-default --role baseline --dry-run
uv run python -m research.contrib_eval run ocr/cloud-default --role baseline
uv run python -m research.contrib_eval run ocr/cloud-default --role candidate --against <baseline-run-id>
```

- Run the baseline before changing code. The run records the commit, whether
  the working tree was dirty and hashes of uncommitted/untracked changes.
- A candidate is refused when its manifest differs from the baseline's. Refresh
  the baseline instead, or pass `--allow-mismatch "<reason>"` to record an
  explicitly non-matched run.
- The test split requires `--confirm-test-split`; the summary marks such runs.
- The run reuses the [OCR benchmark](../../docs/ocr-benchmark.md): the split's
  keys become its selection file, and resuming with `--run-id <id>` continues
  unfinished entries. Completed and failed attempts are kept as recorded.
- Local artifacts go to `runs/contrib/<run-id>/` (ignored by Git): benchmark
  outputs, `report.json` with per-case scores and `operations.json`.
- When inference is complete, the command writes
  `research/ocr_eval/reports/contrib/<run-id>.json`. Commit that summary: it
  holds the manifest, implementation identity, host, quality metrics, failures,
  time, cost and resource figures.

Resource figures come from `psutil` sampling of the evaluation process and its
workers every 0.5 s. CPU time is a lower bound because short-lived workers can
exit between samples. GPU/MPS memory is allocated inside worker processes and is
recorded as unavailable.
