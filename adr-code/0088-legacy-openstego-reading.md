# ADR 0088 — Legacy OpenStego text as a detector reading

Status: accepted for implementation and review, 2026-11-26. Refs #86.
Amends the verdict scope in [ADR 0071](0071-scan-verdict-and-final-ocr-completeness.md).

## Context

[Aperi’Solve](https://github.com/Zeecka/AperiSolve#analyzers) runs zsteg on
PNGs and exposes its analyzer output to agents via
[MCP](https://github.com/Zeecka/AperiSolve/blob/main/docs/mcp.md#the-intended-loop).
Text recovered by a tool is untrusted input that may reach an agent. The
maintainer agreed to start with one documented layout. The
[zsteg tests](https://github.com/zed-0xff/zsteg/blob/b75b578ea13ed207561a46b8620b843c0a894422/spec/openstego_spec.rb)
provide two legacy OpenStego PNGs with expected header matches. The
[zsteg parser](https://github.com/zed-0xff/zsteg/blob/b75b578ea13ed207561a46b8620b843c0a894422/lib/zsteg/result.rb)
documents the fields used by the check. Both public images carry encrypted data.

## Decision

- Check original RGB samples of static 8-bit RGB PNGs. Match the legacy
  header and accept version 1 with one low bit per channel. Validate declared
  lengths against the image capacity before reading any payload bytes.
- Decode uncompressed, unencrypted UTF-8 and apply the existing invisible
  character normalization. Send that text as `openstego` evidence, with its
  own score and provenance. Text follows the selected local or cloud
  detector and its normal evidence storage. The report shows the status,
  size and score. Verbose output shows normalized text. Filename bytes are
  skipped and binary payloads are reported without submitting raw bytes.
- A recognized header with a malformed, encrypted, compressed or unsupported
  payload leaves the scan incomplete. A recognized PNG whose pixels cannot
  be read by this check also leaves the scan incomplete. The existing verdict
  and exit policy retains a finding from a different reading.

## Alternatives and consequences

Running zsteg would bring more layout coverage and a Ruby runtime. The
documented header has a small implementation using the existing PNG and
array libraries. It costs one additional decode of applicable PNGs and adds
a detector reading when plaintext is present. Independent research
evaluation paths continue to use their existing readings.

Decoding encrypted data would require a password interface. Gzip payloads
are recognized by flag. The legacy header declares the stored length and
provides no expanded length, so handling that input belongs in a separately
reviewed decompression design. Other encodings, RandomLSB layouts, and
PngLoader-style formats require their own evidence and coverage decisions.

## Validation boundary

The tests use inert UTF-8 fixtures and fake inference to verify evidence
routing, verdicts, report fields, and failure handling. The two external
samples verify encrypted-header compatibility. On the 554 pinned catalog
inputs, the reader returned no OpenStego result. This evaluation establishes
coverage for the implemented reading on these cases. Model quality,
deployment false-positive rate and cross-platform inference remain unmeasured.
