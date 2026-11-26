# ADR 0088 — Declared headerless PNG layouts

Status: accepted for implementation and review, 2026-11-26. Refs #86.
Amends the verdict scope in [ADR 0071](0071-scan-verdict-and-final-ocr-completeness.md).

## Context and evidence

[Aperi’Solve's PNG analyzer](https://github.com/Zeecka/AperiSolve/blob/main/aperisolve/analyzers/zsteg.py)
calls zsteg with its default settings. Its
[MCP interface](https://github.com/Zeecka/AperiSolve/blob/main/docs/mcp.md#the-intended-loop)
can return textual analysis output to an assistant. Unlike OpenStego, a
headerless layout provides no format marker. On 231 local catalog PNGs
labeled benign for prompt injection, zsteg 0.2.14 reported 324 text candidates
across 85 images. These counts describe decoder output and do not establish
that an image contained steganography. The upstream unmodified flower image
also produced candidates. Its one-bit and three-bit matched variants returned
the expected inert text in their declared layouts.

## Decision

`--lsb-layout` is repeatable and defaults to an empty layout set. A caller
declares the layouts a downstream integration reads. The accepted subset of
zsteg notation uses one through eight low bits from `r`, `g`, `b`, `rgb`, or
`bgr` in original static 8-bit RGB PNG samples, row or column traversal from
the top left, and either zsteg byte assembly order. Use the public
[zsteg fragment preview](https://github.com/zed-0xff/zsteg#usage), the first
printable ASCII fragment of at least eight bytes in the first 256 decoded
bytes per layout. These bounds mirror the downstream default fragment preview.
Whole-stream, binary, file-signature and other analyzer behavior are outside
this reading.

The existing text detector checks the candidates with layout labels as
`png_lsb` evidence. The file report keeps counts, layout provenance and the
detector score. Verbose output shows the text. Decoder errors use the
existing incomplete policy. Finding a candidate or using the option does not
by itself produce an injection verdict.

## Alternatives and consequences

Default broad enumeration would send many ambiguous candidates to the
detector, including from otherwise ordinary images, and add cloud requests
to runs that have no such downstream reader. Explicit layouts make the
caller’s intent and checked scope inspectable. Depending on the Ruby tool
would add an external runtime. The native decoder implements the defined
text-only subset using the installed image and array libraries. When opted in,
applicable PNGs receive an additional decode and text candidates enter the
detector's existing local or cloud path and evidence storage.

## Validation boundary

The pinned zsteg flower fixtures verify one-bit and three-bit RGB extraction
from upstream PNGs. The product integration tests use inert text and fake
inference to verify CLI opt-in, layout interpretation, output and verdict
routing. With the two fixture layouts selected, VIPI returned one candidate
on 202 local catalog controls. The other 29 PNGs were outside the 8-bit RGB
scope. The comparison measured candidate frequency. Detector quality and
production steganography detection rates remain unmeasured.
