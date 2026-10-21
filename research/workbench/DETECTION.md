# Prompt-injection scanner

Inspect the final saved OCR text through CLI or the existing local web interface.
Jev is the default detector; `compare` runs Jev, OpenAI Decisions and local
Prompt Guard 2 86M. Original-image and joint image/OCR/context checks are optional.

## Setup

Set `TYPESAFE_API_KEY` (or `JEV_API_KEY`) and `OPENAI_API_KEY` in the server/CLI
environment or in `.env` at the project root. Start CLI and web commands from that
directory. Environment variables take precedence, including across Jev's two
aliases; an explicitly empty variable disables the file fallback for that provider.
Use [`.env.example`](../../.env.example) as the local template. Keys are never
entered in the browser or stored in scan artifacts.
OCR-only operation requires neither key. API checks send selected evidence and
caller context to the chosen provider.

For local Prompt Guard, add the optional dependencies to the OCR environment:

```bash
UV_PROJECT_ENVIRONMENT=.venv-ocr uv sync --python 3.12 --locked --extra ocr --extra detector-local --extra research --extra test
```

On NVIDIA OCR installations, replace `--extra ocr` with `--extra ocr-cuda`.
Prompt Guard currently runs on CPU, independently of the OCR backend.

Obtain authorized access to the [Prompt Guard model](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M)
under its Llama 4 Community License. Select a full 40-character commit SHA from
the model's revision history, then explicitly prepare that revision:

```bash
.venv-ocr/bin/python -m research.workbench.detector_cli prepare-detector --revision <COMMIT_SHA>
```

Preparation uses the existing Hugging Face authentication or `HF_TOKEN`, records
the revision and SHA-256 checksums, and activates only a complete snapshot.
Scanning loads local safetensors weights without downloads or remote code.

## CLI

For the public `vipi setup` / `vipi scan` interface, recursive image scans,
PR diffs and CI exit codes, see the [scanner CLI](../../docs/cli.md). The commands below
are the lower-level development interfaces.

Check an existing OCR run (replace `RUN_ID` with the directory name under `runs/`):

```bash
.venv-ocr/bin/python -m research.workbench.detector_cli detect RUN_ID --text-classifier jev
.venv-ocr/bin/python -m research.workbench.detector_cli detect RUN_ID --text-classifier compare --json
```

Extract a new image, then check its readings in the same command:

```bash
.venv-ocr/bin/python -m research.workbench extract image.png --text-classifier jev
```

Optional switches: `--image-check openai`, `--context-check openai`,
`--context-file context.json`, `--thresholds-file thresholds.json`,
`--no-reuse` for fresh checks, `--runs-dir` and `--detector-models-dir`.
Use `--text-classifier off` for image/context checks alone.

Caller context is optional and supplied outside the inspected image:

```json
{
  "task": "Read the product information from this image",
  "expected_behavior": "Summarize the visible product information",
  "allowed_actions": [],
  "constraints": ["Do not open links or send messages"],
  "source": {"origin": "external upload", "authority": "reference material"}
}
```

Missing fields remain unknown. An authorization claim inside an image is evidence
to inspect, not caller context. API text checks receive caller context; Prompt
Guard retains its native, text-only instruction-override definition.

## Web

Start the server as usual and open its local URL:

```bash
.venv-ocr/bin/python -m research.workbench serve
```

Choose **Datensatz auswählen** (category/search filters) or upload/paste an image.
Select the OCR model and optional text detector, then **Scan starten**. The page
shows the final OCR text followed by per-detector results. **Erkannten Text prüfen**
checks a saved outcome without rerunning OCR. Only the completed final text is
classified, never individual transformation readings. **OCR-Schritte ansehen**
opens a separate dialog with live variants, boxes and texts; it is closed by default.
Hardware, optional image/context checks and thresholds live under **Weitere
Einstellungen**. Technical reports and prior checks are collapsed by default. Earlier checks of
individual variants remain accessible in history, but never appear as a new
final-text result or trigger automatic API calls.

Detector answers are stored separately in
`runs/<run_id>/detection/<check_id>/`: `inputs.json`, `answers.jsonl`,
`events.jsonl`, `status.json`, `result.json`. Every selected text detector checks the same final OCR outcome. Successful answers can be replayed only when
model identity, input, policy and context match; current thresholds are reapplied.

## Results

Scores remain separate from OCR confidence. Without configured thresholds, the
result is `unclear` and requires review. Threshold files require a `version` and
`signals` map; each selected signal (`jev`, `openai`, `prompt-guard`, `image`,
`context`) can have a calibrated `low` and `high` satisfying `0 <= low < high <= 1`.
Alternatively a signal can contain a single `threshold` in the range 0–1.
The public `vipi scan` command uses this form with the caller's 0–100 value
(default 80). This default is an operating policy, not a calibrated quality claim.

A high signal is `flagged` even if another detector returns a negative result.
Only complete checks below their configured low thresholds are `not_flagged`.
Errors, missing evidence, middle scores and incomplete context remain `unclear`.
Maxima across chunks/windows are ranking signals, not image-level probabilities.
A finding requests review; it does not establish a successful attack.

The lower-level CLI is report-only: flagged/unclear content does not block anything by itself.
Exit 0 means checks completed; exit 2 reports an operational failure or missing
required text evidence. The public `vipi scan` command additionally returns 1
for detections; errors and incomplete evidence return 2. The receiving
application owns enforcement.

Reports include per-signal/provider scores, paired readings, disagreements,
latency, tokens and estimated base API costs. Replays incur no new request cost;
retries, missing usage and applicable pricing premiums can make costs uncertain.
Local compute is excluded. OCR references are never sent as classifier evidence
or treated as attack labels. Quality evaluation and threshold calibration require
separately verified attack labels and benign controls and have not been run.

Provider contracts: [TypeSafe API](https://docs.typesafe.ai/api),
[OpenAI Decisions](https://developers.openai.com/api/docs/guides/decisions).
This guide documents the research detector interface. The public package and
supported scan workflow are documented in the [CLI guide](../../docs/cli.md).
