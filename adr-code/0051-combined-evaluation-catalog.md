# ADR 0051: One combined evaluation catalog with an editable vocabulary

Status: accepted as the rebuild target; draft tooling implemented on
2026-11-07; composition rules agreed on 2026-11-08. The pinned dataset and
VIPI's loaders are unchanged.

## Context and sources

The evaluation data consisted of an OCR catalog (1,000 entries, labeled only by
source dataset) and a detection catalog (113 entries with techniques,
obfuscation and caller-context cases); seven images were byte-identical across
both. Reviewing the development/test split showed source imbalance (textocr 500
images) and many near-identical images (vpi_bench 125 images, 27 distinct
contents). The user decided to rebuild the dataset from scratch, evenly
distributed by technique rather than by source, and to label all images in a
graphical interface with a saved vocabulary. The taxonomy was agreed in the
same session.

## Decision

- **One catalog.** OCR and detection are connected, and an image can carry
  injection information that extracted text alone does not show. Each image has
  one entry; byte-identical images from both old catalogs merge.
- **Fields.** `label` (`benign`, `injection`, `jailbreak`), `techniques`
  (method), `goal` (aim; OWASP Top 10 for LLM and Agentic Applications only as
  orientation), `obfuscation`, `evidence` (where an injection is visible),
  `content` (what the image shows), `cases` (expected plus optional caller
  context), optional `ocr_reference`, `source` with one `license` string,
  `migrated_from` and `curation`. `jailbreak` is a label, not a technique, so
  injection and safety detection stay separately measurable.
- **Vocabulary.** Allowed values live in `vocabulary.json` beside the catalog,
  seeded from the agreed taxonomy and editable later (add missing values,
  remove unused ones). Values are normalized to lowercase with underscores.
- **Storage.** Drafts are written to `.local-assets/dataset-submission/` and
  published as a Hugging Face dataset PR; VIPI adopts them by pinning the new
  revision.
- **Composition rules.** The catalog is an evaluation basis, possibly later
  training data. Balancing every field jointly is impossible (thousands of
  combinations), so each dimension gets the strictest rule it needs:
  1. *Balanced: label × content.* Every content type has attacks and benign
     images in similar numbers, so a system cannot score well by reacting to
     how an image looks (for example "plain text on white means attack").
  2. *Covered: techniques, goal, evidence, obfuscation.* At least 10 images per
     value, spread over several contents and sources. Technique, goal and
     evidence describe attacks only. Common obfuscations (`low_contrast`,
     `tiny_text`, `italic_font`) also appear on benign images, so hard-to-read
     text does not imply an attack. Ten images give coverage, not a precise
     per-value measurement.
  3. *Diverse: text and appearance.* No near-duplicates with the same label
     combination, and at most three images per text template, label and
     obfuscation: further copies of one template add weight, not new cases.
     Obfuscation is the visual variation that makes a repeated text a new
     case. Techniques and goal are not part of the key: the text determines
     them, so differing values within one template are labeling
     inconsistencies, reported for the label check.
     Typographic renderings keep one variant per text, spread evenly over
     the variants.
  4. *Contrast cases.* Harmless lookalikes (quoted injections, articles about
     prompt injection, imperative signs or IT instructions) and minimal pairs
     (the same image with and without an injection) are explicit targets. The
     near-duplicate rule keeps pairs because their labels differ.
     Benign obfuscations are filled to 10 per value, each placed where the
     attacks with that value are: base64 and most small_font on the new
     screenshots, high_transparency as faint white text over 10 benign
     TextOCR photos (CC-BY-4.0 derivatives that replace their source photos,
     like the transparency attacks, which are all photos), image_scaling and
     flowchart text images in place of 12 formerly clean benign text images.
     Replacing instead of adding keeps every content's balance. The cost,
     accepted by the user: 50 of the 62 benign screenshots are obfuscated
     (several with two values) and only a few clean benign text images
     remain. To keep screenshots obfuscated alike for both labels, 20 clean
     vpi_bench attack screenshots (CC-BY-4.0) were mirrored, rotated,
     distorted or blurred after the fact and replace their originals, with
     labels, payload, OCR reference and source copied: screenshots are now
     obfuscated 50 of 90 benign and 56 of 90 attack. Text-level obfuscations
     (split, homoglyphs, small font, base64) cannot be added to finished
     attack images without their HTML. Seven benign screenshots then got
     low_contrast (target text at 30 % opacity, about grey 188 on white),
     matching the attack screenshots' low_contrast in web pages, dashboards
     and code: screenshots are obfuscated 54 of 90 benign and 56 of 90
     attack.
  5. *Synthetic images.* Attacks and benign images are generated with the same
     generator and the same mix of styles, so neither renderer nor look
     reveals the label. Variety (fonts, sizes, colours, layouts) is wanted,
     but only when both labels get it: a uniform look that only one label
     has becomes a shortcut. Plain black text on white is kept for a few
     examples only: 9 original typographic attacks (3 clean, 3 low contrast,
     3 italic) and 9 benign counterparts. The other 36 typographic attack
     texts are re-rendered in the varied style (colours, background
     patterns, fonts, layouts) with their labels; their originals are
     dropped as duplicates of the re-rendered entries. Interface
     screenshots are HTML pages captured with headless Chrome, the way the
     attack screenshots were made: 62 benign screenshots (16 templates such
     as article, shop, docs, pull request, messenger, assistant chat, team
     chat, inbox, dashboard, memo, invoice, code editor and flowchart, with
     seeded accent colours, fonts and names) fill web_page, chat, email,
     dashboard, document, code and diagram to 50 % benign. Chrome is a host
     dependency of the generator only; rendering is deterministic on one
     machine, but other Chrome versions or fonts produce different images
     and therefore new ids. image_scaling images are made with the
     nearest-neighbour generator of Trail of Bits Anamorpher (Apache-2.0,
     commit 6aa9877, local checkout), the generator of the catalog's scaling
     attacks. The initial text images use the same 3200×3200 grey decoy and
     4:1 construction; product-view attacks can use a screenshot decoy
     with the same 4:1 construction (ADR 0052). An
     earlier own dot-pattern renderer was replaced because only benign images
     used it.
     Dark mode: generated screenshots skewed light on the benign side (154
     light / 46 dark benign against 127 / 70 attacks), which would let a
     detector read darkness as a sign of attack. 25 benign and 10 attack
     screenshots, spread across templates, were re-rendered with `dark`
     (`screens.DARK_CSS`, a browser-style lightness inversion that keeps hues and
     photos), replacing the light entries. Afterwards: 129 / 67 benign and
     117 / 76 attacks (light / dark by mean grey level). The inversion also
     lightens elements that are dark in light mode (terminal blocks, some
     headers); this affects both labels equally.
  6. *Origin.* Own images get their own source name, so public images (which
     may be in a tested model's training data) and own images are reported
     separately.
  7. *Label check before upload.* The Haiku denial rate from
     `decisions.json` and a blind relabel of about 50 random kept images
     estimate agreement; disagreements are resolved, and images that stay
     ambiguous are dropped.
  8. *Dataset card.* The Hugging Face PR includes a card with purpose,
     composition and splits, collection, labeling process, license and known
     limitations.
- **Split rule for the rebuilt catalog.** One image is one case; images with
  the same text go to the same side; distribution balanced by labels.

## Alternatives and consequences

- *Two catalogs.* Keeps OCR and detection apart but duplicates shared images
  and their labels and hides image-level injection evidence from the OCR side.
- *OWASP identifiers as fields.* Nearly every image is LLM01/ASI01, so they do
  not discriminate; plain goal names are simpler.
- *Repository overlay file for labels.* Faster, but labels would live apart
  from the images.
- *Automatic grouping rules (similar text, control pairs).* Rejected as too
  complex; near-duplicates are removed during curation with similarity hints.
- *Correct imbalance in the report only (strata, weighting).* Rejected by the
  user in favour of building the dataset right; per-content reporting remains
  a reporting choice, not a substitute for balance.
- *Shrink until every content is balanced.* Benign web pages, chats, emails
  and dashboards have 3–5 images each, so shrinking alone would leave unusable
  categories; missing benign images are added instead.

Reporting consequences for the benchmark (separate concept): report recall
and false-positive rate separately rather than accuracy, because deployment
sees far more benign images than this balanced set; give standard errors
clustered by text group and compare runs paired on the same images.

Sources for the composition rules: contrast sets (Gardner et al., 2020,
arXiv:2004.02709); over-defense benchmarks with trigger-word negatives
(CAPTURE, LLMSEC 2025; NotInject as used in arXiv:2506.07330); base-rate
argument (PromptShield, arXiv:2501.15145); error bars and clustered standard
errors (Miller, arXiv:2411.00640); contamination survey (arXiv:2502.14425);
Datasheets for Datasets (Gebru et al., arXiv:1803.09010). Kept-image counts on
2026-11-08: 494 images; text images 135 attacks against 18 benign; photos 55
attacks against 144 benign; web, chat, email and dashboard 3–5 benign each.

Consequences: prefilled values from source datasets (for example "textocr is
benign") are assumptions until reviewed. 226 entries have no known license,
mostly cyberseceval3 and synthetic or local detection fixtures. Catalog
loaders, workbench datasets, benchmark keys and the splitter still expect two
catalogs and need a separate migration after the dataset PR merges.

## Validation boundary

Offline tests cover merging identical images, prefill mapping, preserved
contexts and regions, vocabulary and label constraints, curation rules,
missing/unknown keys, image hash checks, counts and the overwrite guard. A
migration of the pinned revision produced 1,106 entries with no validation
errors and 226 unknown-license warnings. Since then every entry was reviewed
in the workbench Label tab and near-duplicates were dropped. The composition
rules are not applied yet; the counts above show the current gaps.
