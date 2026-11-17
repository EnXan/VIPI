# ADR 0077: Sentence windows for the local decision models

Status: Accepted, 2026-11-15. Amends the d1 default threshold of
[ADR 0075](0075-calibrated-default-thresholds-for-local-detectors.md)
(40 becomes 45).

## Context and sources

After calibration ([ADR 0075](0075-calibrated-default-thresholds-for-local-detectors.md)),
d1 and Clef-Flash still miss most injections in long text. On the retained
Mistral development text, d1's detection rate falls with text length (threshold
50, by OCR characters): 72 % below 200, 33 % at 200–500, 16 % at 500–1000 and
7 % at 1000–2000. OpenAI stays at 72–98 % in every band. The misses are mostly
web pages, dashboards and code screenshots, where a short injected passage sits
in a page of ordinary text. The local model scores the whole page and the
passage is diluted.

The catalog's injection payloads have a median length of 24 words (p90 47 words).

An experiment (#67, Phase 1b) scored overlapping windows of whole sentences or
lines with d1. The final score was the maximum of the whole text and every
window. On local speed text at threshold 40, the development detection rate
rose from 40.1 % to 50.7 % with a window at every sentence (2453 extra checks
on 450 images). With a window about every 40 words it rose to 47.1 % (415
checks). The false positive rate stayed at 3.6 % in both cases.

Prompt Guard already scores overlapping 512-token windows natively and still
detects 16–19 %, so its limit is the model, not dilution. OpenAI already
detects most long texts.

## Decision

- d1 and Clef-Flash check each final OCR reading as a whole, as before, and
  additionally in **windows** (`windows` in
  [`evidence.py`](../src/vipi/detection/evidence.py)):
  - a window is an exact span of whole sentences or lines (split after `.`,
    `!` or `?` followed by whitespace, or at line breaks);
  - each window has at most **80 words**;
  - a new window starts once **40 words** have passed since the previous
    window's start, but never after the previous window's end.

  Text of at most 80 words gets no windows. A single sentence longer than 80
  words is one window.
- Window checks are ordinary detector checks with `kind: "window"`; whole-text
  checks have `kind: "text"`. The verdict is unchanged: any completed check at
  or above the threshold detects, and `injection_probability` is the maximum.
- Prompt Guard and the cloud detectors (OpenAI, Jev) do not get windows.
- d1 defaults to **45** (was 40); Clef-Flash stays at **8**.

## Why these numbers

- **80 words** covers the p90 payload (47 words) with surrounding context,
  while staying far shorter than the long texts where detection collapses.
  The experiment used this size.
- **40 words between starts:** with 80-word windows, every passage of up to 40
  words lies wholly inside at least one window. That covers the median payload.
  A window at every sentence found 3.6 points more on local speed text, but
  needed about six times as many checks.

These are measured application parameters, not model limits. They were chosen
on the development split.

## Results

Recall / false positive rate in %, `research.evaluate detect-text` with the
product code on retained OCR text. "Whole" means without windows.

d1 (development 227 injection / 223 benign images, test 50 / 54):

| Text | Whole, 40 | Windows, 40 | Windows, 45 |
| --- | --: | --: | --: |
| local speed, development | 40.1 / 3.6 | 46.7 / 3.6 | 43.2 / 2.2 |
| local balanced, development | 40.5 / 3.1 | 48.5 / 3.1 | 45.4 / 2.2 |
| Mistral, development | 44.9 / 3.6 | 54.2 / 3.6 | 52.4 / 2.2 |
| local speed, test | 44.0 / 5.6 | 48.0 / 7.4 | 44.0 / 5.6 |
| local balanced, test | 42.0 / 3.7 | 48.0 / 5.6 | 40.0 / 3.7 |

Clef-Flash on local quality text:

| Split | Whole, 8 | Windows, 8 | Windows, 9 |
| --- | --: | --: | --: |
| development | 47.6 / 3.6 | 56.8 / 4.0 | 55.5 / 3.1 |
| test | 52.0 / 3.7 | 52.0 / 3.7 | 48.0 / 1.9 |
| both | 48.4 / 3.6 | 56.0 / 4.0 | 54.2 / 2.9 |

At the same threshold, windows found 41 more injections in the four d1
measurements. They added one false positive: the same vintage car
advertisement on two test texts. For Clef-Flash they added one false positive
on development, an email asking for a phone number. Advertising addresses the
reader with imperatives, so it is a known false positive pattern for windows;
on Mistral text a window at every sentence also flagged a feng-shui
advertisement.

Threshold choice:

- **d1:** at 40 with windows, the local speed test split reached 7.4 % false
  positives, against the 5 % target of ADR 0075. Three of those four benign
  images were already flagged without windows. At 45, d1 with windows beats
  the previous default (whole text, 40) on recall and false positives on every
  development text and over both splits (local speed: 43.3 / 2.9 instead of
  40.8 / 4.0). On the balanced test split it detects one injection fewer
  (40.0 % instead of 42.0 %). 45 was chosen after seeing the test split, so the
  test split is not an independent estimate for it.
- **Clef-Flash:** 8 stays within the target on both splits (4.0 % and 3.7 %).
  9 would trade about 2 points of recall for about 1 point fewer false
  positives.

Extra checks: d1 made 415 window checks on local speed development text and 774
on Mistral text, for 450 images. Clef-Flash made 439 on development and 82 on
test. On the Apple M2, a d1 check takes about 0.8 s. Median detection time per
image stayed at 0.74 s; the mean rose to 1.7 s on local speed text and 2.7 s on
Mistral text, because only images with long text get windows. On the M4 Pro a
Clef-Flash check takes about 2 s.

## Alternatives

- **A window at every sentence.** Rejected for now: 3.6 points more on local
  speed text for about six times the checks, and many more on long Mistral
  pages (up to about one window per sentence).
- **Windows for the cloud detectors.** Not adopted: OpenAI already detects
  72–98 % in every length band, and every window is a paid request. Not
  measured.
- **Split only the API chunks smaller.** The existing chunks bound request size
  (16,000 JSON bytes). They do not follow sentence boundaries and cover almost
  every OCR text in one piece. Windows serve detection, not request limits.
- **Keep d1 at 40.** Rejected: 3.6 points more on local speed development text,
  but above the false positive target on the test split.

## Consequences

- Local scans of images with long text make more detector checks and take
  longer; images with short text are unchanged.
- The saved detection result (`detection/<id>/result.json`) lists every check
  with its kind and span, so the highest-scoring window shows which passage
  caused a finding. The CLI report is unchanged.
- End-to-end development baselines with this decision (Apple M4 Pro, commit
  `94abd343`), recall / false positive rate in %, before (ADR 0075) and after:
  - local speed with d1: 39.6 / 3.6 → 43.2 / 2.2;
  - local balanced with d1: 40.5 / 3.1 → 45.4 / 2.2;
  - local quality with Clef-Flash: 47.6 / 3.6 → 56.8 / 4.0.

  They match the `detect-text` results above exactly. Median time per image
  rose from 3.1 to 3.7 s (speed), 4.1 to 5.0 s (balanced) and 14.8 to 16.1 s
  (quality). The README results show these baselines.
- Passages longer than the window size, and instructions split over distant
  parts of an image (`split_text`), are not helped by windows.

## Validation boundary

- Unit and integration tests cover:
  - window spans and the word limit;
  - that every passage of up to 40 words lies inside one window;
  - that long sentences leave no gap;
  - that only d1 and Clef-Flash get windows;
  - that a window alone can detect.
- The window count on retained local speed development text matches the
  experiment exactly (415).
- Measured with `detect-text` on retained OCR text, on Apple M2 (d1: local
  speed and Mistral development, local speed and balanced test) and Apple M4
  Pro (d1: local balanced development; Clef-Flash: development and test).
  Test-split runs were the one-time confirmation for this decision.
- End-to-end development baselines for the three local default
  configurations on one Apple M4 Pro.
- Linux, Windows and CUDA are not measured.
