# ADR 0009: OCR mode selection

Status: Accepted. Recorded: 2026-10-21.

## Context and sources

The user approved three provisional OCR modes after a source-stratified screen
of ten raw images. Results are in the
[candidate-screen report](../runs/ocr-model-comparison/2026-10-21-candidate-screen-06/README.md).
Official model files and checksums come from the
[RapidOCR PP-OCRv6 model registry](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml).

## Decision

Map `fast` to PP-OCRv6 Tiny, `balanced` to Small and `quality` to Medium. When
no mode is supplied, keep `quality` as the default to preserve the existing
Medium behavior. `--ocr-model` selects one supported PP-OCRv6 model ID and
overrides the selected mode. `vipi setup` prepares all three mode models by
default; a setup mode or model option prepares only that selection.

## Alternatives

Using Medium for both balanced and quality would duplicate their behavior.
Selecting Tiny for every scan would save time but gave lower token coverage in
the screen, especially on TextOCR.

## Consequences

Reports identify the requested mode and resolved model. Adding a model from a
different OCR family requires a compatible adapter and pinned model files before
its ID can be selected through the public CLI.

## Validation boundary

The comparison used ten images, two per source, on CPU with no transformation
passes. Token coverage was 83.7% for Tiny, 86.2% for Small and 88.8% for Medium.
TextOCR coverage was low for every size, and one CyberSecEval3 reference was
questionable. These results support provisional mode defaults, not a full-run
accuracy claim.
