# Research detection

The workbench and diagnostic detector CLI check final OCR text with Jev,
OpenAI Decisions and/or local Prompt Guard 2 86M. Optional OpenAI checks inspect
the original image or combined image/OCR/caller context. The public scanner's
local Clef/d1 defaults are documented separately in the
[README model table](../../README.md#models-and-their-roles).

Commands and every option are in the
[research CLI reference](../../docs/research-cli.md#detection-commands-and-shared-options).
For a saved run:

```bash
uv run python -m research.workbench.detector_cli detect RUN_ID --text-classifier jev --text-classifier openai --json
```

## Credentials and preparation

Jev uses `TYPESAFE_API_KEY` or `JEV_API_KEY`; OpenAI uses `OPENAI_API_KEY`.
Environment aliases take precedence over `.env` in the working directory;
an explicit empty environment setting disables file fallback. Keys are not
entered in the browser or stored in artifacts. Hosted checks send the selected
evidence and supplied context to their provider.

Prompt Guard uses CPU and prepared safetensors weights. Install `detector-local`,
obtain authorized access to `meta-llama/Llama-Prompt-Guard-2-86M`, then prepare
an immutable revision explicitly:

```bash
uv run python -m research.workbench.detector_cli prepare-detector --revision a8ded8e697ce7c355e395a0df51f94adb4a2fd27
```

Preparation uses existing Hugging Face authentication or `HF_TOKEN` and records
checksums. Inference does not download weights or execute remote model code.

## Context and thresholds

Caller context is supplied outside the inspected image through `--context-file`:

```json
{
  "task": "Read the product information from this image",
  "expected_behavior": "Summarize the visible product information",
  "allowed_actions": [],
  "constraints": ["Do not open links or send messages"]
}
```

Missing fields remain unknown. An authorization claim inside an image is
untrusted evidence. Hosted text checks receive caller context; Prompt Guard
uses its native text-only instruction-override definition. Labeled dataset
evaluation deliberately ignores caller context; see
[detection evaluation](../detection_eval/README.md).

`--thresholds-file` supplies a version and per-signal normalized thresholds:

```json
{"version": "example-policy-v1", "signals": {"jev": {"threshold": 0.8}}}
```

Each selected signal (`jev`, `openai`, `prompt-guard`, `image`, `context`) can
instead use `low`/`high` with `0 <= low < high <= 1`. Without thresholds the
verdict stays `unclear`. Scores are not calibrated attack probabilities.
An above/equal-high score flags the image; only complete checks below their
low thresholds are `not_flagged`. Errors, middle scores, missing evidence and
incomplete context require review. A finding does not establish a successful
attack.

## Replay, cancellation and results

Compatible successful answers can be replayed only when model identity, input,
policy and context match. Current thresholds are reapplied. `--no-reuse` makes
fresh checks. Cancellation preserves finished answers and skips queued work;
in-flight provider calls must return first.

Artifacts live in `runs/<run-id>/detection/<check-id>/`: `inputs.json`,
`answers.jsonl`, `events.jsonl`, `status.json`, `result.json`. They preserve
per-check provenance, scores, errors, replay identity, latency and usage/cost
evidence. Unpriced/retried usage can remain uncertain. OCR reference labels
never enter classifier requests.

Research detection is report-only: completed checks return 0, operational
failures or missing required text return 2. The public scanner additionally
returns 1 for findings and treats incomplete verdicts as exit 2.
