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
| [0004](0004-ocr-reference-and-evaluation-scope.md) | Exact OCR references, scoped evaluation and preservation of dataset evidence |
| [0006](0006-apache-2-license.md) | Apache License 2.0 for VIPI's original code and documentation |
| [0007](0007-reduced-ocr-transforms.md) | Reduced OCR transformation set as the production default |
| [0008](0008-research-layout.md) | Research ownership, stable dataset identities and experiment grouping |
| [0009](0009-ocr-mode-selection.md) | Provisional Tiny/Small/Medium mapping for fast/balanced/quality CLI modes |

When revising an agreed decision, write its replacement with a summary of the
old ADR (identifier, decision, rationale and reason for revision), then delete
the old file and update this index and links. Do not remove the old record before
carrying its summary forward. This replacement rule follows the user's explicit
request; retaining superseded files was considered and not selected.
