# 0020: Preserve text-line geometry and paragraph reading order

Status: Implemented for joint review following the user's request to fix OCR
assembly losses and reading order on a new branch.

## Context and sources

The completed detection-evaluation batch
`bbd44ecaa44c448499ea59d04ce0c9e0` contains 113 images. Assembly version 4
produces a complete final payload for 38 images, although 43 have a complete
individual OCR pass. Two demonstrated defects are in assembly rather than OCR:

- On the synthetic GPU RMA image, the axis-aligned envelopes of two slanted
  lines overlap. Assembly treats them as competing readings and drops the first
  instruction. A saved pass contains both lines.
- On the two Phantom question collages, geometric row joining interleaves
  separate paragraphs across three columns. All reference tokens are present,
  but ordered payload coverage is only 52.1% and 54.2%. Some rescaled readings
  also combine words from adjacent columns into a single line.

The native readings and source identifiers for the RMA and first collage
regressions are preserved in
[`assembly_regressions.json`](../tests/fixtures/assembly_regressions.json).
[`merge.py`](../src/vipi/ocr/merge.py) owns assembly; the engine contract in
[`architecture`](../docs/architecture.md) already supplies native word polygons.
The user authorized this assembly fix, without changing detection policy,
reference transcripts or OCR transformation selection.

## Decision

- Preserve native line orientation when enclosing its word polygons. Estimate
  direction between the first and last word centers, using the native edge for
  a single word. Small top-edge rounding errors must not set a long line's angle.
- Compare line locations in both lines' oriented coordinate systems. Keep the
  existing center-distance and overlap heuristics, and the horizontal fast path.
  A fragment outside an anchor's horizontal extent can join the same baseline
  only when an existing observation contains an identical word at the same
  coordinates. This avoids duplicating full readings around native fragments.
- Use paragraph gutters from the first native reading to divide later coarse
  observations at existing word boundaries before voting. Never cut through a
  native word or infer positions inside an opaque line box.
- Read separated horizontal bands first. Within a connected band, read columns
  independently when whitespace separates them and each column spans multiple
  geometric rows. Otherwise preserve row order. This structural requirement
  distinguishes continuing paragraphs from a single side label; it is an
  application heuristic, not a model requirement or guarantee of table parsing.
- Do not append a word from a competing coarse reading when a separately
  selected neighboring paragraph column already represents that word at the
  same location. Keep the coarse observation in evidence.
- Continue selecting observed spellings and retaining alternatives, native
  words and provenance. No reference text participates in assembly. Increment
  the recorded assembly version to 6; saved runs change only on explicit
  reassembly. Text detectors continue to consume only the final text.

## Alternatives

Rejecting every second observation from a single step prevents the RMA collapse
but also prevents legitimate overlapping OCR fragments from competing. Dropping
all additions loses useful partial-line extensions. Suppressing additions against
every neighboring word also disrupts code screenshots; suppression is confined to
independent paragraph columns. Reading every whitespace-separated component as a
column incorrectly moves standalone labels and table cells.

Choosing the best pass with reference knowledge would leak evaluation labels
into product behavior. Sending every variant to detectors would change detection
semantics and provider workload. Neither is needed for this assembly correction.

## Consequences

Skewed native lines can remain distinct even when their axis-aligned envelopes
overlap. Wrapped paragraphs with visible gutters retain column order. Headers,
footers, simple aligned tables and single labels retain row behavior. Geometry
and text may differ from earlier assemblies; raw observations remain unchanged.

Whitespace alone cannot resolve every layout, including tables with irregular
alignment, overlapping columns or images without visible gutters. The fix does
not repair OCR character errors: the RMA first line is retained but still contains
the observed `4181` instead of the reference's `418:`. Transcript mismatches and
context-dependent detection limits remain separate issues.

## Validation boundary

Regression tests use saved native readings for slanted lines and columns, plus
synthetic spanning headers/footers and aligned table rows. Existing assembly,
reassembly, product and research tests remain applicable.

The initial assembly-v5 replay of the 113-image batch increased complete final
payloads from 38 to 40 and improved ordered coverage on nine images. Both collages
reached 100%; the RMA image improved from 46.7% to 86.7%. One strict coverage decrease
is in `api_pagination.png` (84.4% to 82.2%): the reference inserts a period after
the endpoint where the image has none. Removing a duplicate phrase removes an
accidental later match for that period; ordered word matches remain 33 in both
assemblies. These are the existing references, not independently corrected
transcripts, and additional text is not penalized by that metric.

On the separate ten-image Round 5 OCR regression set, replaying its frozen
candidate readings with assemblies 4 and 5 matches 192/205 reference tokens and
seven complete images in both cases. That small set includes an Anamorpher
payload related to other development samples; it is not proof of generalization
to every unseen payload or layout.

Those initial replays did not repeat OCR inference or live detection requests.
Subsequent contrast inference and assembly-v6 checks are recorded in
[ADR 0021](0021-low-contrast-ocr-profile.md).
Detection accuracy after changing final text remains unmeasured. Windows and
Linux execution of this fix remains unverified until CI runs there.
