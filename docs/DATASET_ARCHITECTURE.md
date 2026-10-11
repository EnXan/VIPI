# Dataset architecture

Upstream images and annotation tables stay under `datasets/external/`. The current
OCR evaluation uses a small, balanced sample referencing originals and reviewed
whole-image filter variants:

```text
datasets/
├── external/                       # original upstream datasets
├── derived/ocr_obfuscation/v1/      # 150 filtered images and review comparisons
├── derived/anamorpher/v1/          # 1,728 generated originals, reveals and inputs
├── catalog/
│   ├── datasets.csv                # complete local source inventory
│   ├── README.md
│   └── ocr/
│       ├── ocr_metadata.json        # 1,000 base records + verified Anamorpher cases
│       ├── ocr_metadata.schema.json
│       ├── ocr_datasets.csv
│       ├── ocr_selection_report.json
│       ├── ocr_metadata.clean.json
│       ├── ocr_selection_report.clean.json
│       └── ocr_obfuscation_manifest.json
└── .cache/                         # transient files; never an annotation source
```

`ocr_metadata.json` is a JSON array, not JSONL. Each record contains only `image`
(repository-relative path), `text` (exact source reference) and `category` (dataset ID).
Font attributes, security labels and training labels are not required by this schema.

Build with `.venv/bin/python scripts/datasets/build_ocr_metadata.py --count 1000 --seed 42 --textocr-share 0.5`.
The builder reconstructs source-backed references, excludes missing images and
untranscribed cases, deduplicates exact image bytes, and samples without replacement.
TextOCR receives 50% of the sample; the other four datasets each receive 12.5%.
Selection is random, without difficulty labels. FigStep is excluded.
Refresh the complete inventory with `.venv/bin/python scripts/inventory_datasets.py`.

The active sample replaces 150 image paths (global random sample, seed 20261004)
with reviewed variants: 30 each of Gaussian blur, motion blur, Gaussian noise,
JPEG compression and resolution loss. Three requested severity levels are capped
for small text and visual readability; 29 variants were further softened after
review. The total remains 1,000, with unchanged text/category and image dimensions.
Raw images and `.clean.json` snapshots are retained for paired evaluation. Parameters,
random seeds, source/output hashes and the limited visual review scope are recorded
in the manifest; this does not upgrade Silver transcripts to Gold.

After a source rebuild, run
`.venv/bin/python scripts/datasets/obfuscate_ocr_images.py apply` to reactivate
the reviewed variants. `render` recreates images with ImageMagick and resets their
review status. `previews` only rebuilds comparison images. Do not replace the
clean snapshots when changing the source selection; use a new filter version.

The selection report retains annotation scope, existing regions, provenance, quality,
image hashes, usage rights and content groups separately from the minimal index.
Source-declared and target-only references must not be treated as full-image
transcripts. In particular VPI-Bench omits other UI text and MM-SafetyBench SD_TYPO
omits background text. All reconstructed references are Silver; the old manually
edited shards were not restored from Trash.

TextOCR uses local train annotations and their matching scene images. Its source
word texts are joined by newlines in annotation order; this is not a guaranteed
full-image reading order. The report preserves word polygons and `reading_order_known: false`.
Unreadable/non-English regions marked `.` are omitted from text and retained as
`ignored_regions`. Images containing no transcribed words are excluded. Use
matched word regions for scoring to avoid penalizing arbitrary reading order.

No splits are created. Keep variants sharing a content group in the same split if
splits are added later. OCR eligibility does not imply training permission.

Anamorpher supplements the base using a complete finite grid of 1,728 combinations.
The grid covers three generators (Nearest with all four diagonal offsets), two
parameter profiles, two target sizes, nine alignments, two font sizes, two text-free
procedural backgrounds and two payload texts. Each original is four times its target
width and height. Twelve backend/interpolation combinations are probed on padded
text windows; the selected full-frame downscale is saved and independently OCR-checked.
Only cases passing the recorded character/contrast thresholds enter the index.
Failed controls remain in the generation manifest and on disk.

Anamorpher reference scope is `target_text_only_after_declared_downscale`.
The minimal index points to the original high-resolution input; the selection
report and `anamorpher_manifest.json` record the required downscale, exact text,
regions, seed, source commit, hashes, libraries and full reveal. Native stealth
and exhaustive manual readability are not certified. The two payload content
groups must stay together in later splits. Synthetic references are kept distinct
from the base's Silver source transcripts.

After rebuilding and applying base filters, run
`.venv-anamorpher/bin/python scripts/datasets/generate_anamorpher_ocr.py append`.
Validate using `scripts/datasets/validate_anamorpher_ocr.py --check-catalog --reproduce`
in that same environment. The existing 150 filters continue to affect only the
1,000-image base. Both `.pre_anamorpher.json` snapshots preserve that base, while
the `.clean.json` snapshots preserve its unfiltered version. Generation details,
dependency pins and representative previews are documented in the catalog README.

Transformation outputs, model predictions and evaluation metrics belong in separate
output directories, for example `datasets/derived/transforms/<pipeline-version>/`
and `runs/<run-id>/`. The curated obfuscation sample is the explicit exception:
its active index references the reviewed derivatives and keeps the clean index
separately; predictions and metrics still remain outside the catalog.

The legacy rich-catalog import/review tools need their previous source shards and
are not used to rebuild or edit the current simple OCR sample.
