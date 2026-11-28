# ADR 0093 — Fixture editor with server-written hidden channels

Status: accepted for implementation and review, 2026-11-27. Refs #125.

## Context

Issue #125 asks for a research UI that builds repeatable test images with
inert markers, exports image and expectations, and checks them against VIPI.
The user widened the scope: every channel VIPI reads (visible text, metadata,
transparency views, codes, pixel steganography, SVG source) needs a
counterpart that can be created and understood entirely in the UI, including
invisible ones. This ADR covers the editor and one writer per channel:
metadata (ADR 0083), QR codes and barcodes (ADR 0084), transparency views
(ADR 0085), OpenStego legacy and RandomLSB (ADR 0088, 0089), declared PNG LSB
layouts and their statistics (ADR 0090, 0091), SVG source text (ADR 0078),
and image-scaling attacks (`image_scaling` in the vocabulary; the dataset
already has Anamorpher cases, ADR 0052).

A browser canvas cannot produce these channels: `toBlob` writes no metadata,
and canvas pixels are premultiplied, so colour values under transparent pixels
are lost. Pixel payloads would also not survive later edits.

## Decision

- **Two stages.** The Editor tab composes the visible layers on a canvas
  (text with font, size, colour, opacity, rotation, skew, blur, mirror,
  base64 drawing; QR codes and barcodes; background colour or image). The
  server writes the hidden layers into that PNG in `research/fixtures/` (no
  Flask import), so tests can use the encoder without the UI. Code modules
  come from zxing-cpp, the library VIPI decodes with, one pixel per module;
  the browser scales and colours them.
- **Write order.** Scaling payloads, then transparency (RGBA), then pixel
  steganography (needs an RGB PNG, so it is skipped next to a transparency
  layer), then metadata when saving. SVG output embeds the composition as a
  `data:` PNG and adds the SVG layers; raster-only layers are skipped.
- **Every channel is a layer.** Hidden layers sit in the same layer list as
  visible ones and are edited in the same properties panel; their value can be
  encoded as base64, Unicode tag characters, zero-width separators or
  homoglyphs, and the written form is shown with invisible characters made
  visible.
- **Read-back.** After each change (debounced) the server writes the file and
  reads it with VIPI's own readers: `read_metadata`, `read_codes` on the white
  composite (or the SVG render), `read_openstego`, `read_lsb` with the
  layer's layout, `read_views`, and `read_svg`. Each layer shows `read`,
  `changed` (VIPI reads something else), `missing`, or `skipped` (the format
  cannot carry it). Scaling and transparency layers report how many pixels
  come out as intended. The page shows each reading, the normalized detector
  input and the low-bit statistics. OCR is only checked by a full scan.
- **Transparency.** For each text pixel the writer solves the compositing
  equations: *on black* keeps the white composite (one alpha per pixel, from
  the channel that must darken most), *alpha dropped* writes fully
  transparent pixels with the text colour (invisible on white only). Text that
  overlaps dark composition cannot be darker than it, which the read-back
  shows as a partial count.
- **Steganography.** OpenStego legacy writes the v1 header, file name and text
  into the low bit of every RGB sample in file order; RandomLSB v2 subclasses
  VIPI's position reader and writes where it reads (8 empty algorithm bytes);
  PNG LSB inverts the zsteg sample order and bit assembly and ends the text
  with a NUL so the printable run stops. Its 256-byte preview is the reader's
  limit (ADR 0090), not a new one.
- **SVG.** Placements cover what the source reading collects: comment,
  `<title>`, `<desc>`, `<metadata>`, a non-structural attribute, a `data:`
  text URI, and `<text>` visible, at opacity 0, `display:none`, outside the
  canvas, at 0.1 px or in the background colour.
- **Metadata containers.** PNG text chunks (tEXt/zTXt/iTXt, optionally after
  the pixel data), XMP (PNG iTXt, JPEG APP1, WebP), EXIF (IFD0 text, XP*,
  UserComment, GPS text), JPEG COM segments, IPTC application record in a
  Photoshop APP13 segment. Format limits come from the specifications: PNG
  keywords 1–79 Latin-1 characters, 65533 bytes per JPEG segment, 32767 bytes
  per IPTC dataset. Setting one EXIF tag from two layers is rejected, because
  a tag exists once per IFD.
- **Scaling attacks.** A scaling layer writes text into exactly the pixels a
  resizer samples when it shrinks the image to a chosen width: Pillow nearest,
  OpenCV nearest or OpenCV bilinear without antialiasing. The output size uses
  the aspect ratio rounded half up, as in the browser. Nearest positions are
  read from the resizer itself by resizing an index ramp; bilinear uses
  OpenCV's half-pixel mapping and writes both neighbours, and a test checks the
  weights against OpenCV. The read-back downscales the final file and counts
  the payload pixels that come out exactly. VIPI itself scans the full-size
  image and shrinks only with Lanczos for cloud image checks, so this is a
  counterpart for downstream pipelines, not a VIPI reading.
- **Views.** The canvas zooms (steps, ⌘/Ctrl + wheel, fit, 100 %, pixelated
  from 200 %). Once a change is written, the canvas shows the written file (an
  SVG's render), so pixel layers and JPEG loss are visible. *On black* and
  *Alpha dropped* show VIPI's transparency views, *Bit plane* one bit of one
  channel, and *Downscaled* the file after any available resizer (Pillow nearest, bilinear, bicubic, Lanczos;
  OpenCV nearest, bilinear, area when OpenCV is installed) at a chosen width.
- **Output encoding.** WebP is written lossless and `exact` (colours under
  transparent pixels kept) so pixel layers survive;
  JPEG stays lossy (quality 95) and the read-back reports what survives.
  ASCII EXIF tags receive UTF-8 bytes, as exiftool writes them.
- **Remove brush.** To replace text in a screenshot, the user paints over it;
  the server fills each connected painted area on the background image only
  (`research/fixtures/heal.py`). Three methods each predict the 4 px band
  around the area, and the best one fills it: the band's most frequent
  colour (taken whenever it fits within a mean squared error of 4, so flat
  interface backgrounds stay exact), a quadratic colour surface fitted with
  one outlier-dropping refit (fades, gradients, vignettes), or a copy of the
  place nearby whose surroundings match the band best, by masked OpenCV
  template matching (patterns, textures, fades along one axis). Telea
  inpainting was tried first and rejected: it blurred text on flat
  backgrounds. A flat-colour-only fill came next and left visible blocks on
  fades. The copy search covers three times the area's size around it (at
  least 64 px): searching a whole 2400x1600 image took 0.6 s per area, too
  slow for a brush that refills on every stroke; with the limit six
  300x40 areas take 1.3 s. Tests: flat exact, vertical fade within 1 level,
  diagonal gradient within 2, a checker pattern exact. Photos with detailed
  content can still show seams. Without a background image the brush works
  on the background colour.
- **Text selection.** When a background image is added, the workbench finds
  its text lines with the text detection of the tiny local OCR model
  (PP-OCRv6 det tiny, 1.7 MB) on one thread, without recognition
  (`research/fixtures/text_boxes.py`, cached per image). Measured on an
  M-series Mac: 0.7 s to load once, 121-357 ms per image from 480x480 to
  1280x1280. When lines were found, a pill in the bottom right corner of the canvas
  (like Live Text) shows them as outlines; a click or a drag across lines
  adds their padded polygons (3 px) to *Removed areas*, filled like brush
  strokes. The brush option *Snap to text* turns a stroke touching lines
  into those lines. Lines, not words, because words would need recognition.
  Without the tiny model there is no pill, only a hint to run
  `vipi setup --ocr-mode speed`; nothing is downloaded. Automatic removal
  stays out: the user picks what disappears.
  Strokes are stored in a *Removed areas* layer in the recipe, so undo,
  delete and reopening recompute the same result. Automatic text detection
  was considered and not chosen: the user wants to decide what disappears.
- **Scan.** *Scan with VIPI* sends the written file to the workbench's scan
  service, the same `vipi scan` pipeline as the *Scan an image* page. The
  service writes SVG bytes to a temporary `.svg` file, because VIPI recognises
  SVG by its path, passes the document's PNG LSB layouts as `lsb_layouts`, and
  returns the score per reading next to the verdict. The editor compares the
  verdict with the label and the recognized text with the expected words.
  The scan job reports its phase (reading, checking) and counts OCR passes
  (summed over the scan's OCR runs) and started detection checks. Both pages
  fill the scan button (`static/scan-progress.js`) by time: each phase moves
  against how long it took in earlier scans with the same settings in this
  browser (stored in `localStorage`, the newest scan weighted half), eases
  towards its end and never shows complete before the phase ends. The counts
  were tried as the bar's measure first and rejected: OCR also selects and
  assesses its text without reporting counts, so with one pass the bar
  jumped to almost full and then stood still for up to 25 s. They stay as
  text in the button. The bar is an estimate, so it can end early or wait
  near the end; it never moves back.
- **Notifications.** Messages and errors of every workbench page appear as
  notifications at the top centre (`static/toast.js`), styled like shadcn's
  toasts in the brand's monochrome palette. Errors stay 8 s, other messages
  4 s, and hovering keeps them open. The editor's steady writing state
  (*Up to date.*) stays under the canvas.
- **Fixture.** Export writes the image and `<name>.fixture.json`: SHA-256,
  label, obfuscation labels, expected text per reading (`ocr`, `decoded`,
  `barcode`, `image_metadata`, `openstego`, `openstego_random_lsb`, `png_lsb`,
  `svg_source`, `image_scaling`, `transparency`), per-channel read-back and
  the recipe. Opening the JSON
  restores the editable document. Obfuscation labels that follow from the
  layers are set automatically and cannot be unset while the layer causes
  them. Three come from thresholds, which are application heuristics, not
  model requirements: `low_contrast` below a WCAG contrast of 3:1 (minimum
  for large text) between the text colour and the average background behind
  the text; `small_font` at 12 px or less (the dataset renderers use 9 and
  11 px against 19 px); `high_transparency` at opacity 0.5 or less, and for
  every *Hidden in transparency* layer. Colour and opacity are judged
  separately, so a faded dark text is `high_transparency`, not also
  `low_contrast`. `split_text` and `flowchart` stay manual, because several
  text layers do not imply a split payload.
- **Text tool.** **T** selects a text cursor instead of adding a layer at the
  centre: a click edits the text under it or opens an empty text box at that
  point, as in image editors. A text left empty is dropped without an undo
  step.

## Alternatives and consequences

Rendering everything server-side would keep one renderer but lose direct
manipulation. Writing metadata in the browser would need a second set of
container writers in JavaScript and could not handle later pixel channels.
The chosen split keeps one renderer per stage; the exported image, not the
recipe, is the fixture, so system-font differences only affect re-editing.

Writing with Pillow showed that its PNG writer drops an `Exif` object whose
first IFD is empty (a Pillow behaviour); the encoder passes EXIF as bytes. The
read-back exposed three VIPI reader issues, fixed in ADR 0094.

A scaling payload written directly into the sampled pixels is a visible dot
pattern on flat backgrounds; Anamorpher's optimised embedding hides it better.
The direct form is exact for every attackable resizer without an external
checkout, and busy or dark backgrounds hide it the same way.

The steganography writers mirror VIPI's readers, so a shared misreading of
the formats would pass the read-back. Fixtures meant as regression evidence
for OpenStego or zsteg layouts should be checked once with those tools.

## Validation boundary

Unit tests write every field of every container in every format that carries
it and read it back with VIPI's reader, check scaling payloads per resizer in
PNG and WebP, their loss in JPEG, the averaging of antialiased resizers and
the OpenCV bilinear weights, codes in six formats, both transparency modes in
PNG and WebP, all steganography methods with several layouts and depths and
their format conflicts, every SVG placement, and every view, plus PNG late chunks, duplicate
keywords, JPEG decodability, validation errors and the HTTP routes. The editor
was exercised in Chromium: composing, dragging, zoom, undo, format switch,
encodings, scaling layers and the downscaled view, export and reopening a
fixture. The encoder and reader are both ours; whether
other tools (exiftool, Windows Explorer, browsers) read these fields the same
way is unverified. Safari and Firefox are untested; canvas `filter` (blur)
requires a recent browser.
