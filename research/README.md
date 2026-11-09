# Research

Research tools import `vipi`; product code must not import research or Flask.
The research workspace has these areas:

| Directory | Purpose |
| --- | --- |
| [`dataset/`](#download-images) | The evaluation dataset (downloaded, ignored by Git), read through `catalog.py` |
| [`curation/`](curation/README.md) | Dataset validation, vocabulary, labeling store and image generators |
| [`evaluate/`](evaluate/README.md) | Frozen development/test split, evaluation runs of scan configurations and the saved baseline |
| [`ocr_eval/`](ocr_eval/README.md) | OCR metrics, the dataset benchmark, retained experiments and historical reports |
| [`workbench/`](workbench/README.md) | Local interface: scan an image, evaluate against the baseline, add, label and submit dataset images |

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

From this source checkout, after downloading the dataset:

Everything below works on the workbench **Dataset** page
(`uv run python -m research.workbench serve`) in three steps: **Add images**,
**Label**, **Submit changes**. The commands do the same from a terminal.

1. **Add your images.** On the Dataset page, press **Add images**, choose or
   drop the files and fill in label, content type, source name, license and
   provenance. From a terminal:

   ```bash
   uv run python -m research.curation add shots/*.png --label benign --content web_page --source my_screenshots --license CC-BY-4.0 --provenance "Screenshots of my demo shop"
   ```

   Each image gets an unreviewed entry; identical images already in the
   dataset are skipped. To render new images instead, use the
   [image generators](curation/README.md#generated-images).

2. **Label them** on the Dataset page: after adding, **Only my changes** is
   ticked and the new entries are listed. Set the classification following
   the [labeling guide](curation/LABELING_GUIDE.md), type everything readable
   in the image (the OCR reference) and the text the label is about (the
   payload), check source and license, and mark each entry reviewed. **Balance per
   content type** shows where benign or attack images are missing; keep each
   content type at 50 % benign.

3. **Check and submit.** Sign in to Hugging Face once in a terminal
   (`uv run hf auth login`; the page never asks for the token). On the Dataset
   page, **Submit changes** shows how many entries you added, changed and
   dropped and any conflict, and opens the pull request after you confirm.
   From a terminal:

   ```bash
   uv run python -m research.curation validate
   uv run python -m research.curation changes
   uv run hf auth login
   uv run python -m research.curation upload --dry-run
   uv run python -m research.curation upload --message "Add demo shop screenshots"
   ```

   `upload` sends only your changes: entries you added, changed or dropped
   since your download, applied to the current `main` of the dataset, plus
   your new images. Others' contributions merged meanwhile stay intact. If
   someone changed the same entry, it stops and names the conflict; download
   the new revision and repeat your change.

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
