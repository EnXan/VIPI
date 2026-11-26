# ADR 0087 — OpenStego RandomLSB as a detector reading

Status: accepted for implementation and review, 2026-11-26. Refs #86.
Extends [ADR 0086](0086-legacy-openstego-reading.md).

## Context

The user requested coverage of more PNG layouts. OpenStego's published
[0.8.6 release](https://github.com/syvaidya/openstego/releases/tag/openstego-0.8.6)
provides an independent RandomLSB reference. Its [pixel reader](https://github.com/syvaidya/openstego/blob/openstego-0.8.6/src/main/java/com/openstego/desktop/plugin/randlsb/RandomLSBInputStream.java)
uses Java's documented `Random` behavior and a fixed seed when no password is supplied.
Its [version 2 header](https://github.com/syvaidya/openstego/blob/openstego-0.8.6/src/main/java/com/openstego/desktop/plugin/lsb/LSBDataHeader.java)
contains an encryption-algorithm field in addition to the legacy fields. The
positioning sequence depends on the password when one is supplied.

## Decision

Probe both layouts on the original static 8-bit RGB PNG samples. Recognize
the RandomLSB v2 header with the upstream default position sequence. Read
its header and filename using one bit and its payload using the bit depth
declared in the header. Validate both bit capacities before consuming any
payload. Track used positions in a packed bitmap after a header match to keep
memory proportional to the image's capacity.

Treat the decoded text, binary data and unavailable payloads as in ADR 0086.
The `openstego_random_lsb` evidence kind and report key preserve provenance if
both OpenStego layouts occur in the same PNG. Password-dependent positioning,
compressed-text extraction, headerless LSB and PngLoader are outside this
decision. A header with a compression flag is reported as incomplete.

## Alternatives and consequences

Invoking the upstream Java application would introduce a runtime and a
process boundary on scanned images. A reader for the documented protocol
uses the PNG decode already performed by the legacy check and samples only a
short header on ordinary PNGs. Extraction scans more positions only on a
recognized header. Random sampling has additional CPU cost on dense payloads.

## Validation boundary

Reference images were made with the upstream 0.8.6 release using an inert
UTF-8 marker and a solid 59 by 37 RGB carrier. Uncompressed payloads at every
depth from one to eight bits per channel were recovered byte for byte. The default-compressed
fixture was reported as incomplete, and the unmodified carrier had no
OpenStego reading. The integration suite uses the two-bit and compressed
upstream-generated PNGs with fake inference. Production model quality,
password-dependent positioning and very large payloads were not measured.
Neither layout produced a reading on the 554 local catalog inputs.
