# Signal-gated OCR correction comparison

Date: 2026-11-01. This research comparison combines the balanced experimental
signal settings in `evaluation/extended_signals.py` with the existing
`adaptive-jev` profile (PP-OCRv6 Tiny, PDFMiner grouping, and OpenAI Decisions
`gpt-6-luna`). It is an experimental composition, not a wired product profile.

## Protocol

Use the same 113 images and verified original-only reference baseline as the
previous work. Images with an inspection signal or unavailable required
signal are sent to the existing adaptive assessment and correction profile;
images without a signal retain their saved original OCR. The selection is
made without references. A reference is used only after a final OCR reading
has been selected, using the same current catalog and `compare_words` metric.
The original baseline reference scores were independently recalculated against
the current catalog and agreed on all 113 pass/fail outcomes.

Of 113 images, 31 triggered inspection, two had unresolved evidence, and 80
had no trigger. Six of the 33 reviewed images reuse results from the previous
identical gated experiment; 27 were newly processed. The previously run cases
and newly processed cases are not a single contemporaneous fresh model run.
The experiment uses cached original OCR and signal decisions; the existing
adaptive profile then reran original OCR for reviewed images because these
research components are not yet connected into a shared execution pipeline.

## Results

| Measurement | Original baseline | Signal-gated correction |
| --- | ---: | ---: |
| Images passing payload-reference evaluation | 89/113 (78.8%) | 92/113 (81.4%) |
| Matched payload-reference words | 4,004/4,175 (95.9%) | 4,031/4,175 (96.6%) |
| Previously failing images recovered | — | 3 |
| Previously passing images regressed | — | 0 |

The three recovered cases are the mirrored/rotated text image and the blue and
orange Anamorpher images. Two more failing cases (cat and beach) received
model-selected transformations and partial word improvements, but remained
below a full reference pass. Three of the 33 reviewed images had previously
been scored by the same gated profile as recovered; they are not independent
confirmation of that profile's results.

Of 24 baseline failures, 16 were routed for review and eight retained the
original without a signal. Thirteen of the 16 routed failures remained below a
full reference pass. Ten of those 13 were judged `ready` by the assessment;
three more include partial or unsuccessful correction attempts. Seventeen
previously passing cases were reviewed, including two with unresolved signals;
all 17 still passed. A previously passing reference does not guarantee that
all visible text was read, so a review of it is not necessarily a true false
positive.

## Work and estimated cost

The 33 reviewed cases represent 49 OCR observations in the existing adaptive
runs, 46 logical Decisions requests and 46 recorded transport attempts. Six
runs are reused and 27 are new; the latter account for 33 OCR observations and
34 logical Decisions requests. The configured input-token estimate totals
$0.0112609 for all 33 reviewed results, including the six reused runs, or
$0.0083163 for the 27 new runs. These estimates are not invoices and exclude
local hardware and electricity. They also exclude the original baseline OCR,
signal extraction and earlier development experiments. The summed recorded
adaptive durations across 33 cases were 81.1 seconds, not an end-to-end
throughput or production-latency benchmark.

Artifacts include per-image selected OCR, reviews, raw run directories and a
full manifest in `.llm-plans/ocr-signal-end-to-end-2026-11-01/`. Six reused
runs are identified explicitly. The first sandboxed request failed before the
user-authorized network run; it is not counted as a successful API request.

## Boundary

The 30-image subset helped select thresholds, and several other images have
appeared in earlier development runs. Thus this is not a held-out production
estimate. The 113 cases are the current detection-evaluation selection, not
the entire 1,000-image OCR reference catalog. Payload-reference completion is
not full-image OCR accuracy or injection detection recall. A no-signal result
is not proof of complete OCR. No fully local selection model, fresh full-run
replication, Windows/Linux performance, text-free-image handling, or
production-scale latency was evaluated. The target of 90% payload-reference
pass rate has not been reached.
