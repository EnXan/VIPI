# ADR 0096 — MCP server for the fixture editor

Status: accepted for implementation and review, 2026-11-28. Refs #125.

## Context

The fixture editor (ADR 0093) builds test images in the browser. The user
wants AI models to use the same functions directly, as an MCP server. The
editor composes visible layers on a browser canvas and fills recipe fields
(metadata value, PNG LSB layout, expected text) in JavaScript, so neither is
available without a browser.

## Decision

- `research/mcp/` with the official `mcp` Python SDK (2.x, `MCPServer`) in the
  `research` extra, started as `python -m research.mcp` over stdio. Product
  code is unchanged.
- Tools: `editor_options`, `create_fixture`, `read_image`, `render_view`,
  `find_text_lines`, `scan_image`.
- Recipes use the editor's fixture recipe. `research/fixtures/recipe.py`
  fills the editor's layer defaults and derived fields (a port of
  `editor-layers.js` and `editor-ui.js`; keep them in step), so a short
  recipe is enough and the written fixture opens in the editor.
- `research/fixtures/render.py` draws visible layers with Pillow: background
  colour and image, removed areas (`heal`), text (bundled Geist or an
  installed system font by name; rotation, skew, mirror, synthetic italic,
  opacity, blur, line height 1.25) and codes. Zero-width and tag characters
  are not drawn, as in browsers. A missing font falls back to Geist and is
  reported in the result's notes.
- Files are written only into `--output` (default `research/generated/mcp`,
  ignored by Git); names are reduced to `[A-Za-z0-9._-]`. Tools read images
  the caller names after checking they decode.
- `scan_image` runs `vipi scan` in-process; cloud OCR configurations make paid
  API calls and are refused unless the server starts with `--allow-cloud`.
- A tool's `ValueError` reaches the model as its message (`ToolError`); the
  SDK reports other exceptions only generically.

## Alternatives and consequences

- A headless browser (Playwright) would draw exactly like the editor, at the
  cost of a Chromium download (~150 MB) and a slow start. Not chosen. Pillow
  glyphs differ slightly from the browser's; the fixture records the written
  file, so read-back and expected text stay exact.
- Calling the running workbench over HTTP would still need the browser to
  compose. Not chosen.
- Automatic obfuscation labels are not derived on the server; callers pass
  `obfuscation` in the recipe.

## Validation boundary

`tests/research/test_mcp.py` calls every tool but `scan_image`'s full run
through the SDK's in-process client: create with text, code, metadata and PNG
LSB layers read back; `read_image` finds them; `render_view` returns an
image; text lines found by the tiny OCR model are removed from a background;
the cloud opt-in and missing files return errors. A stdio run through
`python -m research.mcp` listed the six tools and created a fixture, and a
`scan_image` call with `local-speed-wolf-defender` returned the verdict and
the recognized text. Not verified: Claude Code registration and
Windows/Linux font lookup.
