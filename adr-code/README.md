# Code and design decisions

Record important implementation, architecture and design decisions here. Use
English and include **context and sources**, **decision**, **alternatives**,
**consequences**, and **validation boundary**. Identify accepted decisions and
proposals accurately; recording behavior does not prove that it is justified.
Temporary planning and review queues belong in `.llm-plans/`.

| ADR | Decision |
| --- | --- |
| [0001](0001-evidence-and-review-workflow.md) | Evidence-based, minimal implementation and one-concept review workflow |
| [0003](0003-public-cli-contract.md) | Two-command CLI, explicit model setup, committed-image diffs and score policy |
| [0006](0006-apache-2-license.md) | Apache License 2.0 for VIPI's original code and documentation |
| [0012](0012-hugging-face-evaluation-dataset.md) | Maintainer-reviewed Hugging Face dataset and pinned local downloads |
| [0020](0020-ocr-assembly-geometry-and-reading-order.md) | Oriented OCR line matching and paragraph column order, implemented for review |
| [0028](0028-independent-ocr-payload-regions.md) | Tolerant word coverage with independent visual groups and group integrity (for evaluation runs revised by 0068) |
| [0034](0034-expanded-priority-ocr-signals.md) | Expand the research priority cascade (replaces 0033) |
| [0036](0036-layout-repair-research-trial.md) | Revert signal-context experiment and test layout repair (replaces 0035) |
| [0037](0037-guarded-upscale-research-trial.md) | Trial a guarded upscaled OCR candidate |
| [0039](0039-revert-group-wise-ocr-comparison.md) | Revert the group-wise OCR comparison trial (replaces 0038) |
| [0040](0040-ambiguous-line-retry-trial.md) | Test a line-level retry for ambiguous OCR characters |
| [0041](0041-missing-text-separate-evidence-trial.md) | Trial missing-text probes and separate OCR evidence |
| [0042](0042-local-resolution-letter-insertions.md) | Trial local missing-letter corrections from a resolution probe |
| [0044](0044-product-research-recovery.md) | Shared product recovery and full local/cloud execution (replaces 0021, 0027 and 0043) |
| [0046](0046-product-ocr-benchmark.md) | Reproducible live product OCR benchmark and explicit reporting denominators |
| [0047](0047-cloud-decision-image-resolution.md) | Preserve full-resolution images for cloud decisions |
| [0048](0048-separate-ocr-completeness-and-repair.md) | Separate OCR completeness from repair selection |
| [0049](0049-provider-specific-confidence-validation.md) | Validate provider confidence against OCR reference outcomes |
| [0051](0051-combined-evaluation-catalog.md) | One combined evaluation catalog with an editable vocabulary (draft tooling) |
| [0052](0052-reproducible-enterprise-attack-images.md) | Reproducible product-view attack screenshots and screenshot-backed Anamorpher scaling |
| [0053](0053-one-evaluation-dataset.md) | One dataset layout (`catalog.json`, `vocabulary.json`, `images/`) replacing the two catalogs |
| [0054](0054-evaluation-runs-and-baseline.md) | Evaluation runs of product scan configurations against a saved baseline (replaces 0050) |
| [0055](0055-workbench-without-research-model-tools.md) | A product-only workbench without research model tools (replaces 0014, 0017, 0018, 0019, 0024, 0026) |
| [0056](0056-contribute-only-changes.md) | Contributors add or generate images locally and submit only their changes |
| [0057](0057-jev-detector-configurations.md) | Jev detector configurations for evaluation (amends 0054) |
| [0058](0058-reuse-ocr-across-runs.md) | Reuse OCR and detection results across evaluation runs |
| [0060](0060-model-identity-per-used-entry.md) | Model identity covers only the registry entries a configuration uses (amends 0054) |
| [0061](0061-prompt-guard-detector-configurations.md) | Prompt Guard detector configurations for evaluation (extends 0057) |
| [0062](0062-record-execution-devices.md) | Record where an evaluation run executed: host and device per component |
| [0064](0064-never-reuse-failed-detections.md) | Never reuse a detection that failed (extends 0058) |
| [0065](0065-clef-flash-replaces-clef.md) | Clef-Flash replaces Clef as the local quality model (replaces 0059) |
| [0066](0066-parallel-evaluations.md) | Parallel evaluations in the workbench, with a warning before local runs overlap |
| [0067](0067-remove-retired-scan-paths.md) | Product/research boundaries and shared recovery without retired scan paths (replaces 0002 and 0045) |
| [0068](0068-position-free-benchmark-scoring.md) | Position-free scoring of unordered references in evaluation runs, and offline rescoring |
| [0069](0069-workbench-request-boundaries.md) | Confined evaluation paths, fixed HTTP error messages and image previews without blob URLs |
| [0070](0070-action-setup-only-for-selected-images.md) | GitHub Action prepares models only when images are selected, without a model cache |

When revising an agreed decision, write its replacement with a summary of the
old ADR (identifier, decision, rationale and reason for revision), then delete
the old file and update this index and links. Do not remove the old record before
carrying its summary forward. This replacement rule follows the user's explicit
request; retaining superseded files was considered and not selected.
