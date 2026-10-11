# OCR Pipeline Implementation Plan

Implemented 2026-10-04. See [README.md](README.md) for setup and actual usage.

## Goal and scope

Implement a local image-to-text pipeline with CLI and a simple web interface.
Every input follows the same fixed transformations and the user-selected OCR
model. Anamorpher is handled through ordinary downscaling, with no dataset-specific
branch or separate processing. No automatic corpus benchmarks,
model ranking, optimization, training or multilingual preparation in this phase.
Write the README after the implementation, documenting actual usage and behavior.

## Shared pipeline

1. Decode a PNG, JPEG or static WebP image to RGB8; preserve the input file.
   Use ordinary white-background compositing if alpha is present, without an
   additional transparency inspection. Keep mappings to input coordinates.
2. Include OCR on the unchanged input and immediately save that step's result.
3. Process views with 1–8 parallel workers (default 4), each with its own OCR
   instance. Within each worker, execute steps sequentially:
   adjust image -> run selected OCR -> save recognized text and positions ->
   proceed to the next adjustment. Complete and save each OCR pass before
   generating that worker's next adjusted image; keep the input raster available. Publish
   the adjusted image before OCR starts and its saved result before proceeding.
4. Use the fixed full-image views below, with scaling/rotation based directly on
   the input. Perform downscaling before crops or other filters. Add overlapping
   tiles from original and 2x: 1024 pixels, stride 896, complete edge coverage.
5. For each full-image view and tile, apply four independent filters after its
   unchanged OCR pass: grayscale, local contrast (CLAHE on grayscale,
   clipLimit=2, tileGridSize=8x8), RGB inversion and adaptive Gaussian threshold
   (grayscale, blockSize=31, C=11). Run and save OCR immediately after each filter.
   Each filter starts from that view or tile; do not choose steps by OCR scores.
6. Save every pass to runs/<run-id>/steps.jsonl, including step ID, source view,
   transformation, raw text, positions in the adjusted image and positions mapped
   to the input. Save each adjusted image for the web preview and final overview.
   Flush each record before continuing in that worker. Assign IDs ahead of execution
   and sort the overview and final assembly by those IDs. Do not use reference regions to guide
   OCR. Preserve the native recognized spelling and text.
7. Only after all adjustments finish, assemble the stored results into the final
   output. Align observed lines by input position; choose a primary observed
   reading using Levenshtein similarity, view agreement and native confidence.
   Count each view at most once despite its filters. Extend partial lines with
   spatially anchored additional words. Keep repeated occurrences at distinct
   positions. Preserve all competing readings separately, including different
   scaling payloads; do not interleave them into the main text or invent spelling
   from a dictionary. No dataset-based tuning or hard confidence cutoff.

Write result.json and result.txt in the same run directory. CLI and web both
return this assembled result. If processing fails, retain saved step results
and return a clear error; do not label an interrupted run as a final result.

## Fixed full-image views

| Size / orientation | Implementations |
| --- | --- |
| Original | Unchanged raster |
| 2x | Pillow BICUBIC |
| 1/2, 1/4, 1/8 | Pillow NEAREST, BILINEAR, BICUBIC |
| 1/2, 1/4, 1/8 | OpenCV INTER_NEAREST, INTER_LINEAR, INTER_LINEAR_EXACT, INTER_CUBIC |
| 1/4 | PyTorch and TensorFlow nearest, bilinear, bicubic |
| Original rotated 90, 180, 270 degrees | Exact rotations |

This is 32 full-image views before filters and tiling. Each full-image view has
five versions including unchanged, giving 160 OCR inputs plus five per tile.
Target dimensions are max(1, floor(input dimension * factor)); record actual
sizes. This includes Anamorpher 3200 -> 800 and 4368 -> 1092 without metadata.
Match the existing vendored PyTorch/TensorFlow samplers, including float32-to-
uint8 conversion, antialias=False and PyTorch align_corners=False for linear/cubic.
Keep OCR-internal resizing explicit; no silent additional image preprocessing.
No extra target sizes, selective recovery passes, cross-products of rotations
and scales, or dataset-specific reveal verification in the runtime pipeline.

## OCR models and output

Provide three explicit model choices: RapidOCR/ONNX with PP-OCRv5 server detection
and English recognition, RapidOCR/ONNX with PP-OCRv6 medium, and Tesseract LSTM
with English tessdata_best. Default to PP-OCRv6 medium as a UI default, not a
measured winner. One selected model handles the entire request; no ensemble.
Prepare required model files explicitly and use fixed versions; no hidden model
selection or background benchmark. Do not add language routing or language packs.

The shared function is extract(image, model, on_event=None)
-> {run_id, text, regions, variants}. It emits progress at real processing
boundaries for the web; CLI uses the same pipeline. Regions retain native
text/positions and variant evidence. Variants include their transformation IDs,
image dimensions, saved image, recognized text and boxes in variant coordinates.
Main text joins primary readings in best-effort spatial order. Conflicting
readings remain in regions[].alternatives and raw variants. The web exposes them
under Abweichende Lesarten. Reassemble completed runs from saved steps without OCR.
Optional reference coverage checks are described below. No CER, WER, model
ranking or automatic corpus benchmarks.
A failed required step fails the request clearly; do not silently skip it.

## CLI and web

- CLI: python -m ocr_pipeline extract IMAGE --model MODEL --workers 4 prints recognized text;
  --json provides the structured result and --output saves it if requested.
- Web: python -m ocr_pipeline serve starts Flask on 127.0.0.1:8000. Use a single
  HTML page with vanilla JavaScript; no separate frontend framework.
- Allow file selection, drag-and-drop and clipboard image paste. Show an image
  preview, model selector, worker selector (1–8, default 4) and an Extract text button.
- Live view: show the current step, completed/total steps and actual state
  (transforming, OCR, saving, assembling). Display each adjusted image immediately,
  then its recognized text alongside it. Show empty OCR results explicitly.
  Show each worker's state; selecting a worker follows its live images and results.
- Overlay native OCR polygons on the adjusted image using a responsive SVG with
  the image's dimensions as its viewBox. Reveal boxes and associated text with a
  short stroke/fade animation after results arrive; use word boxes when available,
  otherwise line boxes. Respect prefers-reduced-motion. Animation never delays
  processing or invents intermediate OCR detections.
- Keep every completed step available during the run. Selecting an earlier step
  pauses automatic view switching; a Live button returns to the current step.
  At completion, show all variants with their images, boxes and extracted texts,
  plus the final assembled text with copy and TXT/JSON download controls.
- Use assets/tokens/vipi-tokens.css, the existing white VIPI SVG logo and favicon.
  Default to Ink/Graphite surfaces, Paper text, restrained gray borders and generous
  spacing. Use Geist for interface text and Geist Mono for step labels/values.
  Honor logo clear space and its 96 px minimum width. Keep OCR overlays monochrome
  with contrasting light/dark outlines; injection-status colors belong to later
  classification. Desktop: image and text side by side; mobile: stacked.
- POST /api/runs accepts multipart image/model/workers and returns a run ID. One
  background run calls the shared function with the selected worker count.
  GET /api/runs/<id>/events streams Server-Sent
  Events: run_started, step_started, image_ready, ocr_started, saving,
  step_completed, assembling, run_completed or run_failed. Publish step_completed
  only after its save finishes. Serialize persistence and event IDs across workers.
  On failure, finish in-flight calls before publishing the terminal error.
- GET /api/runs/<id> returns the current state, saved steps and final result when
  available; reconnecting restores this state and resumes events without rerunning
  OCR. Use ordered event IDs and replay to avoid gaps. Serve saved variant images
  through run/step IDs. Keep prior images and texts visible after a failure.
- Accept one active local run at a time. Clean temporary uploads after processing;
  retain run artifacts for the overview. Reject invalid/oversized inputs clearly.
  Inputs up to 40 MP and generated views up to 80 MP are supported.

## Implementation order and functional checks

1. Create the shared contracts, fixed transformations and coordinate mappings.
2. Add the three OCR adapters and the shared text extraction function.
3. Expose CLI, then the local web interface using the same function.
4. Test exact resize/rotation geometry, tile edges, fixed filter execution,
   model selection, distinct text occurrences, CLI output and web error states.
   Assert adjust -> OCR -> flushed save ordering for every step, retention of
   earlier results after a failure, and final assembly only after all steps.
   Check live event ordering/reconnection, overlay alignment after resizing and
   rotation, reduced motion, and that the overview contains every completed pass.
5. Run functional smoke checks on existing images; do not evaluate the dataset,
   compare model quality, tune parameters or consume annotation text as input.
6. Write the actual usage README once the implementation works.

Dataset annotation context is retained separately in [TEST_DATASET.md](TEST_DATASET.md)
and supplies scope/word regions for selected-image evaluation.

## Selected-image evaluation

- Browse the active OCR index, filter by source category and search; choose one
  or more images. Keep the fixed OCR transformations unchanged.
- Evaluate only after OCR. Require the complete source reference, allowing extra
  OCR text; normalize Unicode/case/whitespace without correcting spelling.
- Use ordered token coverage for payloads. Use spatial word-region matching for
  TextOCR, without inventing a global reading order. Ignore excluded regions.
- Compare each filter with its unfiltered view and each other unfiltered view
  with the original. Show coverage, improvements, losses and new valid variants.
- Distinguish successful detection from final assembly retention. Report missing
  tokens and technical failures separately.
- Process selected images sequentially with the chosen worker count per image;
  continue after individual errors. Persist and restore reports and image links.
