# ADR 0056: Contributors add or generate images locally and submit only their changes

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
- **Workbench.** The Label tab is renamed **Dataset** and leads through the
  contribution in three steps: **Add images** (multipart upload into the same
  `add_images`, then the list switches to *Only my changes*), **Label**, and
  **Submit changes** (the `upload --dry-run` result first, then the upload
  after an explicit confirmation). The page never takes a Hugging Face token;
  the server uses the token stored by `hf auth login` and explains how to sign
  in when none is stored. Generating images stays on the command line.
- **Generators.** Fonts are looked up per family on macOS first (so existing
  generated images reproduce byte for byte), then Windows (same faces), then
  Linux replacements (Liberation, DejaVu), with the repository's Geist font as
  the last resort, so text images render on every platform. `templates [NAME]`
  lists the screenshot templates with the spec fields each one reads (found in
  its source) and a working example item. `generate --preview FOLDER` renders
  without changing the dataset. `examples/starter.json` is a small spec to copy.
  No fonts are bundled beyond Geist, because no open font files were available
  without a new download.

## Alternatives and consequences

- *Refuse an upload when `main` moved since the download.* Simpler, but every
  contributor would have to redo their work by hand after each merge.
- *Drop labeling and make the tab only about creating images (asked
  2026-11-09).* Added images have no payload, reference or classification
  yet and existing entries need corrections, so labeling stays; the tab is
  named after its subject instead.
- *A spec editor for the generators in the browser.* A large separate concept
  without a current request; the spec files and `templates` stay.
- *One catalog file per entry.* Removes conflicts at the file level, but
  changes the published layout of ADR 0053 for every reader.

Consequences: finding changes needs the downloaded revision's catalog from
Hugging Face once (then cached). Generated images on Linux or Windows look
different from macOS ones (other font files), so their hashes differ.

## Validation boundary

Offline tests cover adding (duplicates, invalid values, missing source),
change detection, merging with and without conflicts, vocabulary merging, the
upload operations against a simulated Hugging Face API, text and source
editing, the new routes (including image upload, submission preview,
confirmation, missing login and an unreadable dataset), font lookup order, the Geist fallback, the template
description and preview mode. `changes` was run against the real pinned
revision; re-rendering the two text specs on macOS reproduced all 81 images
byte for byte; the starter spec rendered in preview. In the browser, adding an image on the
Dataset page listed it under *Only my changes* (the dataset was restored
afterwards); before Hugging Face PR #2 was merged the submission preview
showed the missing-catalog message, and after the merge a dry run against
`main` reported nothing to submit. No real upload has been made; Linux and Windows rendering is untested.
