# Contribution evaluation

Tools that make a contribution's evaluation comparable: one frozen split of
both pinned catalogs and a freshness check for the latest committed baseline.
Matched baseline/candidate runs and comparison reports are not implemented yet.

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
