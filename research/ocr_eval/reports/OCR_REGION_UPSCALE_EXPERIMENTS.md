# Local retries and guarded upscaling experiments

Date: 2026-11-01. The user authorized iterative experiments and combinations
until the first measured improvement, with a full 113-image comparison after
each change. These are isolated research experiments; they do not change the
product or the default adaptive OCR profile.

## Common comparison

Compare the same 113 approved payload-reference cases against the preceding
signal-gated result of 92/113 passes. Previous selected OCR and model decisions
are reused for unaffected cases. No reference transcript, label, score or
image identity is used to select an OCR candidate. The current reference
metric is applied only after the selection. These are full-suite accountings,
not fresh OCR inference for every case, independent test sets, or security
attack-recall measurements.

## Attempts

| Experiment | Passes | Newly passing / regressed | Additional work | Observation |
| --- | ---: | ---: | --- | --- |
| Local re-OCR of low-confidence word crops, confidence-based selection | 92/113 | 0 / 0 | 46 local crop OCR calls | Changed 11 images; some replacements damaged correct non-reference text, such as `Orders` becoming `Ordt`. |
| Review changed word crops with Decisions | 92/113 | 0 / 0 | 46 local crop OCR calls, 11 Decisions requests | Decisions rejected many incorrect replacements, but no additional reference passed. |
| Whole-image 2x bicubic OCR only for `small_text` | 92/113 | 0 / 0 | 8 local OCR calls, 8 Decisions requests | One model-selected result was still a reference pass; no failed reference became passing. |
| 2x OCR for broader signaled/uncertain cases | 93/113 | 2 / 1 | 27 local OCR calls, 27 Decisions requests | One previously passing case lost a reference word despite the model selecting the candidate. |
| Broader 2x plus confident-token retention check | **93/113** | **1 / 0** | 27 local OCR calls, 27 Decisions requests, no extra model calls for the check | One of eight model-preferred candidates passed the local check. |

The source outputs and protocols are under `.llm-plans/ocr-region-retry-2026-11-01/`,
`.llm-plans/ocr-region-review-2026-11-01/`,
`.llm-plans/ocr-upscale-route-2026-11-01/`,
`.llm-plans/ocr-upscale-broad-2026-11-01/` and
`.llm-plans/ocr-upscale-guard-2026-11-01/`. A subsequent eight-request visual
recheck of candidate text loss rejected all eight candidates, including both
reference-recovering candidates, so it did not improve the pass count.

## Guarded candidate

The broader route uses the balanced priority signals. On a signaled or
unresolved case, it tries 2x bicubic OCR only if the prior route retained the
original and the input is within the existing 8,000,000-pixel two-times OCR
boundary. Previously corrected readings and other cases retain the incumbent.
The model compares the actual image and both actual OCR results; only an
`improved` response creates a prospective replacement.

A local guard then checks whether every case-folded Unicode word token from
incumbent native regions with confidence **at least 0.9** appears in the new
transcription with at least the same multiplicity. It rejects the new reading
if any such token is missing. The guard does not use references and does not
make a security verdict. It can reject real corrections to confidently wrong
incumbent text; indeed it rejected one of the two otherwise recovered cases.
It cannot prove that other text is correct or that all visible text is present.

The 0.9 threshold and guard were chosen **after inspecting this development
suite and the observed regression**. The 93/113 result is therefore
exploratory and susceptible to overfitting, not independent validation. A
separate untouched image set and backend-specific calibration are needed.

The recovered case `sting_logger_dependency_story_...` improved from 199/209
to 209/209 reference words: the upscaled reading recovered a previously missing
command sequence. The tested metric reports zero previously passing references
regressed, but it only evaluates approved payload text; it cannot establish
that all other visible text is unchanged or more accurate.

## Cost boundary

The guarded route reuses the preceding 33 reviewed cases' 46 Decisions requests
and estimated $0.0112609 and adds 27 local OCR passes and 27 Decisions requests
estimated at $0.0230895. The sum is **73 Decisions requests and approximately
$0.0343504** for the reconstructed comparison. The 27 upscaled OCR observations
took about 37 seconds summed on this machine; this omits original OCR, setup,
signal computation, local hardware/electricity, prior experiments and
end-to-end timing. Configured estimates are not invoices. Earlier rejected
research runs add separate cost. This route is substantially more expensive than
the preceding comparison; no production throughput, Linux/Windows, offline
selection or scaling claim follows.
