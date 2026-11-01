# Code and design decisions

Record important implementation, architecture and design decisions here. Use
English and include **context and sources**, **decision**, **alternatives**,
**consequences**, and **validation boundary**. Identify accepted decisions and
proposals accurately; recording behavior does not prove that it is justified.
Temporary planning and review queues belong in `.llm-plans/`.

| ADR | Decision |
| --- | --- |
| [0001](0001-evidence-and-review-workflow.md) | Evidence-based, minimal implementation and one-concept review workflow |
| [0002](0002-product-and-research-boundaries.md) | One `vipi` package with separate research tools and shared scan contracts |
| [0003](0003-public-cli-contract.md) | Two-command CLI, explicit model setup, committed-image diffs and score policy |
| [0006](0006-apache-2-license.md) | Apache License 2.0 for VIPI's original code and documentation |
| [0012](0012-hugging-face-evaluation-dataset.md) | Maintainer-reviewed Hugging Face dataset and pinned local downloads |
| [0014](0014-detection-evaluation-without-context.md) | Separate workbench collections and detection evaluation without scanner context |
| [0017](0017-multi-classifier-workbench-cli.md) | Repeatable CLI classifier selection and guided workbench setup |
| [0018](0018-workbench-scan-and-evaluation-pages.md) | Separate scan setup from evaluation reports |
| [0019](0019-workbench-progress-and-image-reports.md) | Live scan progress and compact per-image evaluation details |
| [0020](0020-ocr-assembly-geometry-and-reading-order.md) | Oriented OCR line matching and paragraph column order, implemented for review |
| [0024](0024-document-vlm-workbench-adapters.md) | Optional full-page document VLM pipelines in the OCR Workbench |
| [0026](0026-sequential-ocr-model-comparisons.md) | Native baselines, one-image readiness and sequential OCR comparisons (replaces 0025) |
| [0028](0028-independent-ocr-payload-regions.md) | Tolerant word coverage with independent visual groups and group integrity |
| [0034](0034-expanded-priority-ocr-signals.md) | Expand the research priority cascade (replaces 0033) |
| [0036](0036-layout-repair-research-trial.md) | Revert signal-context experiment and test layout repair (replaces 0035) |
| [0037](0037-guarded-upscale-research-trial.md) | Trial a guarded upscaled OCR candidate |
| [0039](0039-revert-group-wise-ocr-comparison.md) | Revert the group-wise OCR comparison trial (replaces 0038) |
| [0040](0040-ambiguous-line-retry-trial.md) | Test a line-level retry for ambiguous OCR characters |
| [0041](0041-missing-text-separate-evidence-trial.md) | Trial missing-text probes and separate OCR evidence |
| [0042](0042-local-resolution-letter-insertions.md) | Trial local missing-letter corrections from a resolution probe |
| [0044](0044-product-research-recovery.md) | Shared product recovery and full local/cloud execution (replaces 0021, 0027 and 0043) |

When revising an agreed decision, write its replacement with a summary of the
old ADR (identifier, decision, rationale and reason for revision), then delete
the old file and update this index and links. Do not remove the old record before
carrying its summary forward. This replacement rule follows the user's explicit
request; retaining superseded files was considered and not selected.
