# ADR 0082: Whole-image check only inside cloud scans

Status: Accepted, 2026-11-22. Replaces
[ADR 0081](0081-direct-cloud-image-detection.md).

## Supersedes

ADR 0081 (accepted 2026-11-22) added two routes to Jev and GPT-6 Luna
whole-image detection. Regular cloud scans check the whole image after a text
check without a finding. `vipi scan --image-only` sends only the image,
without OCR. The rationale was an offline comparison on the 450-image
development split. With the 0.80 threshold, Google Vision + Luna rose from
178/227 to 199/227 attacks detected and from 8/223 to 10/223 false positives
when image predictions were combined with OCR-text predictions. Standalone
image recall was lower than the combined scan. The explicit route was kept for
inspection and measurements without OCR.

Reason for revision: on 2026-11-22 the maintainer decided to remove
`--image-only`. The flag is a second scan entry point that is easy to confuse
with the regular cloud scan. It also checks less evidence: no OCR text, no SVG
source reading, and none of the text readings planned for image metadata
(issue #121). The regular cloud scan already runs the same image check.

## Decision

- Remove `vipi scan --image-only`, the `image_only` scan option, the
  `image_only` evidence scope and `detect_image()`.
- Keep the integrated check from ADR 0081 unchanged. A regular cloud scan with
  Jev or OpenAI as detector checks the whole image when its final text checks
  found no injection, including when OCR completed with empty text. A text hit
  finishes detection without an image request. The selected detector and
  threshold apply to both inputs.
- Record the image check independently in the report as `image_check`. A hit
  from either check flags the image. Failed required requests remain scan
  errors under ADR 0071. A negative image result does not turn an incomplete
  text check into a clean scan. Local scans and research `detect-text` use
  text evidence.
- Send a single whole raster after shared input decoding, including EXIF
  orientation and white compositing. Jev requires each side to be 280–1568 px:
  fit within the maximum and pad smaller sides to the minimum. Luna uses
  `detail: original` and proportional resizing above its 30,000-patch input
  limit. These are provider requirements. SVG scans check the safe render and
  the source text per ADR 0078.

## Alternatives considered

- **Keep `--image-only`.** It remains usable for inspection, but it is a second
  contract to document, test and extend for every new reading.
- **Hide it as an undocumented option.** The behaviour would still need tests
  and would still miss text readings.
- **Move it to `research`.** No retained evaluation uses it today. A research
  command can be added when a measurement needs image-only predictions.
- Alternatives already rejected in ADR 0081: replacing the OCR scan with image
  detection (lower standalone recall), always submitting the image with the OCR
  text (unneeded cost after a text hit), and a separate flag for the second
  check.

## Consequences

- Breaking CLI change, released as 0.16.0. Commands with `--image-only` now
  fail with a usage error (exit 2). Reports no longer use
  `evidence_scope: image_only`, and every file record has OCR fields.
- Every scan checks the OCR text, and further readings such as image metadata
  apply to all scans without an image-only special case.
- The vipi-action does not pass `--image-only`, so its inputs are unaffected.

## Validation boundary

Fixture tests check both provider image payloads through a regular cloud scan
(Jev padding, OpenAI `detail: original`), model selection, skipped image calls
after text hits and incomplete scans on provider refusal. The development
comparison from ADR 0081 is unchanged, because the integrated check is
unchanged. No new quality measurement was run.
