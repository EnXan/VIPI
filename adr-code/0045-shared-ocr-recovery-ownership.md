# 0045: Explicit ownership of shared OCR recovery

Status: Implemented for review, 2026-11-01.

## Context and sources

The maintainer requested simpler code, clear responsibilities, useful docstrings
and less duplicated documentation after the pipeline promotion in
[PR #25](https://github.com/EnXan/VIPI/pull/25).
[ADR 0044](0044-product-research-recovery.md) already places shared recovery in
the product package. Its implementation left 11 research modules redirecting
their identities through `sys.modules`, plus a workbench cost re-export.
Research callers can import the product implementation directly.

## Decision

Group recovery under `vipi.ocr.recovery`. Keep orchestration in `pipeline`,
scaled recognition in `probes`, source-resolution retries in `tiles`, and the
decision, signal, layout and retention helpers beside them. Keep shared OCR
engines, transforms, multi-view assembly and cost reporting in `vipi.ocr`.
Remove the research redirects and cost re-export; update callers directly.

Preserve public CLI options, recovery parameters, profile IDs, result schemas
and artifact layouts. The workbench still uses the separate fixed-transform
pipeline for its comparison profiles. This organizes ADR 0044's implementation;
it does not replace its recovery or execution-mode decisions.

## Alternatives and consequences

Keeping the flat layout avoids import changes but obscures recovery ownership.
Keeping compatibility aliases adds indirection without a public CLI contract
requiring them. New provider registries or a pipeline framework are unnecessary
for this reorganization. Repository callers use the new internal paths; external
scripts importing the removed internal modules must update those imports.

The architecture guide owns the module map, the CLI guide owns setup and model
selection, and the recovery guide owns stages and measured limits. Historical
experiment reports and source transcripts remain intact.

## Validation boundary

The initial ownership refactor passed 458 tests with one optional skip. The
removed test checked the deleted compatibility alias. Ruff, `git diff --check`,
local documentation link targets, and wheel/source builds pass; both distributions
contain all 15 recovery modules. The 42 moved functions/classes retain their executable AST,
allowing docstrings, import paths and the recovery-parameter rename.

These checks do not establish live model quality or Windows/Linux execution.
