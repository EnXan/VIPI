# 0053 — One evaluation dataset

Status: accepted for review, 2026-11-09. The layout is staged in Hugging Face
PR #2; VIPI switches its pin and loaders in a later change.

## Context and sources

The user asked for the combined catalog (ADR 0051) to replace both old
catalogs everywhere and for everything that only served them to be removed,
with simplicity as the priority. Until now the dataset held two catalogs with
their own layouts (`ocr_eval/catalog.json` + `images/`,
`detection_eval/cases.json` + `images/`), and the curation draft lived outside
the research tree with images spread over four folders.

This revises one part of ADR 0051. Its storage rule said: drafts are written to
`.local-assets/dataset-submission/` and published as a Hugging Face dataset PR;
VIPI adopts them by pinning the new revision. The rationale was to keep the
draft out of Git until review. The draft is now the dataset itself, so a
separate draft location and a second image layout no longer serve a purpose.

## Decision

- The dataset repository holds one catalog: `catalog.json`,
  `vocabulary.json` and `images/<id>.<ext>`, image paths relative to the
  repository root. Only kept entries are published; dropped entries and their
  reasons stay in the dataset's history (the first commit of PR #2).
- `ocr_eval/` and `detection_eval/` are removed from the dataset's main
  branch; older revisions keep them.
- Locally the dataset lives in `research/dataset/` (ignored by Git) with the
  same layout. The curation CLI, the generator (`images/<id>.png`) and the
  Label tab use it by default.
- VIPI keeps its current pin until the loaders (OCR benchmark, contribution
  evaluation, workbench scan) read this layout; the pin and
  `research.download` change together with them.

## Alternatives

- Keep the two catalogs beside the combined one: no loader changes, but two
  sources of truth and duplicated images.
- Keep the source folders (`ocr_eval/images`, `generated/…`) in the new
  dataset: no path rewrite, but four image folders for one catalog.
- Publish dropped entries: keeps drop reasons in the data, but most entries
  would describe images that are not in the dataset.

## Consequences

Users of the old layout must pin an older revision. Spec items that derive
from images outside the dataset cannot be regenerated from the new dataset
alone: 10 photo overlays and 2 product items use TextOCR base photos
(`base_image`), and 20 obfuscated attack screenshots derive from earlier
entries (`from`). They need the earlier revision's images. The local curation
folder moves from `.local-assets/dataset-submission/` to `research/dataset/`.

## Validation boundary

The Hugging Face PR revision holds exactly the 554 kept images; every hash
matches its entry. Curation validation reports 0 errors (175 unknown-license
warnings); research tests pass. The benchmark, contribution evaluation and
workbench scan still read the old pinned catalogs and are not yet verified
against this layout.
