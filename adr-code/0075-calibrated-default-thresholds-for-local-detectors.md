# ADR 0075: Calibrated default thresholds for the local decision models

Status: Accepted, 2026-11-15. Amends the threshold default of
[ADR 0003](0003-public-cli-contract.md).

## Context and sources

[ADR 0003](0003-public-cli-contract.md) set one finding threshold for every
detector: 80 of 100, equality counts as a detection, and a threshold is a
decision policy rather than calibrated attack confidence. It recorded no
calibration; [ADR 0054](0054-evaluation-runs-and-baseline.md) kept evaluations
at that default and noted that threshold calibration needs its own work.

On the development split (227 attacks, 223 benign images) the local
configurations detect 15–19 % of injections at 80 while cloud detectors reach
74–85 % ([baselines](../research/baselines)). Running the local detectors on the
retained Mistral OCR text with `research.evaluate detect-text`
([ADR 0074](0074-detector-only-evaluation-on-retained-ocr-text.md)) showed
that the gap comes from the detectors, not from OCR. The retained scores show
that the local decision models score most injections far below 80.

d1, recall / false positive rate in %, on retained local OCR text
(development 450 images, test 104 images: 50 attacks, 54 benign):

| Threshold | speed dev | speed test | speed both | balanced dev | balanced test | balanced both |
| --: | --: | --: | --: | --: | --: | --: |
| 80 | 15.0 / 0.4 | 16.0 / 0.0 | 15.2 / 0.4 | 15.4 / 0.4 | 20.0 / 0.0 | 16.2 / 0.4 |
| 45 | 37.4 / 2.2 | 40.0 / 3.7 | 37.9 / 2.5 | 37.0 / 2.2 | 38.0 / 1.9 | 37.2 / 2.2 |
| 40 | 40.1 / 3.6 | 44.0 / 5.6 | 40.8 / 4.0 | 40.5 / 3.1 | 42.0 / 3.7 | 40.8 / 3.2 |
| 35 | 42.7 / 3.6 | 46.0 / 7.4 | 43.3 / 4.3 | 42.3 / 3.1 | 42.0 / 7.4 | 42.2 / 4.0 |

On the retained Mistral text, d1 reaches 44.9 / 3.6 at 40 (development).

Clef-Flash on retained local quality OCR text:

| Threshold | dev | test | both |
| --: | --: | --: | --: |
| 80 | 16.7 / 0.0 | 14.0 / 0.0 | 16.2 / 0.0 |
| 10 | 44.9 / 2.7 | 44.0 / 1.9 | 44.8 / 2.5 |
| 8 | 47.6 / 3.6 | 52.0 / 3.7 | 48.4 / 3.6 |
| 7 | 51.5 / 4.5 | 56.0 / 3.7 | 52.3 / 4.3 |

The test-split false positives at these thresholds are benign sentences with
injection trigger words, for example "Forget everything you learned about
sourdough…", "Delete the old drafts folder…" and "Execute the plan in three
phases…".

Prompt Guard stays at 26–27 % recall even at its best threshold with at most
5 % false positives on the development split, and combining it with d1 does
not raise recall at that false positive rate, so its default is not changed
here. The cloud detectors (OpenAI, Jev) reach 74–85 % at 80 with at most 4.5 %
false positives.

## Decision

- Each detector has a default threshold. d1 defaults to **40** and Clef-Flash
  to **8**; Prompt Guard, Jev and OpenAI keep **80**
  (`DETECTOR_THRESHOLDS` in [`config.py`](../src/vipi/config.py)).
- Operating point: the highest recall with at most 5 % false positives, with a
  margin below that limit, on every retained text the detector is used with.
- `--threshold` (and `ScanOptions.threshold`) stays an explicit override for
  every detector; without it the detector's default applies. Reports record the
  threshold actually used.
- Selection: on the development split the candidates were 35 for d1 and 8 for
  Clef-Flash. The one-time test-split confirmation (`research/splits.json`)
  held for Clef-Flash. For d1, 35 reached 7.4 % false positives on the test
  split (4 of 54 benign images); the maintainer chose 40, which stays at or
  below 4.0 % over both splits. Because 40 was chosen after seeing the test
  split, the test split no longer gives an independent estimate for d1.

## Alternatives

- **One lower threshold for every detector.** Rejected: the cloud detectors are
  well placed at 80, and a value such as 40 would raise their false positives.
- **Keep 80 and document `--threshold`.** Rejected: users of the default local
  quality scan would keep a detector that finds one in six injections.
- **d1 at 35.** Rejected: 1.5–2.5 points more recall, but above the false
  positive target on the test split and with less margin over both splits.
- **Calibrate scores into probabilities.** Rejected for now: a fixed operating
  point per detector meets the requirement without a fitted model and keeps
  scores as the detectors report them.

## Consequences

- Local default scans find about two and a half to three times as many
  injections at about 3–4 % false positives. End-to-end development baselines
  with the new defaults (Apple M4 Pro, commit `0f121796`): local speed with d1
  39.6 / 3.6 (was 15.0 / 0.4), local balanced with d1 40.5 / 3.1 (was
  15.4 / 0.4), local quality with Clef-Flash 47.6 / 3.6 (was 16.7 / 0.0). They
  match the retained-score selection within one image and replace the earlier
  README results.
- Callers that pass `--threshold 80` explicitly, such as the GitHub Action's
  `threshold` input default up to v1.2, keep the old behavior until they stop
  passing it.
- The remaining false positives are benign trigger-word sentences
  (over-defense); a better detector, not a threshold, has to fix them (#67).
- Scores are not comparable across detectors; a threshold below 10 makes
  Clef-Flash's scale visibly different from the others.

## Validation boundary

Chosen from retained scores: d1 on local speed and balanced OCR text (Apple M2)
and on Mistral text, Clef-Flash on local quality OCR text (Apple M4 Pro), on
the development split and once on the test split (104 images, so one false
positive moves the benign rate by 1.85 points). Unit tests cover the resolved
defaults and the explicit override. End-to-end development baselines with the
new defaults are recorded for the three local default configurations on one
Apple M4 Pro; other hardware, Linux and Windows are not measured.
