# Local missing-letter correction from a resolution probe

Date: 2026-11-01. A research trial improves the selected strict result from
93/113 (82.3%) to **94/113 (83.2%)**, with no image pass regression. The
80%-coverage count stays **107/113 (94.7%)**. The recovered flowchart already
exceeded 80%, so this is a small transcription improvement, not recovery of a
previously unread paragraph or one of the six cases below 80%.

## Method and cause

Run original images at 1.5x with Lanczos resampling through native PP-OCRv6
Tiny and the existing PDFMiner grouping. All 113 images receive a fresh probe;
the previous selected readings are reused and rescored with the unchanged
catalog. Weak OCR boxes do not trigger retries. No reference enters candidate
generation, routing, dictionary lookup or correction selection.

The previous exact-token retention guard rejected a useful change:
`partion` became `partition`, but preserving the old misspelling was a
condition for accepting the candidate. The new isolated research guard allows
letter additions under these conditions:

- The original word is alphabetic, has at least three letters and has native
  OCR confidence at least 0.9. Short anchors, numbers and codes retain the
  exact-token guard.
- The new word overlaps the original word by at least half the smaller box
  area, preserves every old letter in order, and has higher native confidence.
- The maximum wordfreq frequency across available languages is strictly
  higher for the new word. Missing optional language tokenizers are skipped.
- All other confident tokens survive the probe. A correction must map to one
  unique incumbent group; each new native observation can support only one
  correction.

Apply only the supported word substitution to the incumbent group. Preserve
the remaining incumbent text, including low-confidence content absent from
the probe. Do not replace the page with the probe output. These rules are
development heuristics, not a semantic guarantee. The three-letter condition
excludes ambiguous one- and two-letter anchors; the confidence and overlap
thresholds follow the earlier research retention and region-association rules.

## Full-suite result

| Measure | Previous selected result | Local correction |
| --- | ---: | ---: |
| Images evaluated | 113 | 113 |
| Strict reference passes | 93 | 94 |
| At least 80% word coverage | 107 | 107 |
| Tolerant matched reference words | 4,041/4,175 | 4,042/4,175 |
| Exact matched reference words | 3,798/4,175 | 3,799/4,175 |
| Newly passing / regressed images | — | 1 / 0 |

`data_ingest_flow.png` changes `partion` to `partition`, with native confidence
0.99468 to 0.99818. The recorded maximum wordfreq values are 3.47 and 3.77.
Its reference score improves from 41/42 to 42/42, including exact matching.
Only this image changes. An insertion-only confidence/geometry rule without
dictionary evidence would also admit the incorrect `requests` to `regquests`
change in the logger screenshot; the dictionary check rejects it.

The 113 probes took about 137.5 seconds summed, including local grouping and
serialization in the research runner. This is additional work on top of the
cached baseline, not a production throughput measurement. Loading multilingual
wordfreq data can use substantial memory; prior research observed roughly
0.9–1.1 GB RSS when all language lists were loaded. The successful route made
zero API calls. An earlier proposed visual API review was rejected by automatic
approval before execution; the fully local route requires no image transfer.

## Validation boundary

The rule was developed after inspecting these development results. It has no
held-out validation, universal language guarantee or evidence that it fixes
the severe low-contrast, Anamorpher, Base64 or homoglyph failures. Higher
confidence and dictionary frequency can still favor an incorrect word or
change a rare name. Do not deploy an unconditional extra OCR pass based on
one recovered word. The public and default adaptive pipelines do not use this
isolated research module.

Artifacts and the complete 113-image selected results are in
`.llm-plans/ocr-resolution-2026-11-01/local-final-summary.json`. The preceding
baseline remains recoverable in `.llm-plans/ocr-upscale-guard-2026-11-01/`.

## Subsequent authorized Decisions comparison

After the user explicitly authorized repeating the previously blocked API
comparison, the original two insertion candidates were reviewed with
`gpt-6-luna`, using the actual image crops and OCR readings without reference
transcripts. The logger's `requests` to `regquests` proposal was rejected:
the model chose the original reading (returned confidence 0.70). For the
flowchart, it chose `partition` (returned confidence only 0.24) and then judged
the whole 1.5x candidate improved (returned confidence 0.96). The localized
word judgment is therefore weak evidence on its own. These confidence values
are provider outputs, not calibrated correctness guarantees.

The API route selects the full candidate for the flowchart and keeps the
incumbent for the logger. Rescoring all 113 selected results gives the same
94/113 strict passes, zero pass regressions, 4,042/4,175 tolerant matched words
and 3,799/4,175 exact matched words. The 80% count remains 107/113. This is
agreement with the local route, not a second additional recovered image.
The other 111 images reuse their saved selected OCR results; no new OCR
inference was required for this API comparison.

Three API requests completed in about 2.1 seconds summed, with three transport
attempts and a configured input-token estimate of $0.0005979. This excludes
the earlier OCR and local processing and is not an invoice. Requests and
responses are saved under the experiment's `decisions/` directory; API-selected
full-suite results are in `final-summary.json`.

## Upscaling options for further investigation

The measured 1.5x Lanczos probe is interpolation: it resamples existing pixels
without a trained reconstruction model. Neural super-resolution predicts finer
detail and needs a separate model and additional inference. OpenCV provides a
[local Python interface](https://docs.opencv.org/4.x/d5/d29/tutorial_dnn_superres_upscale_image_single.html)
for FSRCNN, ESPCN, EDSR and LapSRN. PaddleOCR also documents the text-specific
[Text Gestalt super-resolution model](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version2.x/algorithm/super_resolution/algorithm_sr_gestalt.en.md).
These sources establish implementation options, not gains on our dataset.
Predicted strokes can change a character; image sharpness alone is insufficient
evidence of OCR correctness. No trained super-resolution model has been tested
in this trial. A next comparison should measure OCR fidelity and latency against
Lanczos on the complete suite before adding another transformation route.
