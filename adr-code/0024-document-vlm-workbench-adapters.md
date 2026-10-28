# 0024: Optional document VLMs in the OCR Workbench

**Status:** Implemented for review

## Context and sources

The OCR evaluation workflow needs to compare document-focused models without
changing the public scanner contract or forcing their runtime dependencies on
standard users. PaddleOCR-VL documents a full-page `PaddleOCRVL` pipeline and
Apple Silicon support. Granite-Docling documents a full-page Docling `VlmPipeline`
and an MLX model spec for Apple Silicon.

- [PaddleOCR-VL pipeline and hardware guide](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL.html)
- [Granite-Docling model card](https://huggingface.co/ibm-granite/granite-docling-258M)
- [Docling vision models](https://docling-project.github.io/docling/usage/vision_models/)
- Repository boundary: research UI, dataset evaluation, and experiments live in
  `research/`; product code must not import research.

## Decision

Add PaddleOCR-VL 1.6 and Granite-Docling 258M as optional models in the research
Workbench and its CLI. Run each through its upstream document pipeline on the
original image, store its full-page text and available block geometry, and skip
VIPI's multi-view OCR assembly for these results. Keep their runtime dependencies
in optional `uv` extras. Do not add them to the public `vipi scan` model list.

These models use one worker per run because each Workbench worker owns an engine
instance and loading multiple document VLM instances for one full-page run would
duplicate model memory without adding useful image-level parallelism.

## Alternatives

- Adapt each model to VIPI's existing line-level OCR interface and run the full
  transformation profile. This would not follow the models' documented
  page-level pipelines and would add repeated full-page inference.
- Add the optional runtimes to the standard OCR installation. This would impose
  large document-processing dependencies on users who do not select the models.
- Expose these models in `vipi scan`. This expands the public CLI model contract
  before runtime behavior and evaluation quality have been measured.

## Consequences

Workbench reports identify the model and full-page profile; evaluation consumes
the final pipeline text and returned geometries. Model assets are downloaded
only when a user explicitly prepares a model or runs that model for the first
time. Apple Silicon uses PaddleOCR-VL's CPU path and Docling's Granite
Transformers spec; this keeps Granite usable without a separate MLX dependency.

## Validation boundary

Static code and dependency-lock validation can confirm adapter wiring and
optional dependency resolution. Runtime compatibility, model downloads, memory
use, and OCR accuracy still require local model preparation and evaluation on
the target Mac; no benchmark result is implied by this decision.
