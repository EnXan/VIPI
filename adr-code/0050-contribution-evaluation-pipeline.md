# ADR 0050: Matched contribution evaluation on a grouped development/test split

Status: accepted for the OCR paths; implemented on 2026-11-07.

## Context and sources

Priority 1 in the roadmap requires that a contribution claiming an OCR,
detection or end-to-end improvement be judged on a fresh, matched baseline and
reported with failures, time, resources, cost and its added complexity, not by
a primary quality score alone. The existing [product OCR benchmark](0046-product-ocr-benchmark.md)
already freezes selections, retains attempts and scores outputs, but always
covered every entry and had no split, freshness check or baseline/candidate
pairing. An untracked `research/detection_eval/splits.json` from an abandoned
implementation recorded a splitter that was not in the repository and could
not be reproduced; the user approved deleting it.

Decisions taken with the user: keep a development/test split so repeated
contributions do not tune to the same images; 80/20 over both pinned catalogs
(1,113 entries); name the splits `development` and `test`; pilot the workflow on
`ocr/cloud-default`; keep full run artifacts local and commit small summaries;
measure resources with `psutil`.

## Decision

`research/contrib_eval/` wraps existing research tooling instead of replacing
it; product code is unchanged.

- **Split.** One deterministic splitter writes `research/splits.json`. Entries
  are grouped by OCR source `content_group_id`, by identical detection payload,
  by detection filename family (stem without trailing obfuscation tokens) and
  by byte-identical images, including the seven images present in both
  catalogs. Groups are ranked per stratum (OCR category, detection label
  category) by seeded SHA-256 and the lowest-ranked groups fill 20% of each
  stratum. `development` serves every comparison; `test` is used once to
  confirm a candidate before a default, profile or threshold changes and
  requires `--confirm-test-split`.
- **Identity and freshness.** A manifest has a `suite` part (dataset revision,
  catalog hashes, split hash, selected keys with image/reference hashes, metric
  source hashes) and a `configuration` part (benchmark configuration, declared
  model constants and registries). Product source hashes are excluded because a
  candidate differs from its baseline by design. `status` compares the current
  manifest with the latest committed baseline summary.
- **Runs.** `run` freezes the split's keys as a benchmark selection file and
  runs only the path's configuration, then scores with the benchmark report.
  A candidate is refused when its manifest differs from the named baseline
  unless a mismatch reason is recorded, which marks it as non-matched. Runs
  record commit and dirty-tree hashes, host and package versions, and
  psutil-sampled wall time, CPU time and peak RSS.
- **Comparison.** `compare` writes Markdown and JSON with matched status,
  aggregate and per-category deltas, newly failed, recovered, regressed and
  improved cases, and the files changed between clean commits. Value versus
  complexity is left to the reviewer; the report does not accept a change.
- **Storage.** Per-case artifacts stay in ignored `runs/contrib/<run-id>/`.
  Summaries and comparisons are committed under
  `research/ocr_eval/reports/contrib/`.

## Alternatives and consequences

- *Evaluate on all 1,113 entries without a split.* Simpler and statistically
  stronger per comparison, but repeated contributions would tune to the same
  images. Not selected.
- *Separate splits per catalog.* The seven shared images could land in the
  development split of one catalog and the test split of the other. Not
  selected.
- *Include product source hashes in freshness.* Every candidate would appear
  stale against its own baseline. Implementation identity is recorded per run
  instead.
- *Standard-library resource measurement only.* Avoids a dependency, but child
  worker processes are harder to attribute. The user selected `psutil`.

Consequences: a split regeneration after catalog changes can move entries
between splits and must be reviewed before committing; a stable extension mode
is open (see the roadmap's split-composition review). Detection grouping relies
on filename conventions. Per-case comparison needs both local run directories.
CPU time is a sampling lower bound, and GPU/MPS memory, allocated in worker
processes, is reported as unavailable. A development-split cloud run covers 892
entries and incurs provider charges. Detector-only and end-to-end paths are not
implemented yet.

## Validation boundary

Offline tests cover grouping, determinism, stratification, split checks,
manifest/freshness states, run requests, resume, mismatch handling, test-split
protection, implementation identity, resource sampling and comparison
classification and formatting, using fixture catalogs and simulated benchmark
runs. The real catalogs produce 892 development and 221 test entries with no
group across both splits, and the benchmark accepts the generated 892-key
selection. No live baseline or candidate run has been executed, so the
end-to-end workflow and its cost and resource figures are not yet observed. The
split composition itself awaits a joint review.
