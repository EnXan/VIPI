# ADR 0074: Detector-only evaluation on retained OCR text

Status: Accepted, 2026-11-15.

## Context and sources

Local configurations detect 15–19 % of injection images on the development
split, cloud configurations 74–85 %
([baselines](../research/baselines), [README results](../README.md#performance)).
An audit of the retained detector inputs (`detection/*/inputs.json`) for
[issue #68](https://github.com/EnXan/VIPI/issues/68) showed that every
existing detector pair already saw byte-identical text: Prompt Guard against d1
on local speed and balanced OCR, Prompt Guard against Clef-Flash on local
quality OCR, and OpenAI against Jev on each cloud OCR. On the same text the
detectors differ by 3–5 points. No local detector has seen cloud OCR text, so
it is unknown whether the local gap comes from OCR or from the detector
([issue #67](https://github.com/EnXan/VIPI/issues/67)).

Evaluation runs reuse earlier OCR only when its OCR identity matches the
current checkout: OCR model, mode, review provider, OCR sources and packages
([ADR 0058](0058-reuse-ocr-across-runs.md),
[`ocr_reuse.py`](../research/ocr_eval/ocr_reuse.py)). Since the cloud baselines
were recorded, 13 OCR sources changed, so a new configuration with cloud OCR
would scan and pay for OCR again. Product scan options also reject a local
detector with cloud OCR ([`config.py`](../src/vipi/config.py)), so such a
combination cannot be a regular configuration.

## Decision

- `research.evaluate detect-text RUN_ID --detector DETECTOR` restores each
  image's OCR result from a complete source run (`ocr_reuse.restore`, checked by
  the result hash) and runs only the chosen detector on it, with the product's
  detection settings and default threshold. No OCR runs.
- The OCR identity check of ADR 0058 is deliberately not applied: the point is
  to hold the text fixed, whatever code produced it. Each row records whether
  the detector received the same texts as the source run's detector
  (`same_text_as_source`); the command exits 1 when any text differs or any
  image failed.
- Results are scored with the existing detection metrics
  (`benchmark_report.detection_summary`) and written to
  `runs/detector-text/<run>--<detector>/` with the request and provenance.
  They are not baselines and do not change saved baselines or the README
  end-to-end results.

## Alternatives

- **New configurations with cloud OCR and a local detector.** Rejected: the
  product rejects the combination, and changed OCR sources would rerun paid OCR.
- **Relax the OCR identity in ADR 0058.** Rejected: end-to-end runs must keep
  reusing OCR only when it would be the same; that guarantee stays.
- **Feed detectors the dataset reference text.** Rejected: references are
  scoring data only and would remove OCR errors that real scans contain.

## Consequences

- Detector comparisons on identical text cost only detector time (local) or
  detector fees (cloud), and can include detectors the product does not allow
  with that OCR, such as Prompt Guard on Mistral text.
- Results describe the detector on text from the OCR code of the source run,
  not on text the current OCR code would produce.

## Validation boundary

Validated on the development split on an Apple M2 (16 GB):

- Prompt Guard on retained local speed text reproduced the saved
  local-speed-prompt-guard baseline: recall 18.5 %, false positive rate 2.2 %,
  450 of 450 images on the same readings.
- On the retained cloud-mistral text, where OpenAI reaches 85.0 % recall, Prompt
  Guard reaches 16.3 % (2.2 % false positives) and d1 15.9 % (0.4 %), 450 of 450
  images on the same readings. The local gap therefore comes from the
  detectors, not from local OCR.
- d1 first failed on 125 images with MPS out-of-memory errors while other work
  used the GPU; such rows count as failed and run again on resume.

Unit tests cover source loading, resuming, retrying detector errors, request
checks and scoring with a fake detector. Clef-Flash needs about 19 GB and was
not run; cloud detectors were not run through this command.
