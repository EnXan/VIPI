# VIPI CLI

The public commands are `vipi setup` and `vipi scan` (`python -m vipi`
provides the same interface). Use Python 3.12 and uv.
For installation, see the [README](../README.md#quick-start); for the exact
model-to-purpose mapping, see [models and hardware](models.md). From a checkout:

```bash
uv sync --extra ocr --extra detector-local
uv run vipi setup --ocr-mode balanced
uv run vipi scan image.png --ocr-mode balanced --output report.json
```

![Local mode uses pinned models. Cloud mode needs provider API keys and bills requests.](../assets/diagrams/vipi-modes.svg)

## Commands and options

`vipi setup` explicitly prepares pinned OCR weights and the selected local
decision/detector models. Without an OCR mode/model, it prepares all three local
OCR sizes and the default Clef-Flash decision model. `--ocr-mode` prepares one local
profile. Cloud setup downloads no weights and makes no billable request;
credentials are checked when scanning. Scanning never downloads models.

`vipi scan PATH [PATH ...]` scans static PNG/JPEG/WebP files and directories
recursively. With `--diff` and no paths, it scans the current directory's scope.
Without `--diff`, at least one path is required.

| Shared setup/scan option | Meaning and default |
| --- | --- |
| `--modus local|cloud` | Full execution mode. Default local; a direct cloud `--ocr-model` also infers cloud for compatibility. |
| `--ocr-mode speed|balanced|quality|fast` | Local profile; `quality` is the scan default and `fast` aliases `speed`. Setup without this option prepares all OCR sizes. |
| `--ocr-model ID` | Override OCR with `ppocr-v6`, `ppocr-v6-medium`, `ppocr-v6-small`, `ppocr-v6-tiny`, `google-cloud-vision`, `gpt-6-luna` or `mistral-ocr-4-1`. |
| `--ocr-provider google|openai|mistral` | Cloud OCR selection, default Google. Requires explicit `--modus cloud`; cannot be combined with `--ocr-model`. |
| `--decision-provider clef-flash|d1|jev|openai` | OCR review model. Default local quality: Clef-Flash; other local profiles: d1; cloud: OpenAI Decisions. |
| `--detector auto|jev|openai|wolf-defender|clef-flash|d1` | Injection detector. Default `auto` follows the decision provider. |
| `-h`, `--help` | Show root or command help and exit without preparing models. |

| Scan-only option | Meaning and default |
| --- | --- |
| `--diff REFERENCE` | Select committed images added/modified since the common ancestor of REFERENCE and HEAD. |
| `--exclude PATTERN` | Repeatable ordered filesystem exclusion; `!` re-includes matching paths. No user rules by default. |
| `--threshold 0–100` | Finding threshold. Default: the detector's calibrated value, 45 for `d1`, 8 for `clef-flash`, 40 for `wolf-defender` and 80 for `jev` and `openai` (ADR 0075, ADR 0077, ADR 0085). Equality is a finding. The report records the threshold used. |
| `--output FILE` | Also write an atomic JSON report, including findings or incomplete scans. |
| `--verbose` | Print each image's final OCR text. Off by default. |
| `--list-only` | Run input selection only and list the selected images; no models, providers or keys are used. Selected files have status `selected` and the report status is `listed`; exit 2 on selection errors, otherwise 0. |

Local/cloud choices must agree. Explicit cloud mode rejects `--ocr-mode`, and
local/cloud detector or decision providers cannot be mixed. A local explicit
OCR model does not change the profile's decision model. There is no provider
fallback. The text check receives the selected OCR text and any SVG source
reading. If it finds no injection in a regular cloud scan, the same detector
checks the whole image with the same policy and threshold. An image finding is
sufficient to mark the file. See
[recovery stages](ocr-recovery.md) for spatial retries and retained evidence.

```bash
uv run vipi scan label.png screenshot.jpg
uv run vipi scan ./images --verbose
uv run vipi scan ./images --ocr-mode speed
uv run vipi scan image.png --modus cloud --ocr-provider mistral --decision-provider jev
uv run vipi setup --ocr-mode balanced --detector wolf-defender
uv run vipi scan ./images --ocr-mode balanced --detector wolf-defender
```

## Credentials and local models

Environment variables take precedence over `.env` in the current directory.
All aliases are checked in the environment first; an explicitly empty provider
setting prevents fallback to the file. See [`.env.example`](../.env.example).

| Provider | Credential |
| --- | --- |
| Google OCR | `GOOGLE_CLOUD_API_KEY`, alias `GOOGLE_API_KEY` |
| OpenAI OCR/review/detection | `OPENAI_API_KEY` |
| Mistral OCR | `MISTRAL_API_KEY` |
| Jev review/detection | `TYPESAFE_API_KEY`, alias `JEV_API_KEY` |
| Clef-Flash/d1 | Prepared local weights and verified code; no inference API key |
| Wolf Defender | Prepared local weights; no key or Hugging Face login |

The `ocr` extra supplies local OCR and shared image operations. Local decision
models and Wolf Defender additionally need `detector-local`. Local PP-OCRv6 runs
through ONNX on CPU in the public scanner; decision models select available
CUDA, Apple MPS or CPU. Research scan configurations use the same OCR execution
path as the public scanner.
Cloud recovery can submit additional transformed images and make billable OCR
and decision requests. Reports retain actual usage and unknown costs as unknown.

The image check of a cloud scan sends the whole raster to Jev or GPT-6 Luna
through OpenAI Decisions. Jev accepts 280–1568 pixels per side, so VIPI scales
down or adds white padding where needed. OpenAI uses `detail: original` and VIPI
scales down inputs above 30,000 image patches. For SVGs it checks the safe
render; the source text is a separate text reading.

## Excluding images

Copy [`.vipiignore.example`](../.vipiignore.example) to `.vipiignore`. VIPI reads
it from the Git repository root, or the scanned directory/explicit file's parent
outside Git. `--exclude` rules follow file rules; the last matching rule wins.

```text
generated/
*.webp
!generated/reviewed.webp
```

Patterns use forward-slash paths relative to the rule root. Names without `/`
match a component at any depth; paths with `/` are rooted. A leading `/` anchors
a pattern, a trailing `/` includes directory contents, and `**` spans directories.
Blank lines and `#` comments are ignored. Ordered `!` rules re-include images
within the requested scope, but cannot override built-in exclusions. To select
only PNG files, use `*` followed by `!*.png`.

This is a supported subset, not full `.gitignore` syntax. Excluded paths and
their rules appear as skipped, not safe. To check rules without scanning, add
`--list-only`.

Diff scans read `.vipiignore` from the repository root of the `--diff`
reference, not from the worktree or the compared branch, so a branch cannot
exempt its own images; a rule change applies once it is on the base branch.
`--exclude` rules follow as usual. Each changed image is matched by its
committed path, and excluded images are listed individually
([ADR 0072](../adr-code/0072-exclusions-in-git-diff-scans.md)).

## Branch and PR scans

```bash
uv run vipi scan . --diff origin/main --output report.json
```

Selection compares the common ancestor with HEAD against HEAD, then reads full
committed image bytes from Git objects. Uncommitted edits and untracked files
do not affect it. Paths restrict the selection. Deleted images are skipped;
renames are deletion plus addition. Image symlinks are errors. Missing refs or
insufficient history are errors; fetch the target and enough history first.

## GitHub Action

The Action lives in [EnXan/vipi-action](https://github.com/EnXan/vipi-action),
which documents its inputs, outputs and versions; see the
[workflow example](../README.md#github-actions). It installs a pinned
`vipi-scanner` release from PyPI, runs `vipi scan --list-only` and prepares
models only when images are selected; models are downloaded each run and not
cached ([ADR 0070](../adr-code/0070-action-setup-only-for-selected-images.md),
[ADR 0073](../adr-code/0073-github-action-in-its-own-repository.md)).

PR events scan images added or modified at the PR commit relative to the
actual base branch, with `paths` restricting scope; use checkout
`fetch-depth: 0`. PR scans take `.vipiignore` from the base branch; the
`exclude` input comes from the workflow file, which `pull_request` events read
from the PR. A detection returns 1 and an incomplete scan returns 2; upload
reports with `if: always()` to retain either.

## Limitations

- **Inputs:** static PNG, JPEG and WebP images and SVG files; extensions are
  matched case-insensitively and animated raster images are rejected. Local scans
  accept up to 40 megapixels; cloud scans follow the provider's limits. `.svgz`
  is not supported.
- **Image metadata:** see [Image metadata](#image-metadata). Values Pillow
  cannot parse leave the scan incomplete instead of being skipped. Not read:
  ICC profiles, thumbnails, C2PA manifests and other binary values, and text
  in formats VIPI does not accept.
- **QR codes and barcodes:** see [QR codes and barcodes](#qr-codes-and-barcodes).
  Codes too small, blurred or damaged to decode are counted, not checked.
- **SVG:** see [SVG files](#svg-files). The renderer (resvg) draws neither
  `<foreignObject>`, embedded fonts, animation nor text inside embedded SVG
  images, and ignores dark-mode `@media` rules; text in them is covered by the
  source reading, shapes and images shown only there are not. Base64 strings
  in the source text are decoded like base64 in OCR text (ADR 0079); binary
  payloads such as C2PA manifests stay in the text unchanged. Not covered in
  the source reading: text stored reversed behind a bidi override,
  variation-selector smuggling, homoglyphs and text scattered one glyph per
  element; all but the second are drawn, so OCR can catch them. The cases are
  listed in `tests/svg_cases.py`.
- **Other files:** unsupported files in scanned folders or diffs are skipped and
  listed in the report; an unsupported file named explicitly is an error.
- **Scores:** thresholds are operating points and `injection_probability` is not a
  calibrated attack probability. Scores are not comparable across detectors: the
  local decision models score injections far lower than the cloud detectors, so
  their default thresholds are lower. `no_injection_detected` means the detector
  stayed below the threshold on the final OCR text, the SVG source or metadata
  text and the barcode payloads; it does not prove the image
  is safe, and it does not say whether OCR missed readable text.
- **Cost:** cloud scans can make additional billable requests when OCR is
  unclear and the image is reviewed or read again.

## Image metadata

For PNG, JPEG and WebP files, the text in the file's metadata is a second
reading next to the OCR text ([ADR 0083](../adr-code/0083-image-metadata-reading.md)).
Applications, agents and tools such as `exiftool` read it, while OCR sees only
pixels. The reading holds one `field: value` line per text value:

- PNG `tEXt`, `zTXt` and `iTXt` chunks, including chunks after the image data;
- JPEG comments (`COM`);
- XMP (PNG `XML:com.adobe.xmp`, JPEG standard and extended XMP, WebP): element
  text, attribute values except `xmlns`, `rdf:parseType` and `xml:lang`,
  comments and processing instructions except `xpacket`;
- EXIF text in IFD0, the Exif IFD and the GPS IFD, including `UserComment`
  and the GPS method and area fields with their character code and the UTF-16
  `XP*` fields; byte values count only when they decode as UTF-8 text;
- IPTC application record values in JPEG files.

Numbers, dates stored as numbers and binary values are not text. Unicode tag
characters are decoded and other invisible characters are removed, as for the
SVG source text. An injection in the metadata is a finding. Metadata that
cannot be parsed (for example EXIF data Pillow ignores, or malformed XMP)
leaves the scan incomplete: the file is an error (exit 2), and its verdict is
`injection_detected` when a reading is detected, otherwise `null`.

The file record gains a `metadata` object: `fields` (the field names found),
`characters`, `invisible_characters`, `unreadable` (the groups that could not
be parsed) and `scores`, the highest score per reading (`ocr`,
`image_metadata`). `--verbose` prints the metadata text after the OCR text.

## QR codes and barcodes

VIPI decodes every QR code and barcode in the scanned raster with zxing-cpp
and checks the payloads as a further reading
([ADR 0084](../adr-code/0084-barcode-reading.md)). The raster is the one OCR
reads: the decoded image, or the safe render of an SVG. Phones, scanners and
agents act on a payload that OCR cannot read. The reading holds one
`Format: text` line per code, for every format zxing-cpp reads (for example
QR Code, Micro QR, Data Matrix, Aztec, PDF417, Code 128, Code 39, EAN/UPC).
Decoded URLs are checked as text and never fetched. Binary payloads are not
text and are only counted. Invisible characters are handled as for the SVG
source text.

An injection in a payload is a finding. A code that is found but cannot be
decoded is ignored. A failure of the decoder itself leaves the scan
incomplete (exit 2, verdict `null` unless a reading is detected).

The file record gains a `barcodes` object: `formats` (one entry per decoded
code), `characters`, `invisible_characters`, `binary` and `scores`, the highest score per reading (`ocr`, `barcode`). `--verbose`
prints the payloads after the OCR text.

## SVG files

An SVG file is checked in two readings ([ADR 0078](../adr-code/0078-svg-inputs.md)):

- **Rendered:** VIPI renders the file with resvg and runs the raster through
  the same OCR as any image. Before rendering it removes every `href` that does
  not point into the document (`#…`) or to a `data:` URI, so no local file or
  network resource is drawn; scripts never run. The size comes from
  `width`/`height`, else the `viewBox`, else 100×100 user units; the image is
  drawn at 2× on white, scaled down to fit 40 megapixels.
- **Source text:** what a model sees when it reads the file as text: all text
  and CDATA in every element and namespace, comments, processing instructions,
  internal entity values, and attribute values except geometry, paint and
  reference attributes (those count only when they hold prose). `data:` URIs
  with a text or SVG media type are decoded. Unicode tag characters are decoded
  and zero-width, bidirectional and other invisible characters are removed
  before the detector sees the text.

An injection in either reading is a finding, whether or not it is visible. An
SVG with an embedded font (`@font-face` with a `data:` font, or SVG fonts) can
show text that the renderer does not draw, so the scan is incomplete: the file
is an error (exit 2), and its verdict is `injection_detected` when a reading is
detected, otherwise `null`. Malformed files and
files whose root is not `<svg>` are errors. DTDs and external entities are
never loaded, and entity expansion is bounded by the XML parser.

The file record gains an `svg` object: `intrinsic_size`, `size_source`
(`attributes`, `viewbox` or `default`), `render_size`, `scale`,
`removed_references`, `features` (`animation`, `embedded_font`,
`embedded_image`, `external_reference`, `foreign_object`,
`invisible_characters`, `script`), `invisible_characters`,
`source_text_characters` and `scores`, the highest score per reading (`ocr`,
`svg_source`). The run artifacts keep `input.svg` next to the rendered
`input.png`; `--verbose` prints the source text after the OCR text.

## Results and storage

| Exit code | Meaning |
| --- | --- |
| `0` | All selected images completed without `injection_detected`, including an empty selection and images without text |
| `1` | At least one `injection_detected` and all images completed |
| `2` | Invalid settings, missing runtime/models/keys, detector or provider failure, refusal, missing threshold, unreadable input or interruption |

Errors take precedence. Each file record has a `verdict`: `injection_detected`,
`no_injection_detected`, or `null` when a required detector check did not
complete (the file is then an error). `injection_probability` is the highest
native detector probability over all completed checks, reported next to the
`threshold` that decides the verdict; it is `null` when the final OCR text, the
SVG source or metadata text and the barcode payloads are empty and there is no
completed image check.
Local scans without a text reading are `no_injection_detected`. Cloud scans
without a text reading go straight to the image check after OCR.
Very long text is checked in chunks. d1 and Clef-Flash also check text of more
than 80 words in overlapping windows of whole sentences or lines, up to 80
words each, one about every 40 words (ADR 0077). Every detector also checks
the plaintext of base64 strings in the text, repaired for typical OCR errors,
when it reads as text (ADR 0079). Any check at or above the
threshold detects; all checks below it do not. The report `schema_version`
is 2.

Image checks appear as `image_check` on the file record with `status`, `verdict`,
`probability` and `submitted_image_size` when available. They count toward
`detection_cost`. A required image check that fails leaves the scan incomplete.
The report has `evidence_scope: final_ocr_with_image_check` for a cloud scan
with Jev or OpenAI as detector.

`ocr_incomplete` says whether readable image text is missing from the final OCR
text: `true`, `false`, or `null` when it was not judged. When recovery kept the
first reading, the visual review's existing completeness answer is reused
(`missing_text` is `true`; `complete` with sufficient detail is `false`;
anything else `null`). When recovery changed the final text, the same question
is asked once more about the final text, which adds one visual-review call.
Clear OCR needs no review, so the value is `null` and no call is added. If that
extra call fails, the value is `null` and the reason is kept in the run's
`selection.ocr_incomplete_error`. The summary counts `ocr_incomplete: true`
files; exit codes ignore the flag.
Explicit unsupported files are errors. Directory scans record unsupported files
as skipped and exclude `.git`, `.venv*`, `node_modules`, `__pycache__`, directory
symlinks and VIPI's cache. Image symlinks are errors.

Reports include resolved models, hashes, runtime identities, threshold, timing,
usage/cost evidence, artifact paths, skipped/error/not-scanned inputs and diff
commit IDs. `--output` cannot overwrite a selected image. Terminal output uses
a live progress display when supported; redirected output uses a compact brand.

| Platform | Default cache |
| --- | --- |
| macOS | `~/Library/Caches/vipi/` |
| Linux | `~/.cache/vipi/` |
| Windows | `%LOCALAPPDATA%/vipi/` |

`XDG_CACHE_HOME/vipi/` overrides these defaults. OCR files live in `ocr/`, local
decision models in `decisions/clef-flash` and `decisions/d1`, Wolf Defender in
`wolf-defender/`, and persistent input/variant/result artifacts in `runs/`.

## Platform validation status

Earlier CLI versions were tested on macOS, Linux and Windows on 2026-10-24.
That does not validate the current trained recovery models on every platform.
Current unit/integration/research checks and package smoke tests use fixtures;
CI runs on Ubuntu. The recorded trained Tiny+d1 run was on Apple MPS; see
[the recovery measurement boundary](ocr-recovery.md#measurement-and-costs).
Fresh Clef-Flash quality on CUDA or CPU, cloud-provider and Windows/Linux inference require separate
validation. A platform claim should record a fresh install, model setup, image
and Git-diff scan, JSON output, exit codes and the actual model/provider.
