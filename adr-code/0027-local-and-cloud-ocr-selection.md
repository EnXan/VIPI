# 0027: Separate local OCR profiles from cloud provider selection

Status: Accepted by the user; implemented for review in PR #14. Recorded 2026-10-28.

## Context and sources

The user approved local/cloud execution selection, local Tiny/Small/Medium
profiles and explicit cloud providers after reviewing the saved 113-image
baseline at `runs/batches/49d38e6a499a4f458f60f3e50e2cab21/report.json`.
Google and Mistral each completed all reference words for 69/113 images; Luna
completed 65/113. Google was faster and had lower estimated API cost than Mistral
in that run. These observations do not justify calling Mistral a premium quality
tier. They describe that selection and metric, not general OCR superiority.

Sources: the user's confirmed CLI proposal, current configuration/adapters,
[OpenAI Luna documentation](https://developers.openai.com/api/docs/models/gpt-6-luna),
[image inputs](https://developers.openai.com/api/docs/guides/images-vision),
[Google DOCUMENT_TEXT_DETECTION](https://cloud.google.com/vision/docs/ocr), and
[Mistral OCR documentation](https://docs.mistral.ai/models/ocr-4-1).

## Superseded decisions

This replaces ADR 0009, "OCR mode selection" (2026-10-21). That decision mapped
`fast`/`balanced`/`quality` to Tiny/Small/Medium, kept Medium as default, allowed
explicit model overrides and prepared all local sizes by default. It was based
on a provisional ten-image raw screen with token coverage 83.7%/86.2%/88.8%.
The model mapping and default remain; `speed` becomes the preferred Tiny name
and `fast` remains an alias. Cloud selection is now separate from local profiles.

This also replaces ADR 0022, "Offer hosted Mistral OCR as an explicit CLI backend"
(2026-10-25). It added `--ocr-model mistral-ocr-4-1`, environment/ignored `.env`
credentials, one original-image request, normal reports/artifacts, no automatic
retry/fallback, and setup without local OCR downloads. Its rationale was an
explicit hosted alternative following weak local OCR coverage, without changing
default data handling or multiplying billable calls through local transforms.
The new decision retains those constraints and the legacy model selector while
adding the evaluated Google and Luna providers and an explicit execution mode.

## Decision

- `--modus local|cloud` selects execution; the default remains local. Local
  `--ocr-mode quality|balanced|speed` maps to PP-OCRv6 Medium/Small/Tiny. Quality
  remains default; `fast` is accepted as a legacy alias for speed.
- Cloud uses `--ocr-provider google|openai|mistral`, default Google Cloud Vision
  DOCUMENT_TEXT_DETECTION. OpenAI selects GPT-6 Luna via Responses with original
  image detail and reasoning disabled; Mistral selects OCR 4.1. Provider names
  make no quality or price ordering promise. Downstream detector choice remains
  independent; local OCR alone does not make a hosted detector local.
- Keep direct registered model selection. Without an explicit execution mode,
  selecting a cloud model still opts into that provider for compatibility.
  An explicit local/cloud mode must match the model. A provider requires
  explicit cloud mode, and provider/model selectors cannot be combined: reject
  contradictions rather than choosing precedence that could send an image to
  an unintended service. CLI local-profile options with explicit cloud mode
  are rejected rather than silently ignored.
- Configuration resolves the same model for setup, scanner and Python sessions.
  Setup continues preparing all local sizes by default. Cloud setup skips OCR
  weights and performs no provider request; scan checks the selected credential.
  A separately selected local Prompt Guard detector can still be prepared.
- Promote the existing Google/Luna research adapters into `vipi.ocr.cloud` and
  reuse them from the Workbench. Product code imports no research or Flask.
  Credentials use the existing resolver: GOOGLE_CLOUD_API_KEY/GOOGLE_API_KEY,
  OPENAI_API_KEY, or MISTRAL_API_KEY. Do not persist credentials.
- Cloud receives one original decoded image per input, retaining provider text
  without VIPI transformations or assembly. Reuse the provider engine across
  selected images. Preserve returned geometry and usage in the normal artifacts.
  API failures remain errors; no retries, provider switch or local fallback.
  Local inference/profile behavior remains unchanged by this routing feature.
- Reports add resolved OCR execution/provider fields. Local profile fields are
  null for cloud instead of implying `quality`; this also applies to legacy
  direct Mistral selection. Historical reports remain unchanged. Bump this
  unreleased feature PR to 0.5.0 and update current version references.

## Alternatives and consequences

Price labels such as cheap/balanced/expensive would describe current list rates,
not task suitability, and would change meaning when prices change. Calling
Mistral quality/premium would imply a benefit not established by the comparison.
Provider selection is explicit and needs no unsupported ordering. One preset
resolver keeps API, setup and CLI behavior consistent without a new routing
framework or automatic model cascade.

Cloud OCR transfers images externally and requires the selected account's key
and network access; provider charges apply. Local OCR still defaults to its
existing release transformation profile, while the compared research baseline
was original-only. Routing does not establish equal accuracy between those
configurations or achievement of the 90% OCR/scanner targets.

## Validation boundary

Verify CLI/Python defaults, all providers, profile aliases, conflicts, setup,
one unchanged PNG and one request per image, session reuse, exact text passed
to detection, usage/artifact persistence, credential errors and redaction,
failure exit codes and no retry/fallback. Run product/research regression checks
and inspect the built wheel for the shared adapters and research boundary.
Automated tests mock transports; this routing change does not rerun paid OCR,
benchmark model quality or validate new Windows/Linux execution.
