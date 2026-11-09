# Research

Research tools import `vipi`; product code must not import research or Flask.
The research workspace has these areas:

| Directory | Purpose |
| --- | --- |
| [`dataset/`](#download-images) | The evaluation dataset (downloaded, ignored by Git), read through `catalog.py` |
| [`curation/`](curation/README.md) | Dataset validation, vocabulary, labeling store and image generators |
| [`evaluate/`](evaluate/README.md) | Frozen development/test split, evaluation runs of scan configurations and the saved baseline |
| [`ocr_eval/`](ocr_eval/README.md) | OCR metrics, the dataset benchmark, retained experiments and historical reports |
| [`workbench/`](workbench/README.md) | Local interface: scan an image, evaluate against the baseline, label the dataset |

Start the workbench from the repository root:

```bash
uv run python -m research.workbench serve
```

Images and labels are maintained together in the public
[VIPI Evaluation dataset](https://huggingface.co/datasets/EnXan/VIPI-evaluation).
GitHub tracks the evaluation code and the exact dataset commit in `dataset.json`.

## Download images

Run these commands from a VIPI source checkout. For downloading only, install
the research dependencies below. For workbench scans, use the full
[development setup](../docs/development.md) with the OCR and detector extras.

```bash
uv sync --extra research
uv run python -m research.download
```

Public downloads require no Hugging Face account or token. The command uses
the full commit SHA in [`dataset.json`](dataset.json) and places the dataset
in `research/dataset/`: `catalog.json`, `vocabulary.json` and `images/`
(ADR 0053). These copies are ignored by Git. Existing downloaded files can be reused and
remain available offline. Downloading again overwrites local catalog edits;
submit them first (see [Add images](#add-images)).

## Add images

Submit each image and its catalog changes together as a pull request on the
[dataset repository](https://huggingface.co/datasets/EnXan/VIPI-evaluation).
You need a Hugging Face account to submit a contribution. Through its website,
upload the image and updated catalog using **Open as a pull request**. The
[dataset contribution guide](https://huggingface.co/datasets/EnXan/VIPI-evaluation/blob/main/CONTRIBUTING.md)
also describes that workflow.

For a CLI submission from this source checkout:

1. Work in the local dataset folder `research/dataset/` (ignored by Git): add
   images as `images/<id>.png` and their entries in `catalog.json`, label them
   in the workbench **Label** tab or by hand following the
   [labeling guide](curation/LABELING_GUIDE.md), and keep each content type
   at 50 % benign. Describe the source or generation method and the image
   license in each entry's `source`.

2. Check the folder:

   ```bash
   uv run python -m research.curation validate
   uv run python -m research.curation summary --table
   ```

3. Log in and upload the catalog and new images as a PR:

   ```bash
   uv run hf auth login
   uv run hf upload EnXan/VIPI-evaluation research/dataset . --repo-type dataset --create-pr --include 'catalog.json' --include 'images/*' --commit-message 'Add evaluation images'
   ```

Only the owner or authorized maintainers merge submissions. Images in a public
PR can be visible before review; do not submit confidential material or real
credentials. The official dataset contains accepted contributions from `main`.

## Review and adopt dataset changes

The maintainer reviews the image, catalog diff, transcript, classification,
caller context and source information in the
[dataset PR list](https://huggingface.co/datasets/EnXan/VIPI-evaluation/discussions).
Merging the PR approves its inclusion in the dataset.

To use the updated dataset in VIPI, update `revision` in `research/dataset.json`
to the full reviewed dataset commit SHA through a GitHub PR, then rerun
`uv run python -m research.download`. A merge on Hugging Face does not
automatically change this project's pinned evaluation inputs.

New or changed entries change the split and make saved baselines stale.
In the same PR, regenerate and review the split, then save fresh baselines:

```bash
uv run python -m research.evaluate split
uv run python -m research.evaluate split --check
```

See the [evaluation guide](evaluate/README.md#splits) before committing a
regenerated split.
