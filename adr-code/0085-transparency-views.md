# ADR 0085: Scan transparent images on white, on black and without alpha

Status: Accepted for implementation and review, 2026-11-23 (issue #82).
Amends the verdict scope of
[ADR 0071](0071-scan-verdict-and-final-ocr-completeness.md) in the same way
as ADRs 0078, 0083 and 0084: the final OCR texts of the extra views are part of
it. Amends [ADR 0082](0082-cloud-image-check-without-image-only-scans.md):
the image check submits each distinct view.

## Context and sources

`vipi.images.decode_image` composites every image onto white and drops alpha.
What an agent sees depends on its pipeline:

- a light UI or a white composite: what VIPI checked until now;
- a dark UI or a black composite;
- alpha dropped: many image pipelines call `convert("RGB")` or an equivalent
  and keep the colour values of fully transparent pixels. Exploiting this is
  the AlphaDog attack class
  ([NDSS 2025](https://ndss-symposium.org/wp-content/uploads/2025-789-paper.pdf)).
  McKee and Noever ([arXiv 2401.15817](https://arxiv.org/pdf/2401.15817),
  [arXiv 2402.09671](https://arxiv.org/abs/2402.09671)) report 16 affected
  vision systems, including GPT-4V.

[PyRIT's `TransparencyAttackConverter`](https://github.com/microsoft/PyRIT/blob/main/pyrit/converter/transparency_attack_converter.py)
optimises alpha against a white composite. As a result, the attack image
appears on black.

The dataset has no real alpha-channel attack. Its 33 `high_transparency`
entries have faint text baked into opaque pixels. Only 2 of 554 images have a
transparent pixel at all: two flowchart jailbreaks.

Agreed with the maintainer on 2026-11-23 in the issue:

- run full OCR recovery on every distinct view;
- submit every distinct view to the cloud image check;
- no special case for the raw-colour view;
- release the vipi-action pin as a new major version (see Consequences).

## Decision

- **Trigger.** A PNG or WebP image with any pixel below full opacity after EXIF
  orientation. This includes palette PNGs with `tRNS`. Opaque images and JPEGs
  are scanned exactly as before. SVG renders stay on white (ADR 0078).
- **Views.** `vipi.transparency.read_views` builds, in this order:
  - `white`: an alpha composite on white, pixel-identical to `decode_image`;
  - `black`: an alpha composite on black;
  - `rgb`: alpha dropped, raw colour values.

  A view whose pixels equal an earlier view's records `same_as` and is not
  scanned.
- **OCR.** The white view is the ordinary OCR run of the input. Every other
  distinct view runs through `OcrSession.extract` with full recovery. That
  creates its own run artifacts.
- **Detection.** The final OCR text of the black and raw-colour views are
  readings `ocr_black` and `ocr_rgb` next to the ordinary OCR reading. The
  evidence scope gains `_and_transparency_views`. Identical texts are one
  reading, as for every reading (ADR 0078). Any check at or above the
  threshold detects. Which view showed the text is evidence. It does not
  change the verdict.
- **Image check.** In a cloud scan without a text finding, the distinct views
  are submitted in view order. Each check is a job with `view`. Checking stops
  at the first detection, as the single image check stops after a text
  finding.
- **Failures.** A view whose OCR raises leaves the scan incomplete (exit 2).
  Its exception is reported on the view, and the other views are still checked.
- **Report.** The file record gains `transparency.views`: `name`, `same_as`,
  `score` and `image_check` per view, plus `run_id`, `artifacts`,
  `ocr_seconds`, `ocr_text_characters` and `ocr_cost` per scanned view, or
  `error`. The top-level `ocr_*` fields stay those of the white view.
  `estimated_total_api_cost_usd` adds the OCR cost of every view.

## Alternatives

- **Replace the white composite** with one other background. Rejected. The
  probe below shows that no single view covers white-on-transparent text,
  colour values under zero alpha and an ordinary black logo at the same time.
- **Native OCR only on the extra views.** Cheaper, but empty-looking views are
  the case in which recovery's contrast probes matter. The maintainer chose
  full recovery.
- **Flag a difference between views as a finding.** Rejected. Ordinary logos
  differ between views (cases C01 and C02), so a difference is evidence of
  transparency, not of an attack.
- **More backgrounds**, such as mid-grey chat themes. Not added. Black and
  white bound the luminance range, and mid-tones rely on contrast recovery.
  This is a known gap, not a measured need.
- **An alpha-only view.** Text encoded only in alpha with uniform colour
  values already shows in the white or the black view.

## Consequences

- A transparent image costs one OCR run per distinct view, usually two or
  three. In the measurement below, an extra view took 1.5–7.4 s locally: empty
  views cost more, because recovery probes them. Opaque inputs cost nothing
  extra.
- QR and barcode decoding (ADR 0084) and metadata (ADR 0083) still use the
  white view only. A code visible only on black is a known gap.
- Results change for default inputs that contain transparent images. Under the
  rule of [ADR 0076](0076-action-threshold-follows-detector-default.md), the
  vipi-action release that pins this VIPI version is a new major (`v5`). That
  release is a follow-up in EnXan/vipi-action. Released as 0.19.0.

## Validation boundary

`tests/transparency_cases.py` lists:

- six attack cases (T01–T06): white text on transparency, text under zero
  alpha, a uniform white composite, faint text, a palette `tRNS` PNG and a
  WebP;
- two benign logos (C01, C02).

Each case states its distinct views and which views show the text.

- `tests/unit/test_transparency.py` checks views, deduplication, that the
  white view equals `decode_image`, EXIF orientation, input limits and the
  report.
- `tests/integration/test_transparency_scans.py` scans every case with a fake
  OCR engine that reads text only from a raster that shows it. It also covers
  an opaque RGBA image (one OCR run, no `transparency` object), a failed view
  and the per-view cloud image check for Jev and OpenAI.

Measured 2026-11-23 with real local OCR (`--ocr-mode balanced`, PP-OCRv6
small, d1 decisions) and the d1 detector at 45. The inputs were seven
1000×140 images of a generated payload sentence and two benign logos
(not retained):

| Case | White | Black | Raw colour | Verdict | White only (before) |
| --- | --- | --- | --- | --- | --- |
| T01 white on transparent | empty | 0.94 | = black | detected | missed |
| T02 colour under zero alpha | empty | empty | 0.94 | detected | missed |
| T03 uniform on white | empty | 0.94 | = black | detected | missed |
| T04 faint text | 0.94 | empty | 0.94 | detected | detected |
| T06 WebP alpha | empty | 0.94 | = black | detected | missed |
| C01 black logo | 0.07 | empty | = black | clean | clean |
| C02 white logo | empty | 0.08 | = white | clean | clean |

The two dataset images with transparency read the same text in the white and
the black view (one reading). Their verdicts are unchanged (detected at 0.81
and 0.54), and their OCR time doubled to about 24 s.

Not measured: the cloud OCR providers and cloud detectors on real views,
Clef-Flash, the PyRIT converter's own output, and false positives on a corpus
of real transparent icons and screenshots. The cases are synthetic and few.
New dataset cases belong to #73.
