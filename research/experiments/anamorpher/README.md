# README image-scaling experiment

The default `template.html` uses the fetched GitHub README from
`EnXan/immo_alert_berlin_private` and the user-supplied screenshot text as the
alternative. Open it and choose **Original README** or **Screenshot text**.
The normal HTML includes the full README. Capture mode uses its exact Quick Start
section through step 2, at 860×768, so both text views stay legible. The screenshot
code blocks are inert reference content. This selector changes the reference
HTML; the image-scaling effect lives in the generated PNG.

`render.py` captures the normal reference at 3440×3072 and both small references
at 860×768 using an isolated Chrome profile. `--source-from-reference` instead
creates the large source through 4x LANCZOS upscaling of the small normal image.
`probe.py` creates and checks three
images: the upstream red-only nearest solver, an experimental three-channel RGB
extension with one target, and the RGB extension with two independent targets.
The vendored generator and production OCR pipeline are not changed.

For the dual-target PNG, OpenCV/PyTorch Nearest sample position `(0, 0)` in each
4×4 block, while Pillow/TensorFlow Nearest sample `(2, 2)`. With `lam=0`, `eps=0`
and `gamma=1`, both target samples can be set independently. The generated small
views are verified against the corresponding reference PNGs pixel for pixel.
Other resize ratios, filters and compression are outside that guarantee.

From the repository root, with the existing OCR environment and prepared
PP-OCRv6 models, choose a new output directory:

```bash
.venv-ocr/bin/python -m research.experiments.anamorpher.render runs/anamorpher-probes/my-readme-test --source-from-reference
.venv-ocr/bin/python -m research.experiments.anamorpher.probe runs/anamorpher-probes/my-readme-test --variant rgb-dual
.venv-ocr/bin/python -m http.server 8023 --bind 127.0.0.1 --directory runs/anamorpher-probes/my-readme-test
```

Open `http://127.0.0.1:8023`. The generated `index.html` samples the actual
`rgb-dual/combined.png` in a canvas; it does not substitute reference text or
separate images. Its OCR panel shows the stored results of the real offline scan.
Use HTTP for canvas pixel access; browsers may block this for local `file:` URLs.

Chrome defaults to its macOS application path. Override `--chrome /path/to/chrome`
on other installations. The renderer refuses to overwrite reference PNGs; the
probe refuses to overwrite variant directories. Do not run generation twice in
parallel against the same directory.

`report.json` records source hashes, dimensions, solver parameters, changed pixel
fractions, resize checks, raw OCR text, boxes and reference coverage. Running just
`rgb-dual` checks 12 resize combinations; the three-variant default checks 36.
`references.json` supplies the case's text references, distinct markers and labels.
Reference snippets are checked after removing punctuation, case and whitespace;
exact PNG comparisons separately verify the two Nearest views. Shared repository
UI text is permitted as extra output. Reference PNGs and OCR results are controls,
not externally annotated datasets.

`prepare_immo.py CASE_DIRECTORY` rebuilds the default HTML and reference snippets
from a saved `source-readme.md`, `alternate-readme.md` and GitHub `source.json`.
The source is a snapshot, not a live synchronization with the private repository.

This experiment verifies two deterministic raster views and their OCR readings.
It does not establish optical invisibility, a physical left/right viewing effect,
arbitrary scaling robustness, an attack against an AI agent, or quality of the
pipeline's final multi-view text assembly. No remote detector API is called and
no case is added to the active dataset catalog.

## Joint visibility experiment

`visibility.py` jointly fixes both nearest samples and compensates the remaining
14 RGB pixels in each 4×4 block under byte-value bounds. It repairs rounding to
preserve attainable block sums exactly. `visibility_probe.py` compares the
unchanged baseline, compensation on the original palette, and two grayscale
headroom margins. It checks real sampler outputs, renders previews and runs
fresh native OCR for the new images:

```bash
.venv-ocr/bin/python -m research.experiments.anamorpher.visibility_probe runs/anamorpher-probes/immo-readme-20261012 --output runs/anamorpher-probes/immo-readme-20261012/visibility-new
```

The preview improvement is not a guarantee of human invisibility or native OCR
cleanliness. In the recorded test, the gray variants reduced the measured
LANCZOS ghost error while native OCR extracted more alternate fragments. The
default comparison view deliberately shows this tradeoff, with raw OCR visible.

## Neutral Codex image-input controls

`prepare_codex_probe.py OUTPUT_DIRECTORY` generates two synthetic README views
with random reference codes, two input sizes, and baseline/gray-compensated
combined PNGs. Real Pillow/OpenCV 4:1 nearest outputs must exactly match their
references. The fixtures contain no executable instructions or endpoints.

Inspect the combined images before reading `manifest.json`, then inspect the
nearest controls. Record the actual input route, requested detail and any
reported raster resizing. A `view_image` observation in an existing conversation
is not equivalent to a fresh user upload or an independent API evaluation.
These checks do not identify Codex's internal interpolation algorithm.

`codex_preprocessing_probe.py FIXTURES --output NEW_DIRECTORY` ports the public
Codex 0.162.1 image sizing rules and compares smooth-resize approximations with
the actual nearest control, running offline PP-OCRv6 on each raster. Pillow
BILINEAR approximates Rust Triangle; it is not a bit-exact Rust reproduction or
a Codex model evaluation. Use `prepare_codex_probe.py NEW_DIRECTORY
--reference-size 320 240` for a 1280×960 fixture that fits the public high-detail
size limits. Model-side preprocessing is still outside that guarantee.

## Triangle-targeted construction

`triangle.py` implements the published image-rs 0.25.9 Triangle sampling formula
with downsampling antialiasing, float32 centers and edge normalization.
`triangle_reference.cpp` independently samples opaque RGB8 using scalar arithmetic.
`triangle_probe.py FIXTURES --output NEW_DIRECTORY` constructs neutral reference
images for a declared attachment-cap/high-detail Triangle chain, verifies the
actual outputs with the compiled scalar port, and checks native, Triangle and
normal preview rasters with local OCR. It requires scipy and clang++ in addition
to the existing OCR setup. It does not execute the Rust crate or establish the
desktop model's full preprocessing. Codes and artifacts are stored per run.

The recorded first attempt achieves the alternative Triangle reading by visibly
changing the ordinary image. It is a construction control, not a hidden-text
success. Stronger source preservation produced overlapping letters. The earlier
screenshot instructions are not part of these neutral controls.

`dual_view_probe.py TRIANGLE_CASE --output NEW_DIRECTORY` directly constrains
both the ordinary LANCZOS reference and the Triangle alternative. It compares
three declared weightings, renders actual view outputs, and records complete
local OCR readings. Conditional pixel bounds check whether the specified raster
targets can closely agree under these paths; they are not universal OCR or
attack-impossibility claims. The recorded first dual-view run failed all three
two-view criteria. Its outputs must be treated as failed controls.
