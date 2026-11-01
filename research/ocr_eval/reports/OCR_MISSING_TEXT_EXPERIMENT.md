# Missing-text and separate-evidence experiments

Date: 2026-11-01. Four targeted research steps were evaluated using all 113
cases from the previous guarded 93/113 OCR comparison. The public product and
default adaptive profile are unchanged. Original OCR and prior decisions were
reused; this is complete suite accounting, not a fresh full OCR run.

## 1. Suspected undetected areas

For the 27 images already receiving a 2x OCR probe, compare candidate word-box
positions with the selected original OCR regions. Flag candidate words at least
two characters long with confidence at least 0.8 when less than 25% of their
box overlaps any incumbent box; combine flagged words by candidate line. These
are experimental signal thresholds, not proof that the pixels contain missed
text. The selection uses no references.

On the 113-image accounting, eight images triggered, 19 probed images had no
trigger, and **86 were not probed**. Of the eight triggered, two failed and six
passed the existing payload-reference test. There were 43 suspect lines. This
is not a cheap first-pass text detector: it relies on an already executed second
OCR and cannot detect text missed by both observations. Other 86 images must
not be treated as clear. Symbols and OCR noise caused obvious suspect boxes.

## 2. Targeted local rereading

For the 43 suspect line boxes, crop the original image with one line height of
context and try two independent local PP-OCRv6 Tiny readings: bicubic 2x and
`green-minus-red` followed by bicubic 2x. Preserve their text, crop coordinates
and transform as separate observations; do not overwrite the incumbent OCR.
The 86 local OCR calls took about 14.7 seconds summed on the local machine;
only six produced nonempty text, all using plain 2x. The color-derived version
produced no nonempty result in this trial. On the two reference-failing cases
that triggered this sensor, the nonempty crop readings did not match any of
the reference words previously missing, in a separate lexical-only diagnostic.
This neither proves absence of text nor establishes general performance of the
transforms; the derived boxes and crops may be poor.

The primary output was not changed: reference passes remain 93/113 and matched
reference words remain 4,041/4,175. Six cases have less than 80% reference-word
coverage under this exploratory reporting threshold. Word coverage can reflect
ordering and grouping errors, not only invisible text. Long encoded payloads
may count as one word, so this statistic must not be treated as whole-image
completeness or an attack-recall measure.

## 3. Retain alternate readings and test a local detector

Use distinct provenance-bearing readings: selected OCR plus a separate 2x page
reading when the new-area sensor triggered or the previous confident-token
guard rejected a model-preferred candidate; include nonempty localized crop
readings as separate inputs. Identical text is deduplicated while preserving its
sources. Never concatenate variants into a constructed sentence. Twelve images
have at least one distinct alternate; 132 independent readings were checked
across the suite, including 20 alternatives and 112 nonempty primary readings.
One primary reading was empty and remains incomplete.

Run the existing local Prompt Guard 2 86M on each reading with native token
windows. Evaluate primary alone and then primary plus alternatives using the
existing `verdict.summarize` logic. A fixed 0.5 threshold was chosen for this
research comparison; it is not a validated product threshold. Uncertainty and
partial context remain explicit. Classification is local, no API fee; local
compute is not free.

| Category (caller context withheld) | Images | Primary flagged / not flagged / unclear | With alternatives |
| --- | ---: | --- | --- |
| Injection in all catalog cases | 32 | 9 / 19 / 4 | 9 / 19 / 4 |
| Benign in all catalog cases | 28 | 0 / 28 / 0 | 0 / 28 / 0 |
| Context-dependent | 53 | 4 / 44 / 5 | 4 / 44 / 5 |
| **All images** | **113** | **13 / 91 / 9** | **13 / 91 / 9** |

No image-level verdict changed. The 53 context-dependent images cannot be
scored as unambiguous true or false positives without their caller context.
These are descriptive results for one classifier, one experimental threshold,
a deliberately selected development dataset and a context-free protocol; they
are not VIPI's overall production attack-recall or false-positive rate. All
132 checks completed. The two additional code-crop readings described below
were included in these counts.

When evaluated **separately against the reference after selection**, two of
the 20 alternate OCR readings for previously failed cases cover the tolerant
reference: the 2x page and one code crop of the Base64 incident. This
is a potential recovery opportunity, not an additional selected OCR pass or an
improved detector verdict. Both have 0/1 exact reference words: the long
encoded token is tolerated as a near match by the existing word metric and must
not be represented as exact, decodable, or correct.

## 4. Code-like text fidelity

As an extra weak signal, compare spatially overlapping OCR groups between the
primary and 2x reading. Report disagreement in long code-like runs (at least
24 characters) without claiming they are Base64, malformed or malicious. The
length is an exploratory signal to reduce ordinary-word noise, not an input
limit. Among the 12 images with a 2x alternative, one triggered: the Base64
incident. Eleven showed no such code disagreement; the other 101 images were
not evaluated by this particular comparison and are not clear by implication.

Retry the two signaled code-region boxes using the same two localized
transforms: four additional local OCR calls, two nonempty. Both nonempty crops
are preserved as separate detector readings. One passes the tolerant 1-word
payload-reference test but is not an exact reference match. The selected OCR
still fails that reference, and the local detector outcome remains `unclear`
for this context-dependent image. No automatic code correction or decoding is
performed, and short codes/URLs are outside this preliminary signal.

Artifacts and reproducibility protocols are in
`.llm-plans/ocr-missing-text-2026-11-01/`. The current 93/113 figure is a
same-development-set OCR score, not a held-out estimate, and this trial does
not claim improved attack detection, invisible-text localization, or a local
production-ready policy. Further work should investigate why tight crops often
produce no OCR output and how to find image regions missed by both current
readings before incurring a second full-page pass.
