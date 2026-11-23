# ADR 0083: Image metadata as a detector reading

Status: Accepted for implementation and review, 2026-11-22 (issue #121).
Amends the verdict scope of
[ADR 0071](0071-scan-verdict-and-final-ocr-completeness.md) as ADR 0078 did
for SVG: "final OCR text" becomes "final OCR text and, for raster images, the
metadata text".

## Context and sources

VIPI checked only pixels of PNG, JPEG and WebP files. Their metadata (EXIF,
XMP, IPTC, PNG text chunks, JPEG comments) is invisible in the image, but
applications and agents read it. Examples are alt-text generation, tools such as
`exiftool` whose output reaches a model, and agents that open the file. An
instruction stored there reached such a model without a scan finding. Issue
#86 listed this as an idea; issue #121 records the agreed scope.

Agreed with the maintainer on 2026-11-22:

- all text values, not a list of free-text fields, because an allowlist misses
  custom XMP or PNG keys (the attribute-cloaking lesson of ADR 0078);
- metadata that cannot be read leaves the scan incomplete;
- `--image-only` is removed first (ADR 0082), so every scan has OCR and the
  reading needs no special case.

Local probes with Pillow 11.3 on 2026-11-22:

- PNG text chunks after the pixel data appear in `Image.text` (which loads the
  image) but not in `Image.info`.
- `Image.getexif()` returns an empty result for EXIF it cannot parse instead
  of raising.
- JPEG `Image.info["xmp"]` holds only the standard XMP packet; extended XMP
  segments are in `Image.applist`.

The repository's 26 images and the 554 dataset images carry no text metadata
(11 dataset images have an ICC profile), so the dataset cannot measure this
reading.

## Decision

- **Reading.** For every raster input, `vipi.image_metadata.read_metadata`
  builds one reading of `field: value` lines, checked like the OCR text
  (evidence kind `image_metadata`, scope `final_ocr_and_image_metadata`).
  Identical texts are checked once. Any check at or above the threshold
  detects. SVG inputs keep their source reading (ADR 0078) and have no
  metadata reading.
- **Sources.**
  - PNG `tEXt`/`zTXt`/`iTXt`, read through `Image.text` so that chunks after
    the image data count;
  - JPEG `COM` segments;
  - XMP: PNG `XML:com.adobe.xmp`, JPEG standard and extended XMP (extended
    parts joined in offset order), WebP. Element text, attribute values except
    `xmlns*`, `rdf:parseType` and `xml:lang`, comments, and processing
    instructions except `xpacket`, parsed with `pyexpat` as in ADR 0078;
  - EXIF text in IFD0, the Exif IFD and the GPS IFD. `UserComment` and the GPS
    method and area fields are decoded by their 8-byte character code, the
    `XP*` fields as UTF-16LE;
  - IPTC application record (2:xx) in JPEG.
- **Text only.** Numbers and rationals are skipped. Byte values count only when
  they decode as UTF-8 without control characters, so maker notes, thumbnails
  and binary records are left out. ICC profiles and C2PA/JUMBF data are not
  read. Unicode tag characters are decoded and other invisible characters
  removed with the SVG normalisation; base64 in the reading is decoded under
  ADR 0079.
- **Unreadable metadata.** A parser failure per group (text chunks, JPEG
  comments, XMP, EXIF, IPTC), or EXIF bytes that Pillow parses to nothing,
  adds an incomplete reason. The other groups are still read. As for SVG
  embedded fonts, the file is then an error (exit 2) with verdict
  `injection_detected` when a reading is detected, otherwise `null`.
- **Report.** The file record gains `metadata` with `fields`, `characters`,
  `invisible_characters`, `unreadable` and the highest score per reading
  (`ocr`, `image_metadata`). `--verbose` prints the metadata text. The
  evidence in the run artifacts holds the reading text.

## Alternatives considered

- **A list of free-text fields** (`ImageDescription`, `UserComment`,
  `dc:description`, ...). Fewer characters, but custom keys and attributes
  would pass unchecked.
- **`exiftool` as the reader.** Reads more formats and maker notes, but adds a
  Perl runtime dependency to every install.
- **One reading per field.** Better attribution in the report, but one detector
  call per field; field names already appear in the line prefix.
- **Skip unreadable metadata and only report it.** A crafted EXIF block that
  Pillow ignores but other readers parse would then pass as clean.
- **Strip metadata before scanning** (the usual hardening advice). It protects
  a pipeline that VIPI does not control and hides the evidence.

## Consequences

- A raster image with metadata costs one more detector check (more for long
  text in chunks or windows); one without metadata costs nothing more.
  `read_metadata` opens and loads the file a second time.
- Scans of PNG, JPEG and WebP files can now find injections OCR cannot see,
  and files with unparsable metadata become incomplete. This changes scan
  results with default inputs: released as 0.17.0, and pinning it in the
  vipi-action calls for an Action major version under ADR 0076, as for SVG
  support (ADR 0078).
- Research evaluations (`research.evaluate`, `detect-text`, the OCR
  benchmark) build their own evidence and do not include the reading; the
  dataset has no text metadata.
- Not covered: text in metadata formats Pillow does not expose (for example
  maker-note internals and TIFF-only tags), ICC profile descriptions, C2PA
  manifests, and homoglyphs.

## Validation boundary

Unit tests cover every source, extended XMP order, chunks after the image
data, binary values, invisible characters and unreadable EXIF and XMP.
Integration tests run full scans with fake OCR and detector, including
incomplete scans and detection despite unreadable metadata.

A synthetic corpus written for this change (not retained) was scored on the
metadata reading alone with the calibrated default thresholds, on
2026-11-22:

- 13 benign images imitating common metadata: a macOS screenshot, iPhone and
  Pixel photos, a Photoshop export with XMP history, Lightroom rights and
  IPTC captions, stock licence text with "do not use" and "delete" wording,
  GIMP, ImageMagick (including a hex EXIF profile), Stable Diffusion
  `parameters`, a ComfyUI workflow, an AI image description, a screenshot tool
  title and Windows `XP*` tags.
- 14 attack images: two payloads in a PNG chunk before and after the image
  data, EXIF `UserComment`/`XPComment`/`ImageDescription`, XMP element and
  custom attribute, IPTC caption, JPEG comment, inside a Stable Diffusion
  prompt and a ComfyUI JSON, as Unicode tag characters, as base64, and one
  camouflaged request in an XMP description.

| Detector (threshold) | Benign flagged | Attacks detected |
| --- | --- | --- |
| d1 (0.45) | 0/13 (max 0.19, ComfyUI) | 14/14 (min 0.71, camouflaged) |
| Prompt Guard (0.80) | 0/13 (max 0.002) | 7/14 |

Prompt Guard missed every case with the second payload (a `curl … | sh`
request) and the camouflaged one, wherever it was stored. That is the
detector's known weakness (issue #105), not missing extraction: d1 detected
the same readings. Clef-Flash and the cloud detectors were not measured. The
corpus is small and was written by the same author as the payloads; it shows
that each source reaches the detector and gives no false-positive or recall
rate for real images. Real images with metadata remain to be measured.
