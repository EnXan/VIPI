# ADR 0089 — Optional PNG low-bit statistics

Status: accepted for implementation and review, 2026-11-26. Refs #86.

## Context

The user requested PngLoader coverage. The
[project's defensive guidance](https://github.com/i014n/PngLoader#detection-guidance)
mentions chi-square analysis of low sample bits. It also describes multiple
placement variants, including keyed ones. Image statistics provide evidence
about a carrier's samples. The available guidance does not establish a
tool-specific signature or a result we can map to an injection verdict.
The [pairs-of-values analysis](https://www.informatik.htw-dresden.de/~westfeld/publikationen/ihw99.pdf)
by Westfeld and Pfitzmann explains the distributional hypothesis.

## Decision

Expose `--lsb-stats`, off by default, through the existing optional PNG LSB
reader. For each RGB channel of an eligible image, count the original samples
for each even/odd value pair. For each nonempty pair with counts `a` and `b`,
add `(a - b)² / (a + b)` to the Pearson chi-square statistic for equal counts.
Report it with the number of samples and nonempty pairs. Use all samples of
the static 8-bit RGB image. Optionally requesting both statistics and text
shares one decode in the LSB reader.

The terminal and JSON report show the statistics for forensic review. The
statistic does not carry a probability, threshold, or loader attribution.
It supplies no text to the detector. An unreadable requested inspection uses
the existing incomplete policy.

## Alternatives and consequences

An automatic verdict based on this statistic would require paired evidence,
a calibrated threshold and a demonstrated operational use case. More
specific loader attribution would require independent indicators. This change
adds a histogram pass with no additional model calls or dependencies and
leaves extraction of binary content outside the inspection.

## Validation boundary

The integration fixture checks exact balanced and imbalanced counts per RGB
channel, terminal and JSON output, and the detector call count. The exploratory
catalog check covered 202 benign-labeled 8-bit RGB PNGs. The lowest per-pair
statistic across the channels varied substantially. On the matched upstream
zsteg flower examples, both inert data variants had higher statistics than
the original across all three channels. This does not support an automatic
low-score rule on these examples. Real PngLoader attribution and detection
performance remain unverified.
