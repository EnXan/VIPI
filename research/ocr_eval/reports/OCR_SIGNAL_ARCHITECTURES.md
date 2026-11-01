# Local OCR signal experiment

This research-only experiment evaluates whether local signals can identify
cases needing further review without a decision-model call. It does not change
the active adaptive OCR profile or apply transformations. The code is in
`evaluation/signals.py`; its thresholds are hypotheses, not production settings.

## Signals and strategies

Priority 1 is empty OCR; priority 2 is short OCR (fewer than 40 non-whitespace
characters). Both describe coverage, but short text can also be correct.
Priority 3 comprises low OCR confidence (at least 30% of scored regions below
0.8) and unfamiliar words (at least 50% among three or more eligible words on
the page or in one group). These thresholds were fixed before running this
experiment, not calibrated to a representative population. At least three
words are required to avoid making a linguistic judgment from a single token.
Missing confidence, insufficient eligible text, and missing CJK tokenizers are
reported as unavailable rather than clear. Numeric and mixed alphanumeric
tokens do not count as unknown dictionary words.

The `wordfreq` research dependency supplies frequency data for 42 languages.
It is not universal or current for every domain. Rare words, names and
specialized vocabulary can be unfamiliar; checking many languages can also
make gibberish look familiar. CJK tokenization needs additional packages not
installed by this experiment. It cannot detect missing text or determine that
a fluent reading is complete or correct.

Three routing approaches use the same evidence:

1. **Priority cascade:** evaluate signals in priority order and stop at the
   first trigger.
2. **Any signal:** evaluate every signal and route when any triggers.
3. **Corroborated:** either coverage signal suffices; the two lower-priority
   signals must both trigger. All signals are evaluated.

When no decision triggers but a required signal is unavailable, the result is
`unresolved`, not `no_signal`. `no_signal` means only that these particular
checks did not find an issue. It is not an acceptance or safety verdict. The
first two strategies route identically for identical inputs; the cascade can
avoid work and returns less evidence.

## Development comparison

Thirty images were fixed in advance: 15 failing and 15 passing the previously
verified original PP-OCRv6 Tiny baseline, including known difficult cases and
controls. This is a deliberately balanced development sample, not a random
sample of production images. Existing original OCR and grouped text were
replayed; no new OCR, transformation or external call was performed. Reference
labels were used to choose and assess the sample, never as signal input.
Artifacts including the frozen selection and per-image evidence are local in
`.llm-plans/ocr-signal-architectures-2026-11-01/`.

| Strategy | Routed for inspection | Baseline failures routed (of 15) | Baseline passes routed (of 15) | Failures with no signal |
| --- | ---: | ---: | ---: | ---: |
| Priority cascade | 10 | 7 | 3 | 8 |
| Any signal | 10 | 7 | 3 | 8 |
| Corroborated | 7 | 6 | 1 | 9 |

There were no unresolved cases in this sample. A passing baseline measures the
approved reference payload, not completeness of all text in an image; a
baseline failure need not be fixable by transformations. Inspection counts
therefore do not measure recovered OCR accuracy, security detection, or the
benefit of applying a correction. The six deliberately included difficult
images were routed by all three strategies. One additional failing image was
routed only by the first two, alongside two more passing images.

On this macOS machine, one fresh Python process per strategy processed the
30 stored results in approximately 2.5–2.8 seconds including imports and
local reads, with a measured process peak of approximately 0.9–1.1 GB. This is
a single cold-process experiment with possible OS file caching, not a
production latency or memory benchmark. Most importantly, checking all
available frequency lists has a substantial memory cost; the dependency's
wheel alone is about 54 MB. The global word cache can grow with distinct words.
Neither is suitable to assume acceptable for a local deployment without
further profiling and a different, justified design.

The experiment does not establish safe thresholds, multilingual coverage,
text-free-image behavior, improvement after a transformation, or performance
on Windows/Linux. A held-out sample and a separate test of correction outcomes
are needed before integrating any strategy into the adaptive flow.
