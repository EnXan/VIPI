# Product OCR benchmark protocol

This benchmark runs the production `OcrSession` over every entry of the pinned
dataset that has reference text (536 of 554; ADR 0053). The measured run below
used the earlier two catalogs: 1,000 OCR entries and 113 scanner-evaluation
entries. The requested comparison
is local **speed** (PP-OCRv6 Tiny + LiquidAI d1) against **cloud defaults**
(Google Cloud Vision Document Text Detection + OpenAI Decisions, GPT-6 Luna).
It measures OCR recovery, including visual decisions and image transformations.
It does not run the final injection detector or measure scanner recall.

## Measured run, 1–2 November 2026

The [results](../research/ocr_eval/reports/PRODUCT_OCR_1113_2026-11-02.md) and
[per-image JSON](../research/ocr_eval/reports/PRODUCT_OCR_1113_2026-11-02.json)
record both completed trials. Dataset: `EnXan/VIPI-evaluation` at
`2278db5db5dfe1ba8b930cc9b3888962c2672b35`. There are 31,140 reference words:
811 entries cover source-declared text, 189 target text only, and 113 primary
visible payloads. No reference has zero words. Host: Apple M2 (8 physical/logical
CPU cores), 16 GiB unified memory, macOS 27.0.1, Python 3.12. Local OCR used
RapidOCR 3.9.2 / ONNX Runtime 1.23.2 on CPU; d1 used Torch 2.11.0 / Transformers
5.14.1 on MPS/FP16. This observation does not certify a minimum hardware budget.

Local completed/scored 1,113 entries. Corrected cloud completed/scored 1,100;
13 failed: nine Google service-unavailable responses, three assessment refusals
and one HTTP 400 reporting a 41,943,040-byte request-payload limit. Failures are
not retried or treated as OCR successes. There are no unscored completions or
region-group conflicts. Full-reference passes therefore equal the tolerant
100% image counts: 567 local and 634 cloud. Literal exact completion is 440
local and 408 cloud; exact-word coverage and exact whole-image completion are
different metrics.

The README credits failures as zero across all 31,140 words / 1,113 entries:
local tolerant coverage is 69.46%, cloud 85.38%. The full generated tables also
show scored-only word coverage (cloud 86.38%) and mean-image coverage (84.48%).
Keep these denominators explicit when comparing figures.

The first cloud trial completed 397 entries and failed 716: 712 hosted
comparisons assumed a layout `box` on native Google word regions that instead
provide `polygon`; three assessments were refused and one Google request was
unavailable. The fix derives a missing box from the raster polygon while
preserving existing boxes. Local inference and its comparison expressions are
unchanged, verified by AST comparison and regression tests. A fresh full cloud
trial followed; no old/new cloud outputs were mixed. Both executed source
snapshots are retained and the JSON records separate configuration source hashes.

Original cloud trial overhead, excluded from corrected metrics: 3,200.29s wall
time (53m 20s), with $4.22896 estimated from retained usage; four requests lack
usage, so its full fee remains unknown. Corrected cloud retained 4,297 successful
Google units and 8,154,628 Decisions input tokens, including 2,473 cache reads
and 7,350,403 cache writes. Its known-usage estimate is $7.44450; 13 requests lack
usage. The inference artifacts retain the earlier flat-token estimates; reporting
reprices their unchanged usage with the verified cache rates below and records
the postprocessing source hashes. These two cloud trials consumed a combined
$11.67346 in known-usage list-rate estimates, with 17 requests unpriced; actual
account charges remain unknown. The [independent usage audit](../research/ocr_eval/reports/PRODUCT_OCR_1113_2026-11-02.usage.json)
reconciles those units/tokens and both trial manifests. The largest retained
Decisions request used 49,461 input tokens.

## Run and reproduce

Use the [development setup](development.md), download the dataset, and prepare
local speed models and cloud credentials as described in the [CLI guide](cli.md).
From the repository root:

```bash
uv run python -m research.download
uv run vipi setup --modus local --ocr-mode speed
uv run python -m research.ocr_eval.benchmark runs/benchmarks/full --configuration local-speed cloud-google
uv run python -m research.ocr_eval.benchmark_report runs/benchmarks/full --output runs/benchmarks/full/report.json
```

For baseline comparisons use the [evaluation runs](../research/evaluate/README.md),
which call this benchmark on one split. The runner requires one or more
`--configuration` names (product scan options: `local-speed`,
`local-balanced`, `local-quality`, `cloud-google`, `cloud-openai`,
`cloud-mistral`) and runs them in the given order. Each entry is scanned with
`vipi.scanner.scan_image`, so a run records OCR text and the detection verdict.
Repeating the same command resumes entries without a terminal record; completed
and failed attempts are retained. Use a new directory for a fresh trial. A worker
crash counts the image that was running as failed; unstarted images continue in
a new process. There are no benchmark-level retries of completed/failed images.
The production providers retain their own retry behavior.
Resume only after the earlier invocation has stopped. Interrupted checkpoints
are preserved; an unfinished image is marked failed with unknown duration.
An interrupted invocation's recorded wall time is a checkpoint lower bound,
excluding unmeasured work after its final checkpoint and time between invocations.

Image order follows the dataset catalog. Inference is
sequential, with one OCR worker. Local processes recycle after four images,
following the MPS memory growth observed in the previous 113-image run. This is
a process-lifetime workaround, not a dataset limit. Model loading is lazy, so
the first review in a fresh process includes its model-loading time. Network
connections are blocked in local workers. Cloud uses one persistent process.

The manifest freezes dataset revision, image and reference hashes, source and
lockfile hashes, host, Python and runtime versions. Each attempt records its
timestamps, duration, result hash and artifact directory. Artifacts retain OCR
variants, decision requests/responses and usage. Keep the run directory and
referenced artifacts together; they are local evidence and ignored by Git.
The report command runs no inference. It verifies the selected images/references,
evaluation sources and completed-output hashes before scoring. Its JSON contains
per-image counts and aggregates; the Markdown sibling renders those aggregates.
OCR rates use the entries with reference text; detection uses every entry
(benign must not be flagged, injection and jailbreak must be).

### Scoped cloud confidence trial

The [100-entry selection](../research/ocr_eval/experiments/DECISION_CONFIDENCE_HARD_100.json)
is a reproducible, category-stratified sample from the union of entries that
failed, were unscored or did not pass full reference in either configuration
of the previous evaluation. It contains 81 TextOCR and 19 other entries, with
100 distinct image hashes. The fixed image-hash split has 79 calibration and 21
held-out evaluation entries. This is a first cloud-only experiment; it does not
rerun local inference or represent every difficult entry.

The selection uses keys of the former two-catalog dataset and a confidence
split that the benchmark no longer reads. It is kept as evidence of the trial;
reproduce it from the Git history before 2026-11-09 with the older dataset
revision.

The confidence-validation script (`research/ocr_eval/experiments/decision_confidence.py`)
was removed on 2026-11-09 after the trial; it remains in the Git history.

The confidence report groups native values by provider, model, question and
split. It evaluates the initial OCR completeness choice against both 80%
tolerant word coverage and the full-reference pass; it checks comparisons
against reference-scored tolerant word gain. Reviewability and repair choices
have no direct reference label here and are descriptive. References are read
only after inference. No confidence cutoff is fitted or applied. The results
are a small development-set diagnosis, not evidence of a production-safe policy
or general model calibration. See the [scoped OCR results](../research/ocr_eval/reports/DECISION_CLOUD_HARD_100_2026-11-07.md)
and [confidence validation](../research/ocr_eval/reports/DECISION_CONFIDENCE_HARD_100_2026-11-07.md).

## Metrics and denominators

Use the existing [evaluation v4 rules](../research/ocr_eval/README.md), without
giving reference text to OCR or visual decision providers. Score only the final
selected output, with its selected observation geometry.

- **Word coverage:** tolerant matched reference words divided by all reference
  words in scored entries. This is word-weighted; long references weigh more.
- **Exact word coverage:** the same ratio using literal, case-sensitive words
  with attached symbols. This is stricter than tolerant coverage.
- **Mean image coverage:** arithmetic mean of individual scored-image coverage.
- **≥80% images / 100% images:** entries reaching those tolerant-coverage
  thresholds divided by every planned entry in the group. Use integer word
  counts to test thresholds before rounding displayed percentages.
- **Full-reference pass:** the existing evaluation-v4 pass, which also requires
  independent reference-region integrity. Thus 100% word coverage can coexist
  with a failed full-reference pass. Exact completion and exact reference passes
  are retained separately in JSON.

Failures and unscored completions remain in image-success denominators and are
reported explicitly. A nonempty transcription without locations is unscored
when the reference requires word geometry, matching the workbench policy.
Coverage averages use scored entries; JSON additionally reports conservative
coverage lower bounds over all planned reference words/images, assigning zero
credit to missing scores. Zero-word references never count as threshold successes.

Category rows partition the catalogs. Suite, scope, technique, obfuscation and
Anamorpher-family subsets overlap and must not be added together. Existing labels
are preserved. Anamorpher is identified by the catalog's `anamorpher_` filenames,
as documented in the [scanner catalog guide](../research/detection_eval/README.md#anamorpher-samples).
Its three samples do not establish a broad Anamorpher success rate.

## Time, fees and claim boundaries

Per-image duration measures the call to production OCR, including lazy loading,
recovery and artifact persistence. Tables sum those times by category and show
the average per attempted image. Invocation wall time additionally includes
worker startup/teardown; its overall average uses all planned images. Manifest
creation/downloads and offline scoring are outside inference time. JSON also
retains the pipeline's own duration. These are single-trial observations, not
warm steady-state latency or a distribution across repeated trials.

USD values are **API-fee estimates from retained usage**, not invoices:
[Google Document Text Detection](https://cloud.google.com/vision/pricing) at
$1.50/1,000 units and [OpenAI Decisions](https://developers.openai.com/api/docs/guides/decisions)
at standard global rates checked on 2026-11-02: $0.10/million uncached input
tokens, $0.01/million cache reads and $0.125/million default 30-minute cache writes.
Reads/writes are subsets of input tokens and are priced once; output is free.
See [pricing](https://developers.openai.com/api/docs/pricing) and
[cache accounting](https://developers.openai.com/api/docs/guides/prompt-caching).
Google free quota, volume/account discounts and taxes are unknown, as are
regional/long-context premiums and potentially charged requests without retained
usage. The measured request sizes are recorded in the usage audit. Saved-response
HTTP attempts are retained and retries flagged. Unknown costs stay unknown;
the known-usage subtotal includes successful partial work before failures. Local
API fees are zero; electricity, hardware, depreciation and operator time are
unmeasured. API-fee figures must not be described as total operating cost.

References cover annotated source text or target payloads, not necessarily every
visible word. Tolerant coverage does not prove exact transcription, localization,
semantic equivalence or injection detection. These catalogs were used during
development and contain related examples; they are not an independent holdout.
Preserve all 1,113 requested catalog entries, disclosing the 1,106 distinct image
hashes rather than implying 1,113 independent images. Cite the dataset revision,
configuration, sample counts, metric and hardware with any published claim.
Cloud service aliases are not immutable model snapshots; future live decisions
and outputs can differ. Timing comes from the retained executed sources; the
post-run pricing correction changes fee bookkeeping without changing inference.
Windows/Linux performance and other providers/modes remain unmeasured.
