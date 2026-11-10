# Research workbench

A local Flask app with three pages: scan one image, evaluate a scan
configuration against the saved baseline, and contribute to the dataset. It imports
`vipi`; it is not included in the product wheel.

## Start

Use the [development environment](../../docs/development.md), then run from the
repository root:

```bash
uv run python -m research.download
uv run vipi setup
uv run python -m research.workbench serve
```

Open [localhost:8000](http://127.0.0.1:8000). `vipi setup` prepares the local
models; cloud settings need the provider API keys in the environment or
`.env` instead (see the [CLI guide](../../docs/cli.md)).

## Settings

Scan and Evaluate use the options of `vipi scan` and nothing else:

- **Run on**: this computer (free, needs the local models) or the cloud (paid
  API calls).
- **Text recognition**: Speed, Balanced or Quality locally; Google Cloud
  Vision, OpenAI or Mistral in the cloud.
- **Injection detector**: locally d1 for Speed and Balanced, and Clef or
  Clef-Flash for Quality (locally the model also reviews OCR); in the cloud
  OpenAI Luna (the product default) or Jev.
- **Threshold** (Scan only): flag at a detector score of at least this value,
  default 80.

The default is the product default: local, Quality, threshold 80.

## Scan an image

Choose, drop or paste an image and press **Scan image**. The result shows the
verdict (prompt injection found, not found, or unclear), the detector score,
time and API cost, the recognized text and, under **OCR passes**, every image
variant the scanner read with its text.

## Evaluate

Choose the settings and the images:

- **Development split** (450 images): use for every comparison.
- **Test split** (104 images): only once, to confirm a change before a default
  changes. Starting it needs a confirmation.

**Reuse identical results** is on by default: for an identical image, an
earlier OCR result is reused when OCR settings and OCR code match, and its
detection as well when detector, settings, product code and packages also
match ([ADR 0058](../../adr-code/0058-reuse-ocr-across-runs.md)). Turn it off
to scan every image from scratch.

Before you start, a summary shows the **Baseline** (none, up to date or out of
date with the changed fields), the **Work** (how many images need OCR and
detection after reuse) and the **Cost** (free locally; otherwise which paid
calls remain).

A run goes through every image of the split, shows its progress and can be stopped and resumed. When it is complete,
the page shows OCR word coverage, fully read images, attacks flagged, benign
images flagged and detection accuracy, each with the change against the
baseline, the number of images whose result changed, and results per content
type. **Save as baseline** stores the run in `research/baselines/`; commit that
file. **Report** and **Comparison** download the Markdown reports.

The page runs the same steps as `python -m research.evaluate`; the
[evaluation guide](../evaluate/README.md) defines the metrics. Only one scan or
evaluation runs at a time. Keep the server and computer running for long runs;
after a restart, open the run and resume it.

## Dataset

The **Dataset** tab edits `research/dataset/` in three steps:

1. **Add images**: choose or drop images and give label, content type, source
   name, license and provenance. Each new image gets an unreviewed entry;
   images already in the dataset are skipped.
2. **Label**: the list then shows only your changes; fill in each entry and
   mark it reviewed ([curation guide](../curation/README.md#label-in-the-workbench)).
3. **Submit changes**: shows what would be sent and any conflict, then opens a
   pull request on Hugging Face after you confirm. It needs a one-time
   `uv run hf auth login` in a terminal.

The [contribution guide](../README.md#add-images) describes the whole flow.

## Saved artifacts

| Artifact | Path |
| --- | --- |
| Scan runs (OCR passes, decisions, detection) | the product cache, `~/Library/Caches/vipi/runs/<run-id>/` on macOS |
| Evaluation runs | `runs/evaluations/<run-id>/` (ignored by Git) |
| Saved baselines | `research/baselines/<run-id>.json` (committed) |

Research OCR models, profiles and the diagnostic detector are available from the
command line only; see the [research CLI reference](../../docs/research-cli.md).
