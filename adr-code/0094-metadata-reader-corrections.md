# ADR 0094 — Metadata reader corrections

Status: accepted for implementation and review, 2026-11-27. Amends 0083.
Refs #125.

## Context

The fixture editor (ADR 0093) writes metadata and reads it back with
`vipi.image_metadata`. The read-back showed three cases where VIPI read
something other than what the file holds:

- **Repeated PNG keywords.** ADR 0083 read PNG text through Pillow's
  `Image.text`, a dictionary with one value per keyword. The PNG
  specification allows several chunks with the same keyword, so a later chunk
  (for example a harmless `Comment` after the pixel data) hid an earlier one
  from the detector.
- **XMP text split at entity references.** Expat delivers one text node in
  several pieces, for example at `&amp;` or `&lt;`. Each piece became its own
  reading line, so `Ignore &amp; reply` became three lines.
- **UTF-8 in ASCII EXIF tags.** Pillow decodes ASCII tags as Latin-1. exiftool
  and most editors write UTF-8 there, so `Größe` was read as `GrÃ¶ÃŸe`.

## Decision

- Parse PNG `tEXt`, `zTXt` and `iTXt` chunks from the file bytes in file
  order, before and after the pixel data, and read every chunk, including
  repeated keywords and repeated XMP packets. Decompression keeps Pillow's
  limits (`MAX_TEXT_CHUNK` per chunk, `MAX_TEXT_MEMORY` in total), so no new
  limit is introduced. A chunk that exceeds them makes only the group that
  reads it (text chunks or XMP) unreadable, as before.
- Collect XMP character data until the next markup event (element, comment,
  processing instruction), so one text node is one line.
- Re-decode Pillow's Latin-1 string of an ASCII EXIF tag as UTF-8 when its
  bytes are valid UTF-8; otherwise keep the Latin-1 text. ASCII text is
  unchanged by this.

Everything else in ADR 0083 stays: sources, text-only rule, normalization,
unreadable groups and report.

## Alternatives and consequences

Keeping `Image.text` and reading only the last value per keyword would leave
an evasion path through repeated keywords. Setting `buffer_text` on the
parser also joins pieces but still splits at its buffer size; collecting until
markup does not. A Latin-1 value whose bytes happen to be valid UTF-8 is now
read as UTF-8; such text is rare, and the detector sees the same letters for
pure ASCII.

## Validation boundary

Unit tests cover repeated keywords before and after the pixel data,
compressed iTXt, repeated XMP packets, an oversized zTXt chunk, XMP with
entity references and UTF-8 in ASCII EXIF tags; the editor's read-back tests
write every container field and read it back. Detection scores on the
evaluation dataset were not rerun; the dataset contains few metadata cases.
