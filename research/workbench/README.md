# Research workbench

The local Flask workbench compares OCR models, browses the pinned evaluation
catalogs, and inspects OCR/detection runs. It imports `vipi`; it is not included
in the product wheel.

## Start

Use the [development environment](../../docs/development.md), then run from the
repository root:

```bash
uv run python -m research.download
uv run python -m research.workbench prepare-models --model ppocr-v6-tiny
uv run python -m research.workbench serve
```

Open [localhost:8000](http://127.0.0.1:8000). The
[research CLI reference](../../docs/research-cli.md) documents every command and
option, directory override, optional model environment and exit code.

## Scan and review

Use **Input**, **Options** and **Review** to choose uploaded/pasted images or
dataset selections, OCR models/profile/backend/workers, and optional detectors.
The interface initially selects PP-OCRv6 Tiny and the native original-only
baseline. The research CLI defaults to Medium. Active comparison models and
functional readiness checks are listed in [the baseline protocol](../ocr_eval/BASELINE.md).

| Profile | Behavior |
| --- | --- |
| `baseline` | One original-image call using the model's native processing; default control |
| `transforms` | Previous fixed-transform comparison profile, up to 15 selected full-image passes with size-dependent 2× eligibility |
| `adaptive-jev` | Shared product recovery with OpenAI Decisions review; the historical name does not select Jev |

The adaptive research profile needs `OPENAI_API_KEY` when visual review is
triggered, even with local OCR. Product `vipi scan --modus local` instead uses
its selected local decision model. See [recovery stages and measured limits](../../docs/ocr-recovery.md).

Leave text classifiers and image/context checks off for OCR only. To run
detection, select Jev, OpenAI Decisions and/or Prompt Guard, provide a threshold
set version and a threshold for every selected signal. Scores at the threshold
are flagged. The [detector guide](DETECTION.md) owns context, credentials,
threshold formats and replay behavior.

**Scan** shows single-image progress/results. **Evaluation** shows selection
reports. **View OCR steps** opens transformed images, native boxes, variants and
worker state. Opening saved results restores their data without starting model
calls. Text-only OCR backends can be unscored for spatial references; timing,
text and usage remain available.

## Dataset batches

Browse `ocr_evaluation` and/or `detection_evaluation`, filter by category or text,
and apply the selection. Models run sequentially: each finishes all selected
images before the next loads. Baseline/adaptive use one worker; transforms
support 1–8 (default 4), each with its own OCR instance. CPU is the default OCR
backend; compatible CoreML is experimental and CUDA requires its own runtime.

The [OCR evaluation guide](../ocr_eval/README.md) defines reference matching,
exact-word fidelity and denominators. The
[detection evaluation guide](../detection_eval/README.md) defines case labels
and metrics. Labeled detection cases run without caller context; catalog context
is ground truth only. References never guide OCR or candidate selection.

**Stop scan** cancels the active upload/detector work. **Stop batch** also skips
remaining images. In-flight native/provider calls finish before cancellation;
owned heavy model workers can be terminated. Completed steps/answers remain
inspectable. Cancelled cases are separate from technical failures and excluded
from percentages. Keep the server and computer running for long batches;
restarting marks unfinished queues interrupted rather than resuming them.

## Saved artifacts

Default output is the ignored repository `runs/` directory; `--runs-dir`
overrides it. Browser downloads are optional because reports are saved as runs
progress.

| Artifact | Path |
| --- | --- |
| OCR text / JSON | `runs/<run-id>/result.txt`, `result.json` |
| Transformed images and raw observations | `runs/<run-id>/images/`, `steps.jsonl` |
| Progress and status | `runs/<run-id>/events.jsonl`, `status.json` |
| Detector inputs, answers and result | `runs/<run-id>/detection/<check-id>/` |
| Selection report | `runs/batches/<batch-id>/report.json` |
| Functional model checks | `runs/reports/ocr-round0/<id>/` |

Failed/cancelled runs retain partial artifacts. Adaptive runs also retain
attempts and decisions. Reports preserve actual models, profiles, hashes,
evaluation policy, timings and usage. Cost estimates are not invoices; unknown
fees remain unknown and local compute is excluded. Historical runs retain their
original schema/results rather than being silently rescored.
