"""Turn an editor recipe and its composed raster into a fixture file.

The browser composes the visible layers (text, codes, background) into a PNG.
The hidden channels are written here, in a fixed order: scaling payloads,
transparency, pixel steganography, then metadata on save; SVG output wraps the
raster instead. Afterwards VIPI's own readers read the file back, so every
layer shows whether VIPI finds what it carries.
"""

import hashlib
from dataclasses import dataclass, field
from io import BytesIO

import numpy as np
from PIL import Image, UnidentifiedImageError

from vipi.barcodes import read_codes
from vipi.image_metadata import read_metadata
from vipi.images import composite
from vipi.openstego import read_openstego
from vipi.png_lsb import read_lsb
from vipi.svg import read_svg, render_svg
from vipi.transparency import read_views

from . import alpha, codes, metadata, scaling, stego, svg

FORMATS = {
    "png": ("image/png", "png"),
    "jpeg": ("image/jpeg", "jpg"),
    "webp": ("image/webp", "webp"),
    "svg": ("image/svg+xml", "svg"),
}
LABELS = ("benign", "injection", "jailbreak")
FIXTURE_VERSION = 1
RASTER_ONLY = {
    "scaling": "Scaling payloads live in raster pixels; SVG output embeds the composition only.",
    "alpha": "Transparency needs PNG or WebP.",
    "stego": "Pixel steganography needs a PNG without transparency.",
}


@dataclass(frozen=True)
class Encoded:
    data: bytes
    image_format: str
    layers: tuple[dict, ...]
    readings: dict = field(default_factory=dict)
    lsb_statistics: dict | None = None
    preview: bytes | None = None
    display: bytes | None = None  # what OCR sees, when it is not the file itself

    @property
    def mime(self):
        return FORMATS[self.image_format][0]

    @property
    def extension(self):
        return FORMATS[self.image_format][1]

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()


def _png(image):
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _result(layer, label, **extra):
    return {"id": layer.get("id"), "label": label, **extra}


def encode(raster, recipe):
    """Write the recipe's hidden layers into the composed `raster` (PNG bytes)."""
    image_format = recipe.get("format")
    if image_format not in FORMATS:
        raise ValueError("Choose PNG, JPEG, WebP or SVG as output format.")
    try:
        with Image.open(BytesIO(raster)) as composed:
            image = composed.convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise ValueError("The composed image could not be decoded.") from None
    layers = recipe.get("layers")
    if not isinstance(layers, list):
        raise ValueError("A recipe needs a list of layers.")
    # Hidden layers stay in the recipe (to reopen) but are not written.
    layers = [
        layer
        for layer in layers
        if isinstance(layer, dict) and layer.get("visible", True) is not False
    ]
    if image_format == "svg":
        return _encode_svg(image, layers, recipe)
    return _encode_raster(image, image_format, layers, recipe)


def _encode_raster(image, image_format, layers, recipe):
    skipped = []
    image, scaled = _embed_scaling(image, layers)
    has_alpha = image_format in ("png", "webp") and any(
        layer.get("kind") == "alpha" for layer in layers
    )
    image, transparent = _embed_alpha(image, layers, skipped, has_alpha)
    image, stegos = _embed_stego(
        image, layers, skipped, image_format == "png" and not has_alpha
    )
    results, written = _metadata_layers(layers, image_format)
    data = metadata.save(image, image_format, written)

    with Image.open(BytesIO(data)) as saved:
        rgba = saved.convert("RGBA")
    white = composite(rgba, "white")
    readings = {}
    read = read_metadata(data)
    _check_metadata(results, read.text)
    readings["image_metadata"] = {
        "text": read.text,
        "detector_text": read.detector_text,
    }
    for result, layer, drawn, mask in scaled:
        exact, total = scaling.check(data, layer, drawn, mask)
        result |= {"exact_pixels": exact, "payload_pixels": total}
        result["status"] = "read" if exact == total else "changed"
    views = read_views(BytesIO(data)) if transparent else None
    for result, layer, where in transparent:
        shown, total = alpha.check(views, layer, where)
        result |= {"shown_pixels": shown, "text_pixels": total}
        result["status"] = (
            "read" if shown == total else ("changed" if shown else "missing")
        )
    readings |= _check_stego(data, stegos)
    readings["barcode"] = _check_codes(white, layers, results)
    statistics = None
    if image_format == "png" and not has_alpha:
        lsb = read_lsb(data, (), statistics=True)
        statistics = lsb.statistics if lsb else None
    return Encoded(
        data=data,
        image_format=image_format,
        layers=tuple(item[0] for item in scaled + transparent + stegos)
        + tuple(results + skipped),
        readings=readings,
        lsb_statistics=statistics,
        preview=_preview(rgba, recipe.get("view")),
    )


def _encode_svg(image, layers, recipe):
    skipped, results, placed = [], [], []
    for layer in layers:
        kind = layer.get("kind")
        if kind in RASTER_ONLY or kind == "metadata":
            reason = RASTER_ONLY.get(kind, "SVG files carry no raster metadata.")
            skipped.append(_result(layer, kind, status="skipped", reason=reason))
        elif kind == "svg":
            clean = svg.validate(layer)
            placed.append(clean)
            results.append(
                _result(
                    layer, svg.PLACEMENTS[clean["placement"]], expected=clean["text"]
                )
            )
    background = (recipe.get("canvas") or {}).get("background") or "#ffffff"
    data = svg.build(_png(image), image.size, placed, background)
    document = read_svg(data)
    rendered = render_svg(document)
    for result, clean in zip(results, placed):
        result["status"] = (
            "read" if svg.found(document.source_text, clean["text"]) else "missing"
        )
    with Image.open(BytesIO(rendered.png)) as render:
        rgba = render.convert("RGBA")
    code_results = []
    readings = {
        "svg_source": {
            "text": document.source_text,
            "detector_text": document.detector_text,
        },
        "barcode": _check_codes(rgba.convert("RGB"), layers, code_results),
    }
    return Encoded(
        data=data,
        image_format="svg",
        layers=tuple(results + code_results + skipped),
        readings=readings,
        preview=_preview(rgba, recipe.get("view")),
        display=rendered.png,
    )


def _embed_scaling(image, layers):
    scaled = []
    for layer in layers:
        if layer.get("kind") != "scaling":
            continue
        clean = scaling.validate(layer)
        image, drawn, mask = scaling.embed(image, clean)
        result = _result(
            layer,
            f"{scaling.TITLES[clean['method']]} to {drawn.size[0]}×{drawn.size[1]}",
            expected=clean["text"],
            method=clean["method"],
            size=list(drawn.size),
        )
        scaled.append((result, clean, drawn, mask))
    return image, scaled


def _embed_alpha(image, layers, skipped, allowed):
    transparent = []
    for layer in layers:
        if layer.get("kind") != "alpha":
            continue
        clean = alpha.validate(layer)
        label = alpha.MODES[clean["mode"]]
        if not allowed:
            skipped.append(
                _result(layer, label, status="skipped", reason=RASTER_ONLY["alpha"])
            )
            continue
        image, where = alpha.embed(image, clean)
        transparent.append(
            (_result(layer, label, expected=clean["text"]), clean, where)
        )
    return image, transparent


def _embed_stego(image, layers, skipped, allowed):
    written = []
    for layer in layers:
        if layer.get("kind") != "stego":
            continue
        clean = stego.validate(layer)
        label = stego.KINDS[clean["stego"]] + (
            f" {clean['layout']}" if "layout" in clean else ""
        )
        if not allowed:
            skipped.append(
                _result(layer, label, status="skipped", reason=RASTER_ONLY["stego"])
            )
            continue
        image = stego.embed(image, clean)
        written.append((_result(layer, label, expected=clean["text"]), clean))
    return image, written


def _check_stego(data, stegos):
    if not stegos:
        return {}
    found = {reading.kind: reading for reading in read_openstego(data)}
    layouts = tuple(clean["layout"] for _, clean in stegos if "layout" in clean)
    lsb = read_lsb(data, layouts) if layouts else None
    candidates = dict(lsb.candidates) if lsb else {}
    readings = {}
    for result, clean in stegos:
        if clean["stego"] == "png_lsb":
            text = candidates.get(clean["layout"], "")
            if lsb and lsb.candidates:
                readings["png_lsb"] = {
                    "text": lsb.detector_text,
                    "detector_text": lsb.detector_text,
                }
        else:
            reading = found.get(clean["stego"])
            text = reading.text if reading else ""
            if reading:
                readings[clean["stego"]] = {
                    "text": reading.text,
                    "detector_text": reading.detector_text,
                }
                result["reader_status"] = reading.status
        result["read"] = [text] if text else []
        expected = (
            clean["text"].strip() if clean["stego"] == "png_lsb" else clean["text"]
        )
        result["status"] = (
            "read" if text == expected else ("changed" if text else "missing")
        )
    return readings


def _check_codes(raster, layers, results):
    reading = read_codes(raster)
    lines = f"\n{reading.text}\n"
    for layer in layers:
        if layer.get("kind") != "code" or not layer.get("visible", True):
            continue
        expected = codes.reader_label(layer.get("format"), layer.get("text"))
        name = expected.split(":", 1)[0]
        result = _result(layer, name, expected=expected)
        if f"\n{expected}\n" in lines:
            result["status"] = "read"
        else:
            values = _read_values(reading.text, name)
            result["status"] = "changed" if values else "missing"
            result["read"] = values
        results.append(result)
    return {"text": reading.text, "detector_text": reading.detector_text}


def _preview(rgba, view):
    """The file as another consumer sees it: on black, alpha dropped, a bit plane or downscaled."""
    if not isinstance(view, dict):
        return None
    mode = view.get("mode")
    if mode == "black":
        return _png(composite(rgba, "black"))
    if mode == "rgb":
        return _png(rgba.convert("RGB"))
    if mode == "bitplane":
        channel, bit = view.get("channel"), view.get("bit")
        if channel not in ("r", "g", "b") or bit not in range(8):
            raise ValueError("Choose a channel r, g or b and a bit from 0 to 7.")
        samples = np.asarray(rgba)[..., "rgb".index(channel)]
        return _png(Image.fromarray((((samples >> bit) & 1) * 255).astype(np.uint8)))
    if mode == "scaled":
        white = composite(rgba, "white")
        size = scaling.target_size(white.size, view.get("width"))
        return _png(scaling.downscale(white, view.get("method"), size))
    raise ValueError(f"Unknown view: {mode!r}.")


def _metadata_layers(layers, image_format):
    results, written = [], []
    for layer in layers:
        if layer.get("kind") != "metadata":
            continue
        clean = metadata.validate(layer)
        result = _result(layer, metadata.reader_label(clean))
        spec = metadata.CONTAINERS[clean["container"]]
        if image_format not in spec["formats"]:
            result |= {
                "status": "skipped",
                "reason": f"{image_format.upper()} has no {spec['title']}.",
            }
        else:
            written.append(clean)
            result |= {
                "status": "pending",
                "expected": f"{result['label']}: {clean['value'].strip()}",
            }
        results.append(result)
    return results, written


def _check_metadata(results, text):
    lines = f"\n{text}\n"
    for result in results:
        if result["status"] != "pending":
            continue
        if f"\n{result['expected']}\n" in lines:
            result["status"] = "read"
        else:
            values = _read_values(text, result["label"])
            # "changed": VIPI reads this field, but not the written value.
            result["status"] = "changed" if values else "missing"
            result["read"] = values


def _read_values(text, label):
    """The values the reader found under `label` instead."""
    return [
        line[len(label) + 2 :]
        for line in text.split("\n")
        if line.startswith(f"{label}: ")
    ]


def fixture(encoded, recipe, name):
    """The fixture record exported next to the image."""
    label = recipe.get("label")
    if label not in LABELS:
        raise ValueError("Choose benign, injection or jailbreak as label.")
    expected = {"ocr": str(recipe.get("expected_ocr") or "")}
    if recipe.get("expected_decoded"):
        expected["decoded"] = str(recipe["expected_decoded"])
    for reading, value in encoded.readings.items():
        if value["text"]:
            expected[reading] = value["text"]
    scaled = [
        {"method": layer["method"], "size": layer["size"], "text": layer["expected"]}
        for layer in encoded.layers
        if "method" in layer
    ]
    if scaled:
        expected["image_scaling"] = scaled
    hidden = [layer["expected"] for layer in encoded.layers if "shown_pixels" in layer]
    if hidden:
        expected["transparency"] = hidden
    return {
        "version": FIXTURE_VERSION,
        "image": f"{name}.{encoded.extension}",
        "image_sha256": encoded.sha256,
        "label": label,
        "obfuscation": [str(value) for value in recipe.get("obfuscation") or []],
        "expected": expected,
        "channels": [layer for layer in encoded.layers if layer["status"] != "skipped"],
        "recipe": recipe,
    }
