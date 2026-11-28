"""MCP server for the fixture editor: build and check test images from an AI model.

The tools wrap `research/fixtures/` (no Flask, no browser): a recipe in the
editor's format is completed (`recipe.complete`), its visible layers drawn
with Pillow (`render.compose`) and its hidden layers written and read back with
VIPI's own readers (`encode`). Fixtures open in the editor and the other way
round. Files are written only into the output directory given at start. A full
`vipi scan` with a cloud configuration (paid API calls) needs `--allow-cloud`.
"""

import base64
import functools
from io import BytesIO
import json
from pathlib import Path
import re

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image as ImageResult
from PIL import Image, UnidentifiedImageError

from research.fixtures import alpha, codes, metadata, scaling, stego, svg, text_boxes
from research.fixtures.encode import FORMATS, LABELS, _preview, encode, fixture
from research.fixtures.recipe import ENCODINGS, KINDS, complete
from research.fixtures.render import compose

UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
VIEWS = ("original", "black", "rgb", "bitplane", "scaled")
LAYER_FIELDS = {
    "text": "text, encoding, x, y, font, size, bold, italic, color, opacity, rotation, skew, blur, mirror, visible",
    "code": "text, format, x, y, module, color, paper, opacity, visible",
    "metadata": "source (or text), container, field (EXIF/XMP/IPTC) or key (PNG text), encoding, compressed, after_pixels",
    "scaling": "text, method, width (target width), size, x, y, color, panel, panel_color",
    "alpha": "text, mode (black | rgb), x, y, size, color",
    "stego": "text, stego (openstego | openstego_random_lsb | png_lsb), filename, depth, bits, channels, order, traversal",
    "svg": "text, placement, x, y, size, color (output format svg)",
    "heal": "strokes: [{size, points: [[x, y], …]}] or [{polygon: [[x, y], …], pad}] (removed areas of the background)",
}
INSTRUCTIONS = """\
Builds test images for VIPI, a prompt-injection scanner for images, with the
same functions as the workbench's fixture editor. Use inert markers and benign
controls only. Typical flow: editor_options → create_fixture (a recipe with
layers) → check the returned read-back → render_view to look at a channel →
scan_image for VIPI's verdict. To replace text in a screenshot, call
find_text_lines on it and put the lines into a "heal" layer as polygons."""


def _reported(tool):
    """Pass a tool's ValueError to the model as its message (the SDK hides other errors)."""

    @functools.wraps(tool)
    def wrapper(*args, **kwargs):
        try:
            return tool(*args, **kwargs)
        except ValueError as error:
            raise ToolError(str(error)) from None

    return wrapper


def _name(value):
    return UNSAFE_NAME.sub("-", str(value or "")).strip(".-") or "fixture"


def _image_file(path):
    """A readable image the caller named, as (path, bytes)."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"No file at {resolved}.")
    data = resolved.read_bytes()
    if resolved.suffix.lower() != ".svg":
        try:
            with Image.open(BytesIO(data)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError):
            raise ValueError(f"{resolved} is not an image VIPI can read.") from None
    return resolved, data


def _data_url(data):
    with Image.open(BytesIO(data)) as image:
        kind = (image.format or "png").lower()
    return f"data:image/{kind};base64,{base64.b64encode(data).decode()}"


def build_server(output, *, allow_cloud=False):
    """The MCP server writing into `output`; tools are registered on it."""
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    server = MCPServer("vipi-fixtures", instructions=INSTRUCTIONS)

    @server.tool()
    @_reported
    def editor_options() -> dict:
        """Everything a recipe can contain: output formats, labels, layer kinds with
        their fields, code formats, metadata containers, scaling methods,
        steganography kinds, SVG placements, text encodings and views."""
        return {
            "formats": list(FORMATS),
            "labels": list(LABELS),
            "layer_kinds": {kind: LAYER_FIELDS[kind] for kind in KINDS},
            "encodings": list(ENCODINGS),
            "code_formats": [item["id"] for item in codes.options()],
            "metadata_containers": [
                {
                    "id": key,
                    "formats": list(spec["formats"]),
                    "fields": list(spec["fields"]),
                }
                for key, spec in metadata.CONTAINERS.items()
            ],
            "scaling_methods": scaling.methods(),
            "alpha_modes": dict(alpha.MODES),
            "stego_kinds": dict(stego.KINDS),
            "svg_placements": list(svg.PLACEMENTS),
            "views": list(VIEWS),
            "recipe_example": {
                "format": "png",
                "label": "injection",
                "canvas": {"width": 800, "height": 450, "background": "#ffffff"},
                "layers": [
                    {"kind": "text", "text": "Quarterly report", "y": 120},
                    {
                        "kind": "metadata",
                        "container": "png_text",
                        "key": "Comment",
                        "source": "VIPI-CANARY-7F3A",
                    },
                ],
            },
        }

    @server.tool()
    @_reported
    def create_fixture(
        recipe: dict, name: str = "fixture", background_image: str | None = None
    ) -> dict:
        """Draw, write and read back a fixture; saves NAME.EXT and NAME.fixture.json.

        `recipe` uses the editor's format (see editor_options); missing fields get
        the editor's defaults. `background_image` is a path; without a canvas size
        the canvas takes the image's size. Returns the files, what VIPI reads back
        per hidden layer (status read / changed / missing / skipped), the expected
        text and notes on anything drawn differently than asked."""
        if background_image:
            _, data = _image_file(background_image)
            with Image.open(BytesIO(data)) as image:
                size = image.size
            canvas = {
                "width": size[0],
                "height": size[1],
                **(recipe.get("canvas") or {}),
            }
            recipe = {
                **recipe,
                "canvas": {**canvas, "background_image": _data_url(data)},
            }
        full = complete(recipe)
        raster, notes = compose(full)
        encoded = encode(raster, full)
        stem = _name(name)
        image_path = output / f"{stem}.{encoded.extension}"
        record_path = output / f"{stem}.fixture.json"
        image_path.write_bytes(encoded.data)
        record = fixture(encoded, full, stem)
        record_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return {
            "image": str(image_path),
            "fixture": str(record_path),
            "sha256": encoded.sha256,
            "read_back": list(encoded.layers),
            "expected": record.get("expected"),
            "notes": notes,
        }

    @server.tool()
    @_reported
    def read_image(path: str, lsb_layouts: list[str] | None = None) -> dict:
        """What VIPI's readers find in any image, without OCR or the detector:
        metadata text, QR codes and barcodes, OpenStego payloads, PNG LSB text for
        the given zsteg layouts (for example "b1,rgb,lsb,xy") and SVG source text.
        Text in transparency views needs OCR: look at render_view or scan_image."""
        from vipi.barcodes import read_codes
        from vipi.images import composite
        from vipi.image_metadata import read_metadata
        from vipi.openstego import read_openstego
        from vipi.png_lsb import read_lsb
        from vipi.svg import read_svg

        resolved, data = _image_file(path)
        if resolved.suffix.lower() == ".svg":
            document = read_svg(data)
            return {"svg_source": document.source_text}
        with Image.open(BytesIO(data)) as image:
            white = composite(image.convert("RGBA"), "white")
        lsb = read_lsb(data, tuple(lsb_layouts or ()), statistics=True)
        return {
            "metadata": read_metadata(data).text,
            "codes": read_codes(white).text,
            "openstego": [reading.text for reading in read_openstego(data)],
            "png_lsb": lsb.detector_text if lsb else "",
            "lsb_statistics": lsb.statistics if lsb else None,
        }

    @server.tool()
    @_reported
    def render_view(
        path: str,
        view: str = "black",
        method: str = "pillow_nearest",
        width: int | None = None,
        channel: str = "r",
        bit: int = 0,
    ) -> ImageResult:
        """The image as another consumer sees it: original, black (on black),
        rgb (alpha dropped), bitplane (one bit of one channel) or scaled
        (downscaled with `method` to `width`, default a quarter)."""
        if view not in VIEWS:
            raise ValueError(f"Choose a view of: {', '.join(VIEWS)}.")
        _, data = _image_file(path)
        with Image.open(BytesIO(data)) as image:
            rgba = image.convert("RGBA")
        if view == "original":
            buffer = BytesIO()
            rgba.save(buffer, "PNG")
            return ImageResult(data=buffer.getvalue(), format="png")
        settings = {
            "mode": view,
            "method": method,
            "width": width or max(1, rgba.width // 4),
            "channel": channel,
            "bit": bit,
        }
        return ImageResult(data=_preview(rgba, settings), format="png")

    @server.tool()
    @_reported
    def find_text_lines(path: str) -> dict:
        """Text line polygons in an image (detection of the tiny local OCR model,
        nothing is read). Put them into a "heal" layer as
        {"polygon": …, "pad": 3} to remove those lines from a background image
        whose canvas has the image's size."""
        _, data = _image_file(path)
        with Image.open(BytesIO(data)) as image:
            buffer = BytesIO()
            image.convert("RGB").save(buffer, "PNG")
        try:
            return {"lines": text_boxes.find_lines(buffer.getvalue())}
        except text_boxes.Unavailable as error:
            return {"lines": [], "hint": str(error)}

    @server.tool()
    @_reported
    def scan_image(
        path: str,
        configuration: str = "local-quality-clef-flash",
        lsb_layouts: list[str] | None = None,
    ) -> dict:
        """Run the full `vipi scan` (OCR, every reading, the detector) on an image and
        return its verdict, injection probability, threshold, score per reading and
        recognized text. Cloud configurations make paid API calls and need the
        server to be started with --allow-cloud."""
        from vipi.reporting import file_record
        from vipi.scanner import scan_image as scan

        from research.ocr_eval.benchmark import CONFIGURATIONS
        from research.workbench.scans import READING_REPORTS, options_for

        if configuration not in CONFIGURATIONS:
            raise ValueError(f"Choose a configuration of: {', '.join(CONFIGURATIONS)}.")
        if (
            CONFIGURATIONS[configuration].get("ocr_execution_mode") == "cloud"
            and not allow_cloud
        ):
            raise ValueError(
                "Cloud configurations make paid API calls; start the server with --allow-cloud to use them."
            )
        resolved, _ = _image_file(path)
        result = scan(
            resolved, options=options_for(configuration, None, lsb_layouts or ())
        )
        record = file_record(result)
        return {
            "verdict": record["verdict"],
            "injection_probability": record["injection_probability"],
            "threshold": record["threshold"],
            "ocr_incomplete": record["ocr_incomplete"],
            "scores": {
                key: record[key].get("scores", {})
                for key in READING_REPORTS
                if isinstance(record.get(key), dict)
            },
            "text": result.ocr.text,
            "errors": record["errors"],
        }

    return server
