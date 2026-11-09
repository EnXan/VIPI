# ADR 0055: A product-only workbench without research model tools

Status: accepted, 2026-11-09.

## Context and sources

The user asked for a workbench that makes scanning and evaluating simple and
unambiguous, chose product scan options only (no model comparison, profiles,
workers, hardware or multiple classifiers) and then asked to remove the
research commands and the old local downloads. The workbench pages and the
evaluation flow are recorded in [ADR 0054](0054-evaluation-runs-and-baseline.md).
This ADR records what was removed and replaces six ADRs whose decisions no
longer apply. Their summaries:

- **ADR 0014** (detection evaluation without scanner context): the browser and
  batch APIs kept `ocr_evaluation` and `detection_evaluation` as separate
  collections; detection ran once per image with empty caller context and
  reused that result for every case, counting context-dependent mismatches as
  ordinary errors. Rationale: catalog context is ground truth, not a scanner
  hint. Revised because there is one dataset now; the rule "no caller context
  during evaluation" carries over unchanged into ADR 0054.
- **ADR 0017** (multi-classifier workbench CLI): a three-step setup (input,
  options, review), a checklist and a repeatable `--text-classifier` for Jev,
  OpenAI Decisions and Prompt Guard, versioned thresholds for every enabled
  detector, and the standalone `detector_cli`. Rationale: compare detectors on
  one OCR result. Revised because the workbench uses the product detector only.
- **ADR 0018** (separate scan and evaluation pages): Scan held input, options
  and single-image results; Evaluation held dataset reports; dataset browsing
  was an input of Scan. Rationale: keep setup and reports apart. Revised because
  an evaluation is now started and read on its own page.
- **ADR 0019** (progress and per-image reports): a scan beam over the image,
  time estimates and a per-image evaluation table with stored texts and scores.
  Rationale: make long batches observable. Revised because evaluations now show
  progress counts and summary metrics; per-image changes are in the comparison
  report.
- **ADR 0024** (document VLMs in the workbench): PaddleOCR-VL 1.6 and
  Granite-Docling 258M as optional research models with their own extras,
  one worker per run and no VIPI assembly. Rationale: compare full-page document
  models. Revised because research OCR models are removed.
- **ADR 0026** (sequential OCR comparisons): one research model registry,
  round-0 readiness checks on one image, the native `baseline` profile as the
  research default and models compared one after another. Rationale: fair,
  memory-safe model comparisons. Revised for the same reason.

## Decision

- `python -m research.workbench` has one command, `serve`. Removed:
  `prepare-models`, `check-models`, `extract`, `reassemble` and
  `research.workbench.detector_cli` with their modules (model registry, model
  runtime and worker, document VLM and LightOn adapters, round-0 checks,
  detector options), the OCR profiles and the research OCR runner in
  `research/ocr_eval/evaluation/`.
- The product no longer lists PaddleOCR-VL and Granite-Docling, and the
  `ocr-paddle-vl`, `ocr-granite-docling` and `ocr-lighton` extras are removed.
- The OCR model comparison protocol (`research/ocr_eval/BASELINE.md`) is
  removed; its results stay in the Git history and in `reports/`.
- Old local downloads of the two former catalogs are deleted from the
  maintainer's checkout; `.gitignore` no longer names them.

## Alternatives and consequences

- *Keep the research CLI next to the simple workbench.* More reach for model
  research, but two vocabularies and code that only serves past experiments.
  Not selected by the user.

Consequences: comparing other OCR models or detectors needs new code; Git
history has the removed adapters. The Tesseract engine, reachable only from
the research commands, is removed from the product package as well. Retained experiments under
`research/ocr_eval/experiments/` and historical reports are unchanged.

## Validation boundary

The test suite passes after the removal; tests that only covered the removed
commands were deleted. A real local `vipi scan` completes on this branch.
