# 0028: Independent OCR payload regions and group integrity

Status: Accepted following the user's request to evaluate group order separately
from word order and to reject payloads whose visual groups were merged.

## Summary of replaced decision

This replaces ADR 0023. ADR 0023 set
evaluation v3 to tolerant word coverage in final scanner text, reported literal
word fidelity separately, preserved known reference order, and matched unordered
references within annotated locations. It was chosen to tolerate minor OCR
spelling errors without accepting unrelated text or relying on an external
judge. The user clarified that independent visual groups may be returned in a
different order, while word order within a group and the boundaries between
groups still matter. The v3 region matcher could combine OCR observations across
independent groups, so this distinction was not represented in the pass result.

## Context and sources

The source requirements are the user's direction that the Dashboard and expense
receipt should pass when their independent text groups are returned in another
order, while the Asteron payload should remain incomplete when its two visual
groups are split/interleaved and `II` is read as `l`. The saved
PP-OCRv6 Tiny `checkpoint1_final` outputs provide the observed text groups and
their image-coordinate boxes. The current reference transcript remains the
ground truth; group annotations add geometry without rewriting it.

## Decision

- Record evaluation version 4. Preserve the version-3 word coverage, spelling
  tolerance, literal fidelity and historical report behavior.
- Allow a reference to annotate independent `payload_regions`. Preserve word
  order inside each annotated region and ignore the order between regions.
- Keep one-to-one word matching and the existing 50% overlap threshold.
- For independent regions, report an OCR group as a group conflict when its box
  overlaps more than one reference region by at least 50% of the smaller box.
  A group conflict makes the image incomplete even if its words are otherwise
  present in the OCR output. Keep lexical coverage visible as a separate value.
- Apply this rule uniformly to every reference that uses independent regions;
  do not select behavior by image filename or case label. References without
  region annotations retain their existing ordered-text behavior.
- Preserve the exact payload transcript. Region annotations only describe its
  spatial groups; they do not replace or editorially revise the payload.

## Alternatives

Ignoring all word order would incorrectly accept a changed word sequence inside
one text group. Keeping one global sequence would fail benign layouts when
independent groups are emitted in a different order. Combining all OCR words
that happen to overlap a region can hide an OCR box that spans multiple visual
groups. An external model could infer relationships, but would add provider
cost, variability and a non-local dependency.

## Consequences

Pass rate depends on reviewed group geometry for references that use
`payload_regions`. Broad OCR boxes can trigger a group conflict even when their
text is readable; their lexical coverage remains separately visible. This
measures the annotated payload groups only and does not establish that all
visible image text was detected. Group order remains intentionally irrelevant;
semantic relations between groups are not scored.

## Validation boundary

Unit tests verify that independent groups can be reordered, word order within a
group still matters, OCR boxes spanning multiple reference groups cause a
conflict, and `II` is not covered by `l`. The corrected local annotations for
the Dashboard and expense receipt pass against saved OCR outputs. Both Asteron
variants remain incomplete with group conflicts and the missing `II` word.
This is a rescore of saved outputs, not a new OCR inference run.
