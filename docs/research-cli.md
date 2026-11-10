# Research CLI reference

Every research command with all its arguments and options. Run them from a
source checkout after the [development setup](development.md); they are
separate from the public [`vipi setup` / `vipi scan`](cli.md) interface. Every
command and subcommand accepts `-h` / `--help`; help starts no inference and
downloads no models.

## Dataset download

```bash
uv run python -m research.download
```

Fetches `catalog.json`, `vocabulary.json` and `images/` into
`research/dataset/` from the immutable revision in `research/dataset.json`;
public downloads use no token. It has no arguments or options. See
[dataset paths and contributions](../research/README.md#download-images).

## Dataset curation

```bash
uv run python -m research.curation validate [--dir DIR] [--images-root DIR]
uv run python -m research.curation summary [--dir DIR] [--table]
uv run python -m research.curation templates [NAME] [--dir DIR]
uv run python -m research.curation generate SPEC.json [--preview FOLDER] [--dir DIR] [--images-root DIR]
uv run python -m research.curation add IMAGE... --label LABEL --content CONTENT --source NAME --license LICENSE --provenance TEXT [--repository URL] [--dir DIR]
uv run python -m research.curation changes [--dir DIR]
uv run python -m research.curation upload [--dry-run] [--message TEXT] [--dir DIR]
```

| Subcommand | Purpose |
| --- | --- |
| `validate` | Check the dataset against its vocabulary and images; exits 1 on errors. |
| `summary` | Count kept images per value, label and text template. |
| `templates` | List the screenshot templates, their spec fields and example specs. |
| `generate` | Render a generated-image spec and add its entries. |
| `add` | Add your own images as unreviewed entries; identical images already in the dataset are skipped. |
| `changes` | List your changes since the downloaded revision. |
| `upload` | Open a dataset pull request on Hugging Face with only your changes; needs `hf auth login` and exits 1 on conflicts. |

| Argument or option | Subcommands | Meaning and default |
| --- | --- | --- |
| `--dir DIR` | all | Dataset folder. Default `research/dataset`. |
| `--images-root DIR` | `validate`, `generate` | Folder that holds `images/`. Default: `--dir`. |
| `--table` | `summary` | Print the label balance per content type as a table instead of JSON. |
| `NAME` | `templates` | Optional; show this one template in detail. |
| `SPEC.json` | `generate` | Required spec file, e.g. `research/curation/generated/benign_text.json`. |
| `--preview FOLDER` | `generate` | Render the new images into `FOLDER/images` only and add nothing to the dataset. |
| `IMAGE...` | `add` | Required; one or more PNG, JPEG or WebP files. |
| `--label LABEL` | `add` | Required: `benign`, `injection` or `jailbreak`. |
| `--content CONTENT` | `add` | Required content type from the vocabulary, e.g. `web_page`. |
| `--source NAME` | `add` | Required short name of where the images come from, e.g. `my_screenshots`. |
| `--license LICENSE` | `add` | Required license of the images, e.g. `CC-BY-4.0`. |
| `--provenance TEXT` | `add` | Required; how the images were made or where they were found. |
| `--repository URL` | `add` | URL of the source, if any. |
| `--dry-run` | `upload` | Show what would be sent and any conflict; send nothing. |
| `--message TEXT` | `upload` | Commit message of the pull request, which Hugging Face also shows as its title. Default `Add evaluation images`. |

Invalid input exits 2. See the [curation guide](../research/curation/README.md)
and [how to add images](../research/README.md#add-images).

## Workbench

```bash
uv run python -m research.workbench serve [--port PORT]
```

| Subcommand or option | Meaning and default |
| --- | --- |
| `serve` | Start the workbench (scan an image, evaluate, dataset) on `127.0.0.1`. |
| `--port PORT` | Port to listen on. Default `8000`. |

It uses the product scan options only; prepare local models with `vipi setup`
first. See the [workbench guide](../research/workbench/README.md).

## Evaluation and baseline

```bash
uv run python -m research.evaluate split [--check]
uv run python -m research.evaluate status CONFIGURATION [--split SPLIT]
uv run python -m research.evaluate run CONFIGURATION [--split SPLIT] [--confirm-test-split] [--run-id ID] [--runs-dir DIR] [--dry-run] [--no-reuse-ocr]
uv run python -m research.evaluate save-baseline RUN_ID [--runs-dir DIR]
```

| Subcommand | Purpose |
| --- | --- |
| `split` | Write `research/splits.json` from the downloaded dataset. |
| `status` | Report whether the saved baseline matches this checkout: `fresh`, `stale` with the changed fields, or `none`; exits 0 only when fresh. |
| `run` | Run or resume an evaluation and compare it with the saved baseline; exits 0 for a planned or complete run and 1 for an incomplete one. |
| `save-baseline` | Save a complete run's summary as the baseline in `research/baselines/`. |

| Argument or option | Subcommands | Meaning and default |
| --- | --- | --- |
| `--check` | `split` | Only verify that the committed split matches the dataset; write nothing. |
| `CONFIGURATION` | `status`, `run` | Required: `local-speed`, `local-balanced`, `local-quality-clef-flash`, `local-speed-prompt-guard`, `local-balanced-prompt-guard`, `local-quality-prompt-guard`, `cloud-google`, `cloud-openai`, `cloud-mistral`, `cloud-google-jev`, `cloud-openai-jev` or `cloud-mistral-jev`. |
| `--split SPLIT` | `status`, `run` | `development` (default) or `test`. |
| `--confirm-test-split` | `run` | Required for the one-time confirmation run on the test split. |
| `--run-id ID` | `run` | Resume this run; default: a new run ID. |
| `--runs-dir DIR` | `run`, `save-baseline` | Folder of evaluation runs. Default `runs/evaluations`. |
| `--dry-run` | `run` | Show the plan, including how many images would be reused, without scanning. |
| `--no-reuse-ocr` | `run` | Scan every image from scratch instead of reusing earlier OCR and detection results. |
| `RUN_ID` | `save-baseline` | Required run ID of a complete run. |

Errors exit 2. The configurations and reuse rules are described in the
[evaluation guide](../research/evaluate/README.md).

## OCR benchmark

The runner behind the evaluation can also be used directly:

```bash
uv run python -m research.ocr_eval.benchmark DIRECTORY --configuration NAME... [--selection-file FILE] [--reuse-ocr-from RUNS_DIR]
uv run python -m research.ocr_eval.benchmark_report DIRECTORY --output FILE
```

| Argument or option | Command | Meaning and default |
| --- | --- | --- |
| `DIRECTORY` | both | Required. `benchmark`: a new run directory or a matching one to resume (failed attempts are kept). `benchmark_report`: a retained benchmark directory. |
| `--configuration NAME...` | `benchmark` | Required; one or more evaluation configurations (see above), run one after another. |
| `--selection-file FILE` | `benchmark` | JSON file that freezes an ordered subset of entry IDs from the dataset. Default: all entries. |
| `--reuse-ocr-from RUNS_DIR` | `benchmark` | Reuse OCR results of earlier evaluation runs in this folder when OCR settings, OCR sources and the image are identical; detection runs again. |
| `--output FILE` | `benchmark_report` | Required; write the JSON report here and a Markdown sibling, without inference. |

A successful `benchmark` exit means attempts were recorded, not that all scans
passed; inspect the report's failure and unscored counts. Invalid inputs or
unrecoverable worker startup errors exit nonzero. See the
[benchmark protocol](ocr-benchmark.md) for metrics, timing, fees, artifacts and
claim boundaries.
