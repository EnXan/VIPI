# ADR 0012: Reviewed Hugging Face evaluation dataset

Status: Accepted, 2026-10-25.

## Context and sources

ADR 0011 kept the active OCR selection in a single Git-tracked catalog beside
an ignored, flat image directory. It preserved the 1,000 selected OCR references
and stable IDs while removing full source downloads and nested derived data.
That layout supported local evaluation but left image distribution and external
contributions unresolved. The user has now approved a public Hugging Face
dataset with community pull requests and maintainer approval.

This replaces ADR 0011's distribution decision while retaining the local flat
suite layouts, exact transcripts, provenance and stable IDs. Research remains
organized into `detection_eval/`, `ocr_eval/` and `workbench/`; the OCR loader,
metrics and runner remain in `ocr_eval/evaluation/`.

Sources: the user's accepted hosting proposal, [Hub contributions](https://huggingface.co/docs/hub/repositories-pull-requests-discussions),
[CLI uploads](https://huggingface.co/docs/hub/repositories-getting-started), and
[revision-pinned downloads](https://huggingface.co/docs/huggingface_hub/package_reference/file_download).

## Decision

- Publish images and catalogs together in the public
  `EnXan/VIPI-evaluation` Hugging Face dataset repository.
- Keep detection and OCR suites separate, with image paths relative to each
  suite's catalog directory. Preserve existing catalog contents and image bytes.
- Make the dataset repository the authoritative location for catalogs and
  images. Local JSON and image copies are ignored by GitHub's code repository.
- Pin the dataset repository and full commit SHA in `research/dataset.json`.
  `python -m research.download` downloads both suites or one selected suite.
- Keep write access with the owner or explicitly authorized maintainers.
  Contributors submit images and catalog changes together as a dataset PR.
  Merging is the approval step; do not automatically merge submissions.
- Update the pinned dataset revision separately through a GitHub PR after
  reviewing the dataset changes.

## Alternatives

- Generic file storage would require an additional contribution/review workflow.
- Keeping labels on GitHub while images live on Hugging Face splits one
  contribution across two repositories and review steps.
- Downloading the current `main` implicitly would change evaluation inputs
  without an intentional dataset-version update.

## Consequences

Fresh checkouts download the chosen dataset before using its local references.
An already downloaded dataset works offline. Downloading again can overwrite
local catalog edits, so contributors submit their edits through a dataset PR.
The public PR's files can be visible before merge; approval controls inclusion
in the official dataset, not private handling of submissions. Source rights
and attribution remain applicable to third-party fixtures.

## Validation boundary

Check the remote file list, public access, revision and representative downloads;
compare the published catalogs and image hashes with the local selection. Test
that the research downloader uses the pinned revision and only downloads suite
data. No OCR inference or execution of depicted payloads is part of publication.
