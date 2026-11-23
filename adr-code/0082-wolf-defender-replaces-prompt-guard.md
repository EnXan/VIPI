# ADR 0082: Wolf Defender replaces Prompt Guard as the local text classifier

Status: Accepted, 2026-11-22. Replaces
[ADR 0061](#replaced-adr-0061) and amends the default thresholds of
[ADR 0075](0075-calibrated-default-thresholds-for-local-detectors.md).
Refs #67, #65.

## Context and sources

VIPI had one small local text classifier, Prompt Guard 2
(`meta-llama/Llama-Prompt-Guard-2-86M`). On the development split it detected
18.9 % of attacks at 2.2 % false positives (threshold 80) on retained local
speed OCR text, and at most 27.8 % at 4.9 % at its best threshold (12)
([ADR 0075](0075-calibrated-default-thresholds-for-local-detectors.md)). Its
weights are gated: downloads need accepted Llama 4 Community License terms and
a Hugging Face token, so the repository's `vipi-scan.yml` workflow needed the
`HF_TOKEN` secret and could not scan pull requests from forks.

On 2026-11-22 small, local, ungated classifiers were measured on retained OCR
text only (no OCR runs, no paid calls; scratchpad harness that rebuilds the
product's jobs, verified by reproducing Prompt Guard's stored rates exactly).
Recall / false positive rate in %, development split, local speed text:

| Model (revision) | License | at 80 | best at ≤ 5 % FP | AUC |
| --- | --- | --: | --: | --: |
| Prompt Guard 2 86M (`a8ded8e6`) | Llama 4, gated | 18.9 / 2.2 | 27.8 / 4.9 | .79 |
| Wolf Defender small (`2484cc9a`) | Apache-2.0 | 38.3 / 3.1 | 47.6 / 4.9 | .85 |
| Horizon guard small (`2efc2ed5`) | Apache-2.0 | 27.8 / 4.5 | 28.6 / 4.9 | .76 |
| Horizon guard base (`fc071c57`) | Apache-2.0 | 30.4 / 6.7 | 27.8 / 4.5 | .77 |
| ProtectAI DeBERTa v2 (`90c9989b`) | Apache-2.0 | 35.2 / 12.6 | 26.4 / 4.5 | .65 |
| PIGuard (`dd78b24e`) | MIT | 18.9 / 11.2 | 7.0 / 2.7 | .65 |

d1 3B at its default 45 reaches 45.4 / 2.2 on the same text. Sentinel v1/v2
(license "other", gated), testsavant defender (no license) and a zero-download
fork were not evaluated; Mezzo small gave a constant output in Transformers
5.22. Wolf Defender's vendor pooling (2048-token windows, smooth-max) gave the
same scores as 512-token windows with max on VIPI's texts: only 13 of 450
local texts exceed one 512-token window.

Wolf Defender small is a 141M-parameter mmBERT-small (ModernBERT) sequence
classifier with labels `BENIGN`/`INJECTION`, trained on English and German
public datasets that, per its card, do not include VIPI or its sources (not
verified beyond the card). The pinned revision was published on 2026-11-09.

## Decision

- `--detector wolf-defender` replaces `--detector prompt-guard`
  (`vipi setup` and `vipi scan`). Prompt Guard's provider, setup, revision
  constant and option are removed. `auto` is unchanged (d1 or Clef-Flash).
- The provider (`detection/providers/wolf_defender.py`) keeps Prompt Guard's
  contract: an explicit setup download of the revision pinned by
  `WOLF_DEFENDER_REVISION`, a SHA-256 manifest, offline loading without remote
  code, FP32 on CPU, 512-token windows with 64 tokens overlap and the maximum
  `INJECTION` probability over windows. Setup downloads only seven named root
  files (`config.json`, the three tokenizer files, `model.safetensors`,
  `LICENSE`, `README.md`); the repository's ONNX exports, pickled checkpoint
  and `inference.py` are not downloaded. The label mapping must be
  `{0: BENIGN, 1: INJECTION}`.
- Default threshold **40** (`DETECTOR_THRESHOLDS`). See *Threshold* below.
- The evaluation configurations `local-{speed,balanced,quality}-prompt-guard`
  become `local-{speed,balanced,quality}-wolf-defender` with the same OCR and
  review settings, and record the Wolf Defender repository and revision as
  `detector_models` (unchanged mechanism of ADR 0061). The workbench offers
  Wolf Defender in place of Prompt Guard. `detect-text` accepts
  `wolf-defender`.
- `vipi-scan.yml` uses `detector: wolf-defender` and no longer passes
  `HF_TOKEN`.

### Threshold

Measured with `research.evaluate detect-text --detector wolf-defender` through
the product path on retained OCR text (dev: 227 attacks / 223 benign; test:
50 / 54, one benign image = 1.85 %):

| Threshold | speed dev | speed test | speed both | balanced test | Mistral dev |
| --: | --: | --: | --: | --: | --: |
| 10 | 45.8 / 4.0 | 40.0 / 11.1 | 44.8 / 5.4 | 34.0 / 5.6 | 58.6 / 2.2 |
| 15 | 45.8 / 4.0 | 40.0 / 7.4 | 44.8 / 4.7 | 34.0 / 5.6 | 58.1 / 2.2 |
| 20 | 44.9 / 4.0 | 36.0 / 5.6 | 43.3 / 4.3 | 34.0 / 5.6 | 57.3 / 2.2 |
| 30–40 | 41.4 / 3.6 | 36.0 / 5.6 | 40.4 / 4.0 | 34.0 / 5.6 | 56.4 / 2.2 |
| 50 | 41.4 / 3.6 | 32.0 / 5.6 | 39.7 / 4.0 | 32.0 / 5.6 | 56.4 / 2.2 |
| 80 | 38.3 / 3.1 | 28.0 / 5.6 | 36.5 / 3.6 | 28.0 / 5.6 | 52.9 / 2.2 |

The development split alone pointed to 10. The test split rejected it
(11.1 %). From 20 to 80 the test split has the same three false positives.
Two, with scores of 0.88 and 1.0, are dashboards whose benign notes are
base64 (decoded by ADR 0079, for example "Ignore it when comparing months");
the third (0.84) is mirrored OCR noise. So every
threshold up to 80 exceeds 5 % on the test split by one image, while both
splits together stay at or below 4.3 %. 30 and 40 give identical results on
all four texts; 40 keeps the most distance from the steep region below 20
without losing recall. It was chosen after seeing the test split, so the test
split is no independent estimate for it.

## Alternatives

- *Keep Prompt Guard next to Wolf Defender*: rejected by the maintainer;
  Prompt Guard is weaker on every measured text and needs a gated download.
- *Threshold 50 (the vendor's default)*: same false positives as 40 on every
  text, up to 4 points less recall (0.7 over both speed splits).
- *Threshold 20*: 2.9 points more recall over both speed splits, one more
  development false positive and one step from the test-split jump at 15.
- *The vendor's `inference.py` or its ONNX/INT8 exports*: the vendor code
  gave identical scores; running third-party code is not needed for that. The
  `_x86` INT8 export (about 96 MB, no PyTorch) may help CI install time and is
  left to the OCR/CI speed work (#65); it was not measured.
- *Wolf Defender as the default local detector*: not decided; it detects less
  than d1 at 45 on development text (41.4 vs 45.4 %), on the test split and in
  the end-to-end speed and balanced runs (41.4 vs 43.2 %, 44.1 vs 45.4 %), at
  more false positives.

## Consequences

- `--detector prompt-guard` and `PROMPT_GUARD_REVISION` no longer exist (minor
  version bump). Existing `prompt-guard/` cache folders are no longer used and
  can be deleted.
- No Hugging Face token is needed for any VIPI model. Wolf Defender weighs
  563 MB instead of 1.1 GB; `detect-text` took 46 s for 450 images (about
  0.03 s per image, 4 threads, Apple M2) with 1.0–1.2 GB peak RSS.
- The CI scan gets about twice Prompt Guard's recall. Its run time does not
  change noticeably: the detector took about 0.1 s per image, while the last
  run spent 59 s in setup and 7 min 44 s on three images, dominated by OCR
  (#65).
- End-to-end development baselines (Apple M4 Pro, commit `6600c048`, clean
  tree): `local-speed-wolf-defender` 41.4 % recall at 3.6 % false positives
  (Prompt Guard 18.5 / 2.2, d1 43.2 / 2.2) and `local-balanced-wolf-defender`
  44.1 / 3.1 (Prompt Guard 16.7 / 1.8, d1 45.4 / 2.2), with the same words
  recognized as the Prompt Guard runs (70.0 % and 72.3 %). The speed run
  reproduces the `detect-text` rate at 40 exactly. The README results table
  and `vipi-results.svg` show both; `local-quality-wolf-defender` is not
  recorded yet, so its row still shows the last Prompt Guard baseline, marked
  as removed.
- The three saved `-prompt-guard` baselines stay as historical records.

## Validation boundary

The threshold comes from retained OCR text through the product provider. The
speed and balanced rates are also confirmed by end-to-end development runs; the
quality configuration (Clef-Flash review) has no Wolf Defender run yet. No GitHub runner (Linux, x86) run has
been measured yet; the vendor warns that its INT8 ONNX files can misbehave on
some x86 CPUs, which does not apply to the FP32 safetensors used here. Tests
cover the manifest and checksum, the label check, windowing, offline loading
of a tiny ModernBERT fixture, setup with the pinned revision, the threshold
default and the renamed configurations.

## Replaced ADR 0061

ADR 0061 (accepted 2026-11-10, extending ADR 0057) added the evaluation
configurations `local-speed-prompt-guard`, `local-balanced-prompt-guard` and
`local-quality-prompt-guard`: the local configuration plus
`detector: prompt-guard` with unchanged OCR, review and threshold, Prompt
Guard 2 in the workbench detector field for every local OCR size, and the
detector's repository and pinned revision as `detector_models` in the model
identity so that a revision change turns its baselines stale. Rationale: the
user asked to make Prompt Guard selectable for evaluation after ADR 0055
removed the workbench's multi-detector comparison. It is replaced because
Prompt Guard is removed; the same mechanism now serves Wolf Defender.
