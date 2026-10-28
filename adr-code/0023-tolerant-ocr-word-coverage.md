# 0023: Tolerant word coverage and separate literal fidelity

Status: Accepted following the user's request to change OCR evaluation before
their next full evaluation run.

## Context and sources

The user prioritizes finding every reference word, allowing minor OCR spelling
errors before Jev or the Decisions API classifies the final text. Literal word
agreement must remain a separate metric. Evaluation version 2 instead counted
exact NFKC/casefold-normalized tokens, including punctuation. A long encoded
payload could receive zero coverage after one character substitution; casefold
could also conceal case errors that change encoded content.

Sources are the user's requirements, the current metric implementation in
`research/ocr_eval/evaluation/metrics.py`, and saved OCR observations. The
BUG-4821 example has seven substitutions in its 284-character payload despite
zero exact-token coverage. Its raw observations and reference remain unchanged.

## Decision

- Record evaluation version 3 and the matching policy in new runs and batches.
- Make tolerant reference-word coverage in the **final scanner text** the
  primary metric. A case passes only when every reference word is covered.
  Best-pass/pipeline coverage remains diagnostic; a word found in a raw variant
  but lost from final assembly cannot make the case pass.
- Define words as whitespace-delimited units containing at least one Unicode
  word character. Preserve their literal spelling and attached symbols.
  Standalone punctuation does not contribute a word.
- For coverage only, normalize NFKC and case, and remove punctuation. Accept
  Levenshtein distance up to `max(1, floor(0.20 * reference_length))` for
  normalized words of at least two characters. Single characters must match
  after normalization. This is one edit for lengths 2–9 and 20% rounded down
  thereafter. Missing words cannot be replaced by raw word-count equality.
- This tolerance is an explicit application heuristic implementing "minor
  spelling errors", not a model/protocol restriction or a validated semantic
  equivalence threshold. One edit deliberately allows short words such as
  `it`/`mt`; it can also accept meaning-changing pairs. A stricter proportional
  threshold would reject short words after one OCR error. Larger allowances
  would increase accidental matches. Record the policy so runs remain auditable.
- Preserve reference order where annotated. Each observed word/fragment may be
  used at most once, so repeated reference words require repeated evidence.
  Adjacent OCR fragments may form one reference word, treating visual wrapping
  consistently for every text type, without encoding-specific rules. For
  unordered references, retain one-to-one matching in overlapping annotated
  word locations and local region order.
- Score literal, case-sensitive word agreement separately, including attached
  punctuation and symbols. Visual word splitting may be rejoined, but no case
  or Unicode normalization changes literal spelling. Report this independently
  for final text, raw variants and batch/category aggregates.
- Preserve extra OCR text as allowed by the existing recall-oriented contract.
  Words merged across reference boundaries are not inferred by this metric.
  Neither metric measures hallucination precision or semantic equivalence.
- Count technical failures as failed cases in pass-rate denominators; exclude
  pending/cancelled cases. Mean word coverages include scored completed images.
- Preserve historical reports. Display their old metric explicitly; do not
  silently rescore or relabel their exact-token results as version-3 coverage.

## Alternatives

Pure box coverage measures text localization independently of spelling, but most
payload references lack annotated word boxes. Counting OCR words without matching
would accept unrelated background/UI text. An LLM judge introduces provider cost,
variability and potentially reference leakage. Treating every similar word as
literal would hide the difference requested by the user. Separate per-encoding
rules are unnecessary for generic word coverage.

## Consequences

Small spelling errors and missing punctuation can pass primary word coverage
while reducing literal fidelity. Higher primary pass rates therefore do not
establish improved model accuracy or scanner recall. Case coverage remains
limited to the reference scope: a payload-only annotation cannot prove all
visible image text was detected. An exact word pass also does not validate
standalone punctuation or decoded content.

OCR models, transformations, assembly, scanner inputs and classifier decisions
are unchanged. The existing branch already includes the 0.4.1 version bump
relative to main's 0.4.0; this change stays in that feature PR.

## Validation boundary

Local tests exercise edit boundaries, repeated/missing words, unrelated text,
line-wrapped long words, literal case/symbol fidelity, spatial constraints,
assembly losses, and batch report persistence/restoration. Existing OCR and
detection tests remain applicable. No paid provider calls or new full model
evaluation are needed for this scoring change. The user starts the next full
evaluation after restarting the workbench. No quality target is claimed from
changed scoring rules.
