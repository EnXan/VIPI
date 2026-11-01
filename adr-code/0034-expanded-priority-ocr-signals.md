# 0034: Expand the research priority cascade

Status: Accepted for research comparison, 2026-11-01.

## Supersedes

ADR 0033 compared three local research routing policies using 30 selected
images. It retained the existing adaptive profile under ADR 0032 and did not
select a policy for production. Its rationale was to investigate a cheaper
signal-based gate while separating missing evidence from clear evidence. The
maintainer has now selected the priority cascade for further research, so this
record replaces 0033 while retaining that research-only boundary.

## Decision and context

Extend the cascade with hypotheses based on a single low-confidence OCR
region, small recognized text boxes, symbol proportion, overlapping groups and
grayscale contrast within detected text boxes. Stop on the first triggered
signal; record unavailable inputs. Retain the original signals and the exact
previous 30-image sample as a comparison. The parameters are documented
experimental thresholds, including minimum word length and text length to
avoid basing evidence on isolated punctuation. They do not restrict OCR input.

The results in [EXTENDED_OCR_SIGNALS.md](../research/ocr_eval/reports/EXTENDED_OCR_SIGNALS.md)
show more known reference failures marked but also more passed references
marked. A one-region confidence trigger is particularly prone to false alarms.
This is insufficient evidence to select production thresholds or infer that
any correction succeeds. At the time of this decision, ADR 0032 and the active
adaptive profile remained unchanged. The later Research Workbench default is
recorded in [ADR 0044](0044-product-research-recovery.md). The alternative
policies and original results remain documented in
[OCR_SIGNAL_ARCHITECTURES.md](../research/ocr_eval/reports/OCR_SIGNAL_ARCHITECTURES.md).

## Alternatives and validation boundary

The other prototype policies are retained for comparison rather than wired to
the active flow. Detection/recognition mismatch, probe disagreement, local
orientation, regional blur/compression and language-aware uncertainty require
additional input or validation and are not claimed by this implementation.
Future integration requires held-out evaluation, appropriate backend-specific
thresholds, actual correction outcomes, cost measurements and language tests.
Payload references are not complete-image or injection-detection ground truth.
