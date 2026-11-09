# ADR 0056: Contributors add images locally and submit only their changes

Status: accepted, 2026-11-09.

## Context and sources

The user asked whether people can add new images to the dataset easily. An
assessment found: images had to be copied and their entries written by hand;
the Label page could not edit payload, OCR reference, source, license or
caller context; a contributor could not see their own additions or the label
balance there; and `hf upload` of the whole `catalog.json` let a later pull
request overwrite one merged meanwhile, because the dataset has one catalog
file ([ADR 0053](0053-one-evaluation-dataset.md)). Asked on 2026-11-09, the user
chose to submit only the changes.

## Decision

- `python -m research.curation add IMAGE...` copies images into
  `research/dataset/images/<id>.<ext>` (id = start of the SHA-256) and adds one
  unreviewed entry each with the given label, content, source name, license
  and provenance. Images already in the dataset are skipped.
- The Label page edits payload, OCR reference text, source fields and caller
  context cases, with the same validation as the label fields. A new reference
  covers the main visible text (`primary_visible_payload`,
  `reviewed_payload`). A reference with word regions keeps its text, because
  text and regions must change together.
- **Only my changes** lists entries added, changed or dropped since the
  downloaded revision; **Balance per content type** shows the 50 % benign
  target per content.
- `changes` lists the same difference; `upload` applies it to the current
  `main` of the dataset (added entries appended, changed entries replaced,
  dropped entries and their images deleted, vocabulary changes carried when
  only one side changed) and opens a pull request with `parent_commit` set to
  that `main`. An entry changed on `main` since the download, or the same id
  added there with other content, is a conflict and nothing is uploaded.
  `--dry-run` shows the plan.

## Alternatives and consequences

- *Refuse an upload when `main` moved since the download.* Simpler, but every
  contributor would have to redo their work by hand after each merge.
- *One catalog file per entry.* Removes conflicts at the file level, but
  changes the published layout of ADR 0053 for every reader.

Consequences: finding changes needs the downloaded revision's catalog from
Hugging Face once (then cached). Until the dataset PR that introduces the
one-catalog layout is merged, `main` has no `catalog.json` and uploads cannot
work. Generators for new images are improved separately.

## Validation boundary

Offline tests cover adding (duplicates, invalid values, missing source),
change detection, merging with and without conflicts, vocabulary merging, the
upload operations against a simulated Hugging Face API, text and source
editing and the new routes. `changes` was run against the real pinned
revision. No real upload has been made.
