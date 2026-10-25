# ADR 0001: Evidence and review workflow

Status: Accepted. Recorded: 2026-10-19.

## Context and sources

The user supplied the repository guidelines and requested their adoption. The
[working agreement](../AGENTS.md) and [OCR evaluation data rules](../research/ocr_eval/README.md)
define the current workflow for product and dataset work.

## Decision

Use English while preserving user data and source material as supplied. Base
choices on actual requirements and evidence; raise reasoned objections to
questionable choices. Apply "As much as necessary, as little as possible."
Keep temporary plans in `.llm-plans/` and important decisions in `adr-code/`.
Implement, verify and demonstrate one agreed concept, then stop for joint review.
Restrictions require a concrete use case or explicit requirement and an ADR
explaining purpose, normal-operation impact, alternatives and tradeoffs.

On revision, replace the previous ADR file only after summarizing its identifier,
decision, rationale and reason for revision in the new record. No ADR is
superseded by this initial record.

## Alternatives

Continuing with dataset-only root instructions would omit current product work.
A single uninterrupted implementation of all compliance changes would skip the
requested review boundary. Retaining superseded ADR files would make historical
comparison easier, but the user explicitly requested replacement with a summary.

## Consequences

Temporary notes stay local; reviewed decisions have a maintained record. Each
concept has a visible review boundary. Deleting replaced ADR files makes the
replacement summary essential for understanding history.

## Validation boundary

This concept establishes and checks repository guidance and decision records.
It does not claim whole-repository compliance. Existing German workbench text
and restrictions in [transforms](../src/vipi/ocr/transforms.py),
[workers](../src/vipi/ocr/workers.py), [API chunking](../src/vipi/detection/evidence.py)
and the [workbench](../research/workbench/web.py) still require separate review.
Their presence in code is not a justification. Runtime changes are deferred to
that review rather than retroactively approved by this ADR.
