# ADR 0078: SVG inputs: a source text reading and a safe render

Status: Accepted, 2026-11-17 (issue #84). Implemented for review; the
measurements listed under validation are still open. Amends the input formats
of [ADR 0003](0003-public-cli-contract.md) and the verdict scope of
[ADR 0071](0071-scan-verdict-and-final-ocr-completeness.md) ("final OCR text"
becomes "final OCR text and, for SVG, the source text").

## Context and sources

Repositories carry SVG diagrams and icons, and VIPI skipped them. An SVG is an
XML text document as well as an image. A coding agent that opens the file reads
all of its text, including text that is invisible when rendered. A human or a
vision model sees only the rendered image. The use case agreed in issue #84:
flag SVG files whose text, visible or not, or whose rendered image contains a
prompt injection.

No open-source scanner checks SVG for prompt injections. PhantomLint
(arXiv 2508.17884, PDF/HTML) compares extracted text with OCR of the render.
Cloudflare's svg-hush keeps only same-document references when serving SVG.
Known techniques for SVG and related formats, with sources, are listed in the
issue #84 comment of 2026-11-17:

- hidden `<text>` and metadata, CDATA and attribute cloaking (Unit 42, March
  2026);
- Unicode tag characters and zero-width splitting, which evaded Prompt Guard and
  Azure Prompt Shield (Hackett et al., 2025);
- malicious fonts that remap glyphs (EMNLP Findings 2025).

Local probes on 2026-11-17 established:

- `xml.etree.ElementTree` drops comments outside the root, DTD comments,
  unreferenced entities and processing instructions; `pyexpat` with explicit
  handlers reports them. Expat 2.6.2 rejects a billion-laughs chain and does
  not load `SYSTEM` entities.
- `resvg_py` 0.5.0 draws a local file referenced by `<image href="/abs/path">`.
- It ignores `@font-face` data-URI fonts, `<foreignObject>`, `@media` dark rules
  and `@import`.
- It rejects absolute units (`mm`, `in`, `pt`) unless `dpi=96` is passed.

## Decision

- **Selection.** `.svg` joins the supported extensions for folders, explicit
  files and `--diff`. `.svgz` is not supported.
- **Parsing.** `vipi.svg.read_svg` parses once with `pyexpat`. Internal entities
  are expanded, because Illustrator exports use them. DTDs and external entities
  are never loaded, and external entity system IDs are reported. The root must
  be `<svg>` in the SVG namespace or without a namespace. Malformed input is a
  per-file error.
- **Source reading.** This is everything a raw reader sees except markup
  syntax:
  - character data in every element and namespace, including CDATA;
  - comments anywhere, processing instructions and internal entity values;
  - attribute values, except a fixed list of geometry, paint, unit, reference
    and animation-timing attributes (`STRUCTURAL_ATTRIBUTES`). A value of a
    listed attribute still counts when it holds prose, meaning four
    whitespace-separated words.

  `<tspan>`/`<textPath>` continue the line of their `<text>`. `data:` URIs with
  a text, `+xml`/`+json` or SVG media type are decoded, nested SVGs
  recursively, and binary payloads are dropped. The detector sees a normalised
  copy: Unicode tag characters decoded to ASCII, and format characters (`Cf`)
  and variation selectors removed. Their count is reported, but they are not a
  finding by themselves, because flag emoji use tag characters.
- **Rendering.** The render-safe copy keeps only `href` values that start with
  `#` or `data:`. Nested SVG `data:` URIs are filtered the same way. Removed
  references are reported. resvg renders the copy from a string with an empty
  `resources_dir`, `dpi=96`, system fonts and a white background. The intrinsic
  size follows usvg's rules:
  - absolute `width`/`height`;
  - a percentage of the `viewBox`;
  - a missing side derived from the `viewBox` aspect ratio;
  - otherwise 100 user units.

  `vipi.svg.render` reproduces these rules to choose the scale before
  allocating a raster.
- **Scale and bound.** The raster is drawn at 2×, reduced until the rounded-up
  raster fits `MAX_INPUT_PIXELS` (40 MP). This is a rendering parameter, not a
  rejection: a vector has no native resolution, diagram labels are often
  10–12 px and sometimes smaller, and browsers on HiDPI screens draw at 2×. The
  2026-11-21 measurement (validation boundary) shows 2× recovering labels below
  8 px: 99.2 % instead of 79.4 % word recall at 5 px. The 40 MP bound is the existing
  local decoder guard; here it bounds the raster VIPI itself allocates (40 MP
  RGBA ≈ 160 MB) and applies to cloud mode too. ADR 0047's cloud exemption
  concerns decoding pixels that already exist.
- **Detection.** The final OCR text of the render and the source text are two
  readings of one evidence (`scope: final_ocr_and_svg_source`). Identical texts
  are checked once. Any check at or above the threshold detects. Visibility
  does not change the verdict.
- **Base64 outside `data:` URIs** is left as it is in the source reading,
  neither decoded nor removed. Real SVGs carry it: 12 of this repository's 27
  SVGs embed a C2PA Content Credentials manifest as about 7.7 KB of base64 in
  `<metadata>`. The maintainer chose on 2026-11-17 to keep this realistic input
  unchanged and to let the false-positive measurement show whether it matters.
  Decoding runs of at least 32 base64 characters was considered: it would close
  E12 and remove the noise, but it adds a length heuristic before there is any
  measured need.
- **Embedded fonts.** An `@font-face` with a `data:` font, or SVG
  `<font>`/`<glyph>`, makes the evidence incomplete. Browsers apply such fonts
  and resvg does not, so remapped glyphs could show text that neither reading
  contains. Such a file is `null` (exit 2) unless a reading is detected.
  Presence of `<foreignObject>` alone does not make a scan incomplete: its text
  is in the source reading, and draw.io exports use it routinely.
- **Report.** The file record gains an `svg` object with sizes, scale, removed
  references, features, the invisible-character count, the source text length
  and the highest score per reading. Artifacts keep `input.svg` beside the
  rendered `input.png`.

## Alternatives considered

- **Render only (the issue as filed).** This misses everything an agent reads
  but no renderer draws.
- **CairoSVG.** LGPL, needs system Cairo, and had an SSRF (CVE-2023-27586).
- **librsvg via pyvips.** Needs system libraries.
- **A headless browser.** Matches GitHub rendering best, but adds a browser
  download and needs network and script blocking.
- **svg-hush as a dependency.** A native wrapper with a single maintainer for
  one rule that VIPI implements in its parser pass.
- **ElementTree.** Misses the text outside the root, in the DTD and in
  processing instructions.
- **An allowlist of text attributes** (`aria-label`, `title`, `alt`). Misses
  attribute cloaking (`data-*`, arbitrary attributes).
- **Every attribute.** Adds path data and styling to every detector input.
- **Invisible characters as a finding.** Flag emoji would be flagged.
- **Loading embedded fonts into resvg.** Needs font parsing (a new dependency)
  and rewriting family names that attackers control.
- **A second, dark-background render.** Doubles OCR cost. Text in dark-only
  rules is already in the source reading.

## Consequences

- An SVG costs one OCR run plus detector checks of two readings. Icon sets add
  many small files; `.vipiignore` can exclude them.
- The vipi-action selects whatever VIPI selects. Pinning a VIPI release with
  SVG support changes the result of scans with default inputs, which under
  [ADR 0076](0076-action-threshold-follows-detector-default.md) calls for Action
  `v2`; `v1` keeps a VIPI pin without SVG support.
- Not covered (each is a `known_gap` or `ocr` case in `tests/svg_cases.py`):
  - base64 outside `data:` URIs (E12);
  - embedded rasters hidden from the render (R08);
  - shapes shown only in another animation or colour-scheme state (R09, R10);
  - in the source reading only, so OCR has to catch them: text stored reversed
    behind a bidi override (E04), homoglyphs (E06), text scattered one glyph per
    element (S33), text as shapes and pixel text (R02–R04, R12);
  - variation-selector smuggling: removed, not decoded (E05);
  - image-scaling attacks inside embedded rasters.
- resvg draws no text inside embedded SVG images (probed); that text is in the
  source reading (E09–E11).
- An embedded font makes the file an error (exit 2) even when a reading is
  detected; the verdict then still says `injection_detected`, as for other
  incomplete scans.

## Validation boundary

`tests/svg_cases.py` is the table of 72 cases: 33 hidden-text techniques
(S01–S33), 12 encodings (E01–E12), 12 render-channel cases (R01–R12) and 15
safety cases (X01–X14). Each case cites its source and states whether the
payload reaches the source reading, whether resvg draws it, the features,
removed references and outcome (`covered`, `ocr`, `incomplete`, `blocked`,
`error`, `known_gap`).

- `tests/unit/test_svg_cases.py` checks every case through `read_svg` and
  `render_svg`. Whether resvg draws a payload is decided by rendering the case
  with and without it and comparing pixels: drawn, not readable.
- `tests/integration/test_svg_scans.py` scans every case through the CLI
  pipeline with fake OCR and a detector that finds the payload, and checks
  verdict, exit code and the report's `svg` object.
- `tests/unit/test_svg_corpus.py` parses and renders the repository's 27 SVGs
  and seven benign look-alikes (Illustrator, Inkscape, draw.io, Mermaid,
  matplotlib, Figma, a C2PA manifest), and compares their detector text with a reviewed golden
  snapshot (`tests/fixtures/svg/benign_detector_text.json`).
- `tests/unit/test_svg.py` covers sizes (18 cases checked against resvg), the
  scale bound, unfiltered resvg drawing a local file, and the report.

Measured locally on 2026-11-18 (Apple GPU; d1 at 45, Prompt Guard at 80,
PP-OCRv6 quality with d1 review). Every attack case uses one explicit payload
sentence, so these are coverage checks with real models, not a detection rate:

- **Source reading.** d1 and Prompt Guard detect all 43 attack cases whose
  payload reaches the source reading. The lowest d1 score is 0.62, where CSS
  surrounds the payload (S29).
- **Benign SVGs.** Of the 27 repository SVGs and 7 look-alikes, d1 flags none;
  its highest score is 0.385. Prompt Guard flags `vipi-scan-flow.svg` (0.993),
  whose text describes prompt injection. The C2PA manifests score at most 0.20
  (d1) and 0.01 (Prompt Guard).
- **Rendered reading.** With real OCR, all seven `ocr` cases are detected
  (S33, E04, E06, R02, R03, R04, R12). OCR reads 62–100 % of the payload words.
- **Scale.** OCR word recall on the eight repository diagrams (666 words,
  10–11 px labels, 17 px titles) is 99.24 % at 1× and 99.39 % at 2×. Rendering
  the same diagrams smaller stands for diagrams with smaller labels:

  | Labels at 1× | 1× | 2× |
  | :-- | :-- | :-- |
  | ≈ 5 px | 79.4 % | 99.2 % |
  | ≈ 6 px | 91.0 % | 98.4 % |
  | ≈ 8 px | 98.9 % | 98.3 % |
  | ≈ 10 px | 99.2 % | 99.4 % |

  2× matters below about 8 px and is neutral above. With small labels, 1× is
  also slower, because recovery re-reads what it judges incomplete (8 of 8
  diagrams at 5 px). This confirms 2×.

Not verified:

- Clef-Flash, the cloud detectors and cloud OCR;
- varied payloads and third-party benign SVGs (dataset concept);
- `resvg_py` on Linux and Windows, and font fallback on GitHub runners; the
  render oracle assumes system fonts exist (`ubuntu-latest` in CI).
