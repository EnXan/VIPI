# 0037: Trial a guarded upscaled OCR candidate

Status: Research trial, 2026-11-01.

## Context and decision

The prior layout-only candidate in ADR 0036 caused regressions. The user
explicitly authorized iterative improvements and combinations with full-suite
comparisons until an initial improvement. Test local word re-recognition and
upscaled whole-image OCR as separate research routes, using current selected
OCR as fallback and comparing actual image/OCR pairs without reference data.

For the broad 2x candidate, evaluate a conservative check that rejects a
model-preferred replacement when it omits any word token from a native
incumbent region with OCR confidence at least 0.9. This threshold was selected
post-hoc after examining the development suite's regression. It is an
experimental hypothesis and not a production confidence calibration or a
universal quality guarantee. It can reject useful corrections to confidently
wrong OCR. The existing 2x input pixel boundary remains in effect.

## Results and consequences

As documented in [OCR_REGION_UPSCALE_EXPERIMENTS.md](../research/ocr_eval/OCR_REGION_UPSCALE_EXPERIMENTS.md),
the first measured full-suite result without a passing-reference regression is
93/113 rather than 92/113. It recovered one reference case and used 27 more
local OCR observations and 27 more Decisions requests than the preceding
comparison. This result uses the same development data to select the guard and
measure its result, and reuses cached OCR and model responses; it does not
establish held-out effectiveness, complete-image correctness, absence of
regressions outside the references, or production-scale cost. Preserve the
existing product and adaptive defaults. Require independent validation and cost
evaluation before considering integration.
