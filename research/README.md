# Research

Research tools import `vipi`; product code must not import research or Flask.
The research workspace now has three areas:

| Directory | Purpose |
| --- | --- |
| [`detection_eval/`](detection_eval/README.md) | Reviewed image-based prompt-injection evaluation suite |
| [`ocr_eval/`](ocr_eval/README.md) | OCR evaluation with one `catalog.json` and local `images/` |
| [`workbench/`](workbench/README.md) | Local OCR and detection interface, CLI, saved runs and dataset browsing |

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

Download just one suite:

```bash
uv run python -m research.download detection_eval
uv run python -m research.download ocr_eval
```

Public downloads require no Hugging Face account or token. The command uses
the full commit SHA in [`dataset.json`](dataset.json) and places files here:

| Suite | Local catalog | Local images |
| --- | --- | --- |
| Detection | `research/detection_eval/cases.json` | `research/detection_eval/images/` |
| OCR | `research/ocr_eval/catalog.json` | `research/ocr_eval/images/` |

These copies are ignored by Git. Existing downloaded files can be reused and
remain available offline. Downloading can overwrite local catalog edits; use a
separate submission directory when preparing contributions.

## Add images

Submit each image and its catalog changes together as a pull request on the
[dataset repository](https://huggingface.co/datasets/EnXan/VIPI-evaluation).
You need a Hugging Face account to submit a contribution. Through its website,
upload the image and updated catalog using **Open as a pull request**. The
[dataset contribution guide](https://huggingface.co/datasets/EnXan/VIPI-evaluation/blob/main/CONTRIBUTING.md)
also describes that workflow.

For a CLI submission from this source checkout:

1. Fetch the latest accepted catalog from `main` into a separate directory.
   `.local-assets/` is ignored by this code repository, so submission files stay
   out of GitHub commits.

   ```bash
   uv run hf download EnXan/VIPI-evaluation detection_eval/cases.json --repo-type dataset --revision main --local-dir .local-assets/dataset-submission
   ```

2. Create `.local-assets/dataset-submission/detection_eval/images/`, put the new
   images there, and edit the downloaded `detection_eval/cases.json`. Use
   unique filenames and the [detection entry format](detection_eval/README.md).
   Record the exact visible payload, the expected label, attack techniques and
   obfuscation. Group caller-context variants under the same image entry.
   Describe the source or synthetic generation method and applicable image
   license in the PR description.

3. Log in and upload the submission as a PR:

   ```bash
   uv run hf auth login
   uv run hf upload EnXan/VIPI-evaluation .local-assets/dataset-submission . --repo-type dataset --create-pr --include 'detection_eval/cases.json' --include 'detection_eval/images/*' --commit-message 'Add detection evaluation images'
   ```

For OCR submissions, use `ocr_eval/catalog.json` and `ocr_eval/images/` in the
same commands and directory layout. Follow the existing
[OCR record format](ocr_eval/README.md), preserving exact transcripts,
reference scope, word regions and source provenance. Keep existing record IDs
unchanged.

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
