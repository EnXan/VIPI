# Catalog curation

Tools for rebuilding the evaluation data as **one combined catalog**: every
image has one entry with its benign/injection/jailbreak label, techniques,
goal, obfuscation, evidence, content, caller-context cases and an optional OCR
reference. The design is recorded in
[ADR 0051](../../adr-code/0051-combined-evaluation-catalog.md); the agreed
taxonomy is in `vocabulary.py`.

The combined catalog is a draft. VIPI still evaluates the two pinned catalogs
until the rebuilt catalog is merged into the dataset and loaders are adapted.

## Build the draft

```bash
uv run python -m research.download
uv run python -m research.curation migrate
```

This writes `.local-assets/dataset-submission/catalog.json` and
`vocabulary.json` (ignored by Git). Known values are prefilled and every entry
starts unreviewed:

- detection labels from the case without context, techniques, obfuscation,
  payload, cases and payload regions; technique `jailbreak` becomes the label
  `jailbreak`;
- OCR transcripts, scope, regions, source, provenance and license;
- source-based labels (textocr benign; typographic, cyberseceval3, vpi_bench
  injection; mm_safetybench jailbreak), typographic variants as obfuscation,
  and content where the source makes it clear.

Byte-identical images present in both catalogs become one entry. Image paths
keep their dataset locations (`ocr_eval/images/…`, `detection_eval/images/…`).
`migrate` refuses to overwrite an existing draft; `--force` replaces it and
discards labeling work in it.

## Check the draft

```bash
uv run python -m research.curation validate
uv run python -m research.curation summary
```

`validate` checks keys, vocabulary values, single/multiple fields, fields that
do not apply to a label, curation decisions, duplicate ids, identical images
kept twice, and image files and hashes. Unknown licenses are warnings.
`summary` counts kept images per value and lists values below 10. It also
shows kept images per content and label (`label_by_content`) and checks text
templates (texts overlapping by 80 % or more): `over_limit` lists more than
three images with the same template, label and obfuscation; `inconsistent`
lists templates whose images differ in techniques or goal. The rules are in
ADR 0051.

`summary --table` prints the label balance per content: share of the set,
benign and attack shares, distance to the 50 % benign target in percentage
points, and how many images the smaller side is missing (or how many the
larger side would have to lose). The `balance` key holds the same numbers in
JSON.

## Generated images

```bash
uv run python -m research.curation generate research/curation/generated/benign_text.json
```

renders a spec of texts and adds one unreviewed entry per new image to the
draft (rendering in `render.py`, spec handling in `generate.py`). Two styles:
`typographic` reproduces the typographic source (512×256, Arial 19 px, black
on white; kept for a few examples only); `varied` picks font, size, colours
(no plain white), background pattern (solid, gradient, stripes, dots, grid,
checker, noise), canvas and alignment from a fixed palette, seeded by the
text. `typographic_rerender.json` re-renders typographic attack texts in the
varied style. Images go to
`research/generated/incoming/<id>.png` (ignored by Git; the id is the start of
the PNG hash), so running a spec again adds nothing. Each entry gets source
`vipi_generated`, license Apache-2.0 and the readable text as a gold OCR
reference (homoglyph characters stay in `payload`).

A spec sets `label`, `content` and optionally `style`; items set `text`,
`kind` and `obfuscation` and may set `style`, `content`, `techniques`, `goal`
and `evidence`. Obfuscations: `low_contrast`, `italic_font`, `small_font`,
`blur`, `distorted_text`, `rotated_text`, `mirrored_text`,
`unicode_homoglyphs`, `split_text` (numbered panels), `flowchart` (step boxes)
and `image_scaling`. `image_scaling` uses the nearest-neighbour generator of
[Trail of Bits Anamorpher](https://github.com/trailofbits/anamorpher), the tool
behind the catalog's scaling attacks. Plain text items use a 3200×3200 grey
decoy. Screenshot items can use a screenshot decoy with an empty target panel;
the target panel's instruction appears after 4:1 nearest-neighbour
downscaling. It needs a checkout (numpy only,
no Torch or TensorFlow) in `.local-assets/anamorpher` or `VIPI_ANAMORPHER`:

```bash
git clone https://github.com/trailofbits/anamorpher.git .local-assets/anamorpher
git -C .local-assets/anamorpher checkout 6aa9877ed64d0d1b1bf6d8b86d754ab5098c155b
```
For `split_text` and `flowchart`, `|` in the text marks panels or steps.
Use the same generator and the same mix of styles for attack text images, so
neither renderer nor style reveals the label (ADR 0051 rule 5).
Items with a `template` are interface screenshots (`screens.py`, templates
in `screen_templates.py`): an HTML page captured with headless Chrome (found
through `VIPI_CHROME`, the macOS app or `google-chrome`/`chromium`), with
`text` as the target text and its only OCR reference (`target_text_only`).
`others`, `meta`, `metrics`, `lines`, `nodes`, `role` and `comment` fill the
surrounding page. Product templates also support `modal_*` fields for fake
workflow dialogs, `scatter_fragments` for separate notes, and `form_variant`
for distinct Jira Service Management, Okta Admin, GitHub Actions and Linear-like
form surfaces. Product desktop views can mark `highlight_file`; illustration
views accept `diagram_nodes` and `highlight_index`. Screenshot obfuscations:
`split_text` (fragments in separate
bubbles, tiles or comments), `flowchart` (the `flow` and `product_flow` templates),
`unicode_homoglyphs`, `small_font` (9 px), `low_contrast` (30 % opacity), `base64` (the target text shown
encoded; the OCR reference is the encoded string), `blur`, `distorted_text`,
`mirrored_text`, `rotated_text` and screenshot-backed `image_scaling`.
Product screenshot specs can set `target_only_obfuscation` so rotation, mirroring,
blur and distortion affect only the target text, leaving the product page
upright. `attack_product_batch_01.json` through `attack_product_batch_05.json`
reproduce attack rows 1–50 in synthetic Jira issue views and service
forms, Okta identity administration, GitHub Actions workflow and environment
views, Linear release updates, Figma-style design files and FigJam boards,
release posters, local-agent desktop windows, technical illustrations and
wordless posters, diagrams and web interfaces.
Each surface has its own navigation, panel
placement, colour treatment and controls. Their target text, surrounding context and
labels are in the specs. Batch 04 row 40 uses TextOCR sample
`textocr:2929d7a50c01b07f` under CC-BY-4.0 and records that source in its
provenance. Batch 05 row 41 uses a separate TextOCR CC-BY-4.0 whiteboard photo;
rows 42–50 have `image_only` evidence, empty payloads and no OCR references.
`attack_product_row_51.json` is the final attack: a wordless local-agent
desktop with a selected production environment, pending review gate and
cursor-focused run control. It has `image_only` evidence and no OCR reference.
Screenshot specs require Chrome; only `image_scaling` specs need the pinned
Anamorpher checkout. PNG hashes can differ with another Chrome or font version.
From a prepared draft, regenerate the five ten-image batches and final row with:

```bash
uv run python -m research.curation generate research/curation/generated/attack_product_batch_01.json
uv run python -m research.curation generate research/curation/generated/attack_product_batch_02.json
uv run python -m research.curation generate research/curation/generated/attack_product_batch_03.json
uv run python -m research.curation generate research/curation/generated/attack_product_batch_04.json
uv run python -m research.curation generate research/curation/generated/attack_product_batch_05.json
uv run python -m research.curation generate research/curation/generated/attack_product_row_51.json
```

`benign_screens.json` holds the benign
screenshots. Items with a `base_image` (a path under the images root) put
their text over that photo as faint white text (`high_transparency`);
`benign_photos.json` does this for 10 TextOCR photos. Items with `from` (a
catalog entry id) apply `blur`, `distorted_text`, `mirrored_text` or
`rotated_text` to that entry's image and copy its labels, text and source;
`attack_screens_obfuscated.json` does this for 20 vpi_bench attack
screenshots.
The running workbench reloads the draft when the file changes.

## Label in the workbench

Start the workbench (`uv run python -m research.workbench serve`) and open the
**Label** tab. It edits the draft in `.local-assets/dataset-submission/`.

- Filter by status (unreviewed first), any field value, source or text.
- **Group similar** (on by default) lists entries with nearly the same image
  or text together under a group heading, largest groups first. It only
  orders the list; the rules are in `similarity.py`. The first grouped list
  takes a few seconds while image hashes are computed.
- Click chips to set labels; `label` and `content` take one value, the others
  several. Fields that do not apply to the chosen label are disabled.
- Every click is validated and saved immediately; rejected changes show the
  reason and leave the file unchanged.
- **Mark reviewed** (key `R`) records that an entry is checked; **Drop…** asks
  for a reason (`duplicate of <id>` also fills `duplicate_of`); **Keep**
  restores a dropped entry. Arrow keys move between images.
- **+ value** adds a vocabulary value. It is normalized (`Low-Contrast` →
  `low_contrast`) and you are asked to confirm when a similar spelling exists.
  **Manage vocabulary** renames values (renaming onto an existing value merges
  both in every entry) and removes values no entry uses.

## Model proposals

A model can propose labels following [LABELING_GUIDE.md](LABELING_GUIDE.md).
It writes `proposals/batch-*.json` next to the draft and never edits the
catalog; later batch files override earlier ones for the same entry. In the
Label tab, choose status **Proposed**: proposed values are outlined and the
panel lists every change with the model's rationale.

- **Approve** (key `A`) applies the proposal, adds any proposed new vocabulary
  value it uses, marks the entry reviewed and moves on.
- **Deny** (key `D`) discards the proposal; the entry stays unreviewed.

Decisions are stored in `proposals/decisions.json`. Proposals with values that
are neither in the vocabulary nor proposed as new cannot be approved.

## Entry format

| Field | Content |
| --- | --- |
| `id`, `image`, `image_sha256` | Identity; `id` keeps the OCR id where one existed |
| `label` | `benign`, `injection` or `jailbreak` (verdict without caller context) |
| `techniques`, `goal`, `obfuscation`, `evidence` | Lists of vocabulary values |
| `content` | One vocabulary value: what the image shows |
| `payload` | Primary visible text from the detection catalog |
| `cases` | `expected` plus optional caller `context` |
| `ocr_reference` | Optional: `text`, `scope`, `quality`, `reading_order_known`, `regions` |
| `source` | `dataset`, `repository`, `sample_id`, `license`, `provenance`, `content_group_id` |
| `migrated_from` | Former ids and image paths in the two old catalogs |
| `curation` | `reviewed`, `decision` (`keep`/`drop`), `reason`, `duplicate_of` |
