# 0067 — Position-free scoring of unordered references in evaluation runs

Status: accepted, 2026-11-11.

## Context and sources

Evaluation runs and the OCR benchmark score each image with
`benchmark_report.score_result`. For references with a known reading order
the final OCR text is compared in order. References without a reading order
(mostly TextOCR scene photos, 45 of the 435 referenced development images) are
annotated as regions with image positions. [ADR 0028](0028-independent-ocr-payload-regions.md)
matched their words only to OCR words at the same position (at least 50 %
overlap), and an OCR box that spanned several independent regions was a group
conflict that failed the image.

GPT-6 Luna OCR returns text without word positions. `score_result` therefore
left those 45 images unscored for `cloud-openai` and `cloud-openai-jev`:
8,565 of 15,796 reference words were scored there, while every other
configuration was scored on all 15,796. The README's "Words recognized"
compared different denominators (user review, 2026-11-10). On the 390 images
every configuration could score, Luna read 94.5 %, Mistral 93.5 %, Google
88.1 % and local `speed` 80.2 %.

Asking Luna for word boxes was tested on 29 development images (2026-11-10,
one structured-output request each): ordered text was unchanged (99.8 % vs
100 %), but on the scene photos only 35 % of correctly read words got a box
with at least 50 % overlap, so the positional rule scored Luna at 28 % although
it read 64 % of the words; output tokens rose about 5.5 times. Positions from
Luna are not accurate enough to score with.

The injection detector receives only the final text, never positions.

## Decision

- For a reference without a reading order, `score_result` matches each
  annotated region in the final OCR text without word positions: word order
  inside a region is kept, the order between regions is ignored, the spelling
  tolerance of evaluation v4 applies, and every OCR word covers at most one
  reference word. Longer regions claim their words first and reference order
  breaks ties, so the result is deterministic. Every OCR provider is thus
  scored on every image with the same rule.
- Group conflicts are still computed when the OCR result has positions and are
  reported (`group_conflicts`, `group_conflict_images`), but they no longer
  fail the image, because they cannot be determined for providers without
  positions.
- Ordered references are scored as before.
- `benchmark_report.report` no longer refuses retained outputs whose
  evaluation code changed since inference. Scoring reads only the retained
  results; the report records the scoring sources and policy it used, and a
  summary records the scoring-code hashes (`metric_sha256`), so `status`
  marks a baseline stale until it is rescored.
- `python -m research.evaluate rescore RUN_ID` scores a complete run again
  without inference and replaces only the metrics, `metric_sha256` and
  `report_sha256` in the run summary and its saved baseline; every other field
  stays.

## Relation to ADR 0028

ADR 0028 (independent OCR payload regions, which replaced ADR 0023) set
evaluation v4: tolerant word coverage in final text, literal fidelity reported
separately, known reference order preserved, word order kept inside
independent regions and ignored between them, one-to-one matching with a 50 %
overlap threshold, and a group conflict when one OCR box overlaps several
independent regions, which made the image incomplete. Its reason was to accept
reordered independent groups while rejecting merged groups. That still governs
the research OCR evaluation (`metrics.evaluate`) used by experiments. For
evaluation runs and the benchmark, this ADR replaces its positional matching
and the failing group conflict, because they made providers without word
positions unscorable and the comparison unfair.

## Alternatives

- Ask Luna for word boxes: tested; boxes too inaccurate for the 50 % overlap
  rule and about 5.5 times the output tokens.
- Compare only the images every configuration can score: fair, but drops the
  scene photos from the metric for every provider.
- Ignore word order completely: rejected in ADR 0028; it would accept a
  changed word sequence inside one region.
- Report a lower bound with unscored images as zero: still differs by
  provider and penalizes missing positions rather than missing text.

## Consequences

A word read elsewhere in the image can now cover a reference word of the same
spelling; positional matching prevented that. Merged groups no longer fail an
image. Coverage on scene photos rises slightly for providers with positions;
Luna's scene photos are scored for the first time. Rescored development runs:
`cloud-openai` 86.9 % of scored words (84.8 % of all planned words, three images
failed), `cloud-openai-jev` 86.3 %, `cloud-google` 88.1 %, `cloud-mistral`
84.6 %, `local-speed` 70.0 %. Detection metrics are unchanged. Every saved
baseline is stale until rescored. Resuming an unfinished benchmark across this
change still fails, as before, because evaluation sources are part of its
provenance.

## Validation boundary

Unit tests cover region order, word order inside a region, typo tolerance,
one-to-one use of OCR words, reported but non-failing group conflicts, and
`rescore` keeping every non-metric field. The rescored figures come from the
retained outputs on the M2; the local runs on the M4 are rescored separately.
The Luna box test covers 29 images and one prompt.
