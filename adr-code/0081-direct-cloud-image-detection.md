# ADR 0081: Direct cloud image detection

Status: Accepted for implementation and review, 2026-11-22.

## Context and sources

An offline comparison combined direct whole-image predictions with retained
OCR-text predictions on the 450-image development split. With the existing
0.80 threshold, Google Vision + Luna rose from 178/227 to 199/227 attacks
detected and from 8/223 to 10/223 false positives. The paired Mistral runs
added 12 attacks and one false positive for Luna and seven attacks and two
false positives for Jev. These are development results from retained outputs.

The maintainer asked for a direct scan and an integrated image check in the
regular cloud process, after a text check without a finding. API sources:
[OpenAI Decisions](https://developers.openai.com/api/reference/resources/decisions/methods/create),
[OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision)
and [TypeSafe image inputs](https://docs.typesafe.ai/images#limits).

## Decision

- `vipi scan --image-only` runs the selected cloud detector on the whole image
  using the standard VIPI policy. It defaults to GPT-6 Luna through Decisions.
  `--detector jev` selects TypeSafe. Regular cloud scans run the same image
  check if their final text checks found no injection, including when OCR
  completed with empty text. A text hit finishes detection without an image
  request. The selected detector and threshold apply to both inputs.
- Record the image check independently in the report. A hit from either check
  flags the image. Failed required requests remain scan errors under ADR 0071.
  A negative image result does not turn an incomplete text check into a clean
  scan. Local scans and research `detect-text` use text evidence.
- Send a single whole raster. Apply shared input decoding, including EXIF
  orientation and white compositing. Jev requires each side to be 280–1568 px.
  Fit within the maximum and pad smaller sides to the minimum. Luna uses
  `detail: original` and proportional resizing when above its 30,000-patch
  input limit. These are provider requirements. SVG image-only scans check the
  safe render. Regular SVG scans additionally check source text per ADR 0078.

## Alternatives and consequences

- Replace the OCR scan with image-only detection. On the development split
  standalone image recall was lower. The explicit image-only route is useful
  for inspection and measurements when OCR is intentionally absent.
- Always submit images alongside OCR text. The separate image request is
  unnecessary after a positive text result and adds provider latency and cost.
- Leave the second check behind a separate flag. The agreed cloud scan runs it
  when the text has no finding. `--image-only` selects a separate scan input.

## Validation boundary

Fixture tests check the two provider payloads, model selection and the CLI
report, including skipped image calls on text hits and incomplete scans on
provider refusal. The paired development comparison quantifies the measured
quality trade-off. The one-time test-split confirmation is recorded in the
pull request before merge. Provider-side boxes and explanations are a
separate change.
