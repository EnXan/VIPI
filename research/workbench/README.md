# Research workbench

A local Flask app with four pages: scan one image, evaluate a scan
configuration against the saved baseline, contribute to the dataset, and build
test fixtures in the editor. It imports
`vipi`; it is not included in the product wheel.

## Start

Use the [development environment](../../docs/development.md), then run from the
repository root:

```bash
uv run python -m research.download
uv run vipi setup
uv run python -m research.workbench serve
```

Open [localhost:8000](http://127.0.0.1:8000). `vipi setup` prepares the local
models; cloud settings need the provider API keys in the environment or
`.env` instead (see the [CLI guide](../../docs/cli.md)).

## Settings

Scan and Evaluate use the options of `vipi scan` and nothing else:

- **Run on**: this computer (free, needs the local models) or the cloud (paid
  API calls).
- **Text recognition**: Speed, Balanced or Quality locally; Google Cloud
  Vision, OpenAI or Mistral in the cloud.
- **Injection detector**: locally d1 for Speed and Balanced and Clef-Flash
  for Quality (these also review OCR), or Wolf Defender for every local OCR
  size (detection only; review stays d1 or Clef-Flash); in the cloud
  OpenAI Luna (the product default) or Jev.
- **Threshold** (Scan only): flag at a detector score of at least this value.
  It starts at the chosen detector's product default: 45 for d1, 8 for
  Clef-Flash, 80 for the others.

The default is the product default: local, Quality, Clef-Flash, threshold 8.

## Scan an image

Choose, drop or paste an image and press **Scan image**. While it runs, the
button fills from the left with a moving sheen. It moves by time, against how
long reading and checking took in your earlier scans with the same settings,
so it becomes accurate after a scan or two; the OCR passes and detection
checks the scan reports are shown next to it. Messages and errors on every page appear as notifications
at the top centre. The result shows the
verdict (prompt injection detected, not detected, or no result), the injection probability, whether OCR may have missed text,
time and API cost, the recognized text and, under **OCR passes**, every image
variant the scanner read with its text.

## Evaluate

Choose the settings and the images:

- **Development split** (450 images): use for every comparison.
- **Test split** (104 images): only once, to confirm a change before a default
  changes. Starting it needs a confirmation.

**Reuse identical results** is on by default: for an identical image, an
earlier OCR result is reused when OCR settings and OCR code match, and its
detection as well when detector, settings, product code and packages also
match ([ADR 0058](../../adr-code/0058-reuse-ocr-across-runs.md)). Turn it off
to scan every image from scratch.

Before you start, a summary shows the **Baseline** (none, up to date or out of
date with the changed fields), the **Work** (how many images need OCR and
detection after reuse) and the **Cost** (free locally; otherwise which paid
calls remain).

A run goes through every image of the split, shows its progress and can be stopped and resumed. When it is complete,
the page shows OCR word coverage, fully read images, attacks detected, benign
images detected, detection accuracy and the `ocr_incomplete` counts, each with the change against the
baseline, the number of images whose result changed, and results per content
type. **Save as baseline** stores the run in `research/baselines/`; commit that
file. **Report** and **Comparison** download the Markdown reports.

The page runs the same steps as `python -m research.evaluate`; the
[evaluation guide](../evaluate/README.md) defines the metrics. Several
evaluations can run at once; one scan runs at a time. Before another local
evaluation starts or resumes while a local one is running, the page warns that
the runs compete for CPU, memory and GPU and asks to confirm; cloud runs start
without a warning. A run that overlapped with others says so in its report and
on the page, because its time and resource figures include their load
([ADR 0066](../../adr-code/0066-parallel-evaluations.md)). Keep the server and
computer running for long runs; after a restart, open the run and resume it.

## Dataset

The **Dataset** tab edits `research/dataset/` in three steps:

1. **Add images**: choose or drop images and give label, content type, source
   name, license and provenance. Each new image gets an unreviewed entry;
   images already in the dataset are skipped.
2. **Label**: the list then shows only your changes; fill in each entry and
   mark it reviewed ([curation guide](../curation/README.md#label-in-the-workbench)).
3. **Submit changes**: shows what would be sent and any conflict, then opens a
   pull request on Hugging Face after you confirm. It needs a one-time
   `uv run hf auth login` in a terminal.

The [contribution guide](../README.md#add-images) describes the whole flow.

## Editor

The **Editor** tab builds a test image with known content in every channel
VIPI reads, shows what VIPI reads back, and exports it as a fixture
([ADR 0093](../../adr-code/0093-fixture-editor.md)). Use inert markers (new layers
start with one that only asks for a canary string) and benign controls only.

- **Document bar:** file name and canvas size (with an image, *Original*
  returns to its own size); background colour, or **Add image** to use an
  image (the canvas takes its size); output format (PNG, JPEG, WebP, SVG);
  and the **ground-truth label** (injection, benign …), which only records
  what VIPI should decide in the fixture JSON and does not change the image.
- **Layers** (tool bar on the left, one per channel):

  | Tool | Layer | VIPI reads it as |
  | --- | --- | --- |
  | **T** | Text drawn into the image: font (Geist, Geist Mono and the common system fonts installed on this computer), size, colour, opacity, rotation, skew, blur, mirror, base64 | OCR (full scan), base64 decoding |
  | **C** | QR code or barcode (QR, Micro QR, rMQR, Data Matrix, Aztec, PDF417, MaxiCode, Code 128/39/93, EAN, UPC, ITF, DataBar …), module size, colours, opacity | Barcode reading |
  | **M** | Metadata field: PNG text chunks (optionally after the pixel data), XMP, EXIF, JPEG comments, IPTC; value plain, base64, Unicode tag characters, zero-width spaces or homoglyphs | Metadata reading |
  | **S** | Scaling attack: text only in the pixels Pillow nearest, OpenCV nearest or OpenCV bilinear samples when shrinking to a target width | Not read by VIPI; for pipelines that downscale |
  | **A** | Hidden in transparency: text that shows on a black background, or when the alpha channel is dropped, while the white view stays unchanged | Transparency views (OCR in a full scan) |
  | **P** | Pixel steganography: OpenStego legacy, OpenStego RandomLSB (bit depth) or a PNG LSB layout in zsteg notation | OpenStego readings; PNG LSB when the scan declares the layout (`--lsb-layout`) |
  | **V** | SVG source text: comment, `<title>`, `<desc>`, `<metadata>`, `aria-label`, `data:` URI, or a `<text>` element that is visible, transparent, hidden, outside the canvas, 0.1 px or in the background colour | SVG source reading, OCR of the render |

  **T** is a text cursor: click in the image to type a new text there (or
  click an existing text to edit it); Cmd/Ctrl+Enter or a click elsewhere
  finishes, Esc discards an empty one. The other tools add their layer at
  the centre. The eye in front of every layer hides it: a hidden layer stays
  in the document (and the fixture recipe) but is not drawn or written. Drag visible layers on the canvas or nudge them with the arrow
  keys.
  **Remove brush** (**J**, below the layer tools): paint over text in the
  background image, for example a screenshot, and it is filled from its
  surroundings: flat backgrounds get their exact colour, fades and gradients
  are continued smoothly, and patterns are copied from a matching place
  nearby, so your own text can go there. Detailed photos can show seams;
  paint those in smaller pieces. **[** and
  **]** or the *Brush* field change the size, Esc ends. Every stroke is one
  undo step; the strokes form the *Removed areas* layer, and deleting it
  restores the original image. Only the background changes; without a
  background image the brush paints with the background colour. Text and
  other layers lie above it, so delete or edit those instead.
  **Select text:** after you add a background image, the workbench looks for
  its text lines (the tiny local OCR model's detection, a fraction of a
  second, nothing is read). A pill in the bottom right corner of the canvas offers
  *Select text · n lines*: the lines get outlines, and a click on one or a
  drag across several removes them exactly. With *Snap to text* in the brush
  options, a stroke that touches a line removes the whole line. Without the
  tiny model (`vipi setup --ocr-mode speed`) the pill does not appear.
  System fonts are offered only when installed, because the canvas would
  otherwise draw a fallback; a fixture that names a font missing here shows it
  as *not installed*, and the exported image is what was actually drawn.
  Double-click a text layer to edit its text in place (Enter adds a line,
  ⌘/Ctrl + Enter or a click elsewhere keeps it, Escape discards it);
  double-click a code to jump to its content field. Number
  fields (size, position, width, opacity …) change when you drag left or right
  on the field or its label, as in Photoshop: hold Shift for steps of ten,
  Alt for tenths; a click still lets you type. One drag is one undo step. A layer
  the chosen format cannot carry is marked and not written (for example
  steganography outside PNG or next to a transparency layer).
- **Zoom:** **−**/**+**, **Fit** and **100%** above the canvas, or ⌘/Ctrl +
  mouse wheel; from 200 % pixels are drawn sharp.
- **Views:** **Original** shows the written file once a change is written (for
  SVG, the render OCR sees), so pixel layers and JPEG loss are visible. **On
  black** and **Alpha dropped** show the transparency views VIPI scans. **Bit
  plane** shows one bit of one colour channel, where steganography appears.
  **Downscaled** shows the file after a resizer of your choice at a target
  width (Pillow nearest, bilinear, bicubic, Lanczos as in VIPI's cloud check;
  OpenCV nearest, bilinear, area).
- **Read-back:** every non-text layer shows what VIPI's reader found after the
  last change: *read*, *read differently* (hover for what VIPI reads), *not
  read* or *not in this format*; scaling and transparency layers show how many
  pixels come out as intended. Select a layer to see under **In the file**
  exactly what VIPI reads from the written file, *What the detector gets*
  when VIPI normalizes invisible characters, and for pixel steganography the
  low-bit statistics (`--lsb-stats`). This checks that the content arrives,
  not whether VIPI detects it; that is **Scan with VIPI**.
- **Expected:** the visible text OCR should find, decoded text and the
  obfuscation labels. Those that follow from the layers are set
  automatically: italic, rotated, mirrored, skewed, blurred, base64 and
  homoglyph text, scaling and transparency layers, text with a contrast
  below 3:1 against the background behind it (`low_contrast`), 12 px or
  smaller (`small_font`) or at opacity 0.5 or less (`high_transparency`).
- **Scan with VIPI** (top right) runs the full `vipi scan` on the written
  file with the chosen settings, including the declared PNG LSB layouts of
  the document. **Scan result** shows the verdict, whether it matches the
  label (a benign fixture should not be detected), the score per reading
  (OCR, transparency views, metadata, codes, OpenStego, PNG LSB, SVG source),
  the recognized text with the expected words it missed, time and cost. It
  marks the result when the document changed after the scan. While it runs,
  the white scan control fills as on *Scan an image* and shows the OCR pass
  or check that is running. One scan runs at
  a time, shared with the *Scan an image* page.
- **Export** (top right) offers *Image*, the image file only, or *Image +
  fixture JSON*, which also downloads `<name>.fixture.json` (hash, label,
  obfuscation, expected text per reading, read-back, recipe). **Open** loads
  such a JSON to edit it again.

PNG and WebP are written lossless (WebP keeps colours under transparent
pixels); JPEG is lossy. The steganography writers mirror VIPI's readers, so
check such fixtures once with OpenStego or `zsteg` before relying on them.

Shortcuts: **T**, **C**, **M**, **S**, **A**, **P**, **V** add a layer; **+**/**−** zoom,
**0** fit, **1** actual pixels; **Delete** removes the selected layer; **⌘Z** /
**⇧⌘Z** undo and redo (Ctrl on Windows and Linux). Visible text is checked
only by a full scan; the editor does not run OCR.

## Saved artifacts

| Artifact | Path |
| --- | --- |
| Scan runs (OCR passes, decisions, detection) | the product cache, `~/Library/Caches/vipi/runs/<run-id>/` on macOS |
| Evaluation runs | `runs/evaluations/<run-id>/` (ignored by Git) |
| Saved baselines | `research/baselines/<run-id>.json` (committed) |

Research OCR models, profiles and the diagnostic detector are available from the
command line only; see the [research CLI reference](../../docs/research-cli.md).
