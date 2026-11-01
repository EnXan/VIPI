# Group-wise OCR reading comparison

Historical result: the implementation was reverted at the user's request.
This report preserves the original protocol and results.

Date: 2026-11-01. This research experiment tests whether individually comparing
aligned text groups can recover useful upscaled OCR without replacing a whole
page. It is isolated from the default adaptive and product scanner flows.

## Protocol

Start with the previously measured guarded-upscaling comparison: 93/113
approved payload-reference cases pass. Preserve its outputs except for the
seven images where the prior model favored a 2x candidate but the global
confident-token guard rejected it. Compare those candidates locally by group.

A pair must overlap by at least 70% of the smaller box in original-image
coordinates and be the only overlap for each group in both directions. A
changed pair is reviewed only if the original group has a native OCR region
below 0.8 confidence or the candidate omits a token from a native region at or
above 0.9 confidence. These thresholds are exploratory. Missing or ambiguous
geometry is not automatically merged. The model gets both group readings and
the original image crop, never reference labels or scores, and makes an
independent candidate/incumbent/uncertain choice for each pair. Candidate is
substituted only on a positive decision, maintaining the incumbent group
position and overall group ordering; uncertain retains the incumbent and records
the alternative separately in the research artifact. Ambiguous pairings are
not substituted. Alternatives are **not** passed to the downstream detector in
this trial.

The seven images produced 31 eligible pairs, with other geometry ambiguous. A
single request per image was used, with one crop and question per eligible
pair. Reference scoring took place after the choices. All other images kept the
existing guarded-upscaling output. Detailed inputs, output choices, uncertainty
and full-suite accounting are in `.llm-plans/ocr-group-combine-2026-11-01/`.

## Results

| Measure | Previous guarded result | Group-wise combination |
| --- | ---: | ---: |
| Reference passes | 93/113 (82.3%) | 92/113 (81.4%) |
| Newly passing / regressed | — | 0 / 1 |
| Additional Decision requests | — | 7 |
| Additional configured API estimate | — | $0.0012142 |

Across 31 groups the model selected 15 candidate readings, 15 incumbent
readings, and one uncertain alternative. In the targeted incident/Base64 case,
it judged the encoded group uncertain; the current reading was retained and the
case remained 0/1. Another potentially relevant group was not uniquely aligned
and therefore could not be automatically replaced.

In the blurred invoice, the model selected `approver is travelling:Il dd the
signed eopy after payment.` over the incumbent `approver is travellig: Ill add
the signed eopy after payment.` The chosen reading failed to preserve the
reference `I’ll`; a previously passing image therefore regressed. This is an
observed model decision, not a reference-driven selection.

## Boundary and decision

The experiment did not improve the full-suite pass rate and is not enabled in
any active pipeline. Its one uncertain alternative is stored but not tested as
separate input to the injection detector; this result therefore cannot answer
whether multi-reading detection would improve scanner recall. The evaluation
uses prior saved OCR, selected model decisions and the same development suite;
it is not an independently held-out trial or a fresh 113-image OCR run.
Reference passes cover only annotated payloads, not all visible text. No
production latency, multilingual reliability or local decision-model behavior
was measured.
