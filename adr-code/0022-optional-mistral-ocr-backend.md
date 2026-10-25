# 0022: Offer hosted Mistral OCR as an explicit CLI backend

Status: Accepted for review in PR #14. Recorded on 2026-10-25.

## Context and sources

The 113-image comparison on the frozen evaluation set measured 35/113 complete
payloads for the historical single-pass PP-OCRv6 Medium adapter and for the
stock RapidOCR default pipeline. The current multi-pass profile completes
40/113. The user requested trying a stronger OCR system and making it available
from the public CLI.

Mistral documents the `/v1/ocr` API for images and reports block text, reading
order, bounding boxes, confidence scores and usage. Its published OCR API price
is $4 per 1,000 pages. A CLI scan handles one image per request. Sources:
[OCR API documentation](https://docs.mistral.ai/studio/document-processing/basic_ocr),
[OCR API reference](https://docs.mistral.ai/api/endpoint/ocr) and
[API pricing](https://mistral.ai/pricing/api/).

## Decision

- Register `mistral-ocr-4-1` as an explicitly selected `--ocr-model` for
  `vipi scan`. Keep local PP-OCRv6 as the default. Read credentials from
  `MISTRAL_API_KEY` in the environment or the existing ignored `.env` file.
- Send each selected source image directly to `/v1/ocr`, request OCR blocks and
  block confidence, map returned coordinates into VIPI's existing OCR result
  contract, and save the normal scan report and artifacts. Do not store the key
  or upload images unless this model is selected.
- Use one untransformed image request per input. Do not reuse the local
  multi-pass profile for a billable page API; local transformations would
  multiply provider calls without an established benefit. Do not retry failed
  API requests automatically or silently fall back to local OCR.
- `vipi setup --ocr-model mistral-ocr-4-1` confirms the selected provider and
  skips local OCR model downloads. API credentials are checked at scan time.

## Alternatives and tradeoffs

Keeping the local engine only avoids external image transfer and usage charges,
but does not let the user compare a different OCR system from the CLI. Making
Mistral the default would change data handling, billing and repeatability for
all scans; it is therefore explicit. Sending every local transform would
increase the number and cost of API calls. Automatic retries or fallback could
duplicate charges or send the same image to an unintended provider, so failures
are reported to the user.

The external service requires network access and a valid Mistral key. Mistral
may update its hosted model; the requested model ID and returned model are
recorded in run metadata. Its OCR output may differ in spelling, structure or
hallucination rate, and this decision does not claim it meets the 90% quality
target. The scanner's detection policy remains downstream of the selected OCR.

## Validation boundary

Local checks exercise request formatting, block-to-region conversion, API
errors, CLI model selection and the single-pass guarantee using a mocked API.
A real Mistral API comparison is separate: it transmits selected evaluation
images and incurs the published per-page charge. No remote performance claim is
established by mocked tests.
