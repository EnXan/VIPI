"""Complete an editor recipe outside the browser (for the MCP server).

The editor's JavaScript fills layer defaults and derives some recipe fields
before it asks the server to encode: a metadata layer's written value, a PNG
LSB layout, the expected OCR and decoded text. This module does the same in
Python, so a caller can pass a short recipe such as
``{"layers": [{"kind": "metadata", "source": "…"}]}`` and get the recipe the
editor would have produced. It mirrors `static/editor-layers.js` and
`static/editor-ui.js`; keep them in step.
"""

import base64
import copy

LINE_HEIGHT = 1.25
ENCODINGS = ("plain", "base64", "tags", "zero_width", "homoglyphs")
HOMOGLYPHS = dict(zip("aceijopsxyABCEHKMOPTX", "асеіјорѕхуАВСЕНКМОРТХ", strict=True))
KINDS = ("text", "code", "metadata", "scaling", "alpha", "stego", "svg", "heal")


def transform(text, encoding):
    """Rewrite text as the editor's "Draw as" / "Encode as" does."""
    if encoding == "base64":
        return base64.b64encode(text.encode()).decode()
    if encoding == "tags":
        return "".join(
            chr(0xE0000 + ord(char)) if " " <= char <= "~" else char for char in text
        )
    if encoding == "zero_width":
        return "​".join(text)
    if encoding == "homoglyphs":
        return "".join(HOMOGLYPHS.get(char, char) for char in text)
    if encoding == "plain":
        return text
    raise ValueError(f"Choose an encoding of: {', '.join(ENCODINGS)}.")


def _defaults(kind, layer, width, height, image_format, scaling_methods):
    centre = {"x": round(width / 2), "y": round(height / 2)}
    if kind == "text":
        return {
            "visible": True,
            "encoding": "plain",
            **centre,
            "font": "Geist",
            "size": max(8, round(height / 8)),
            "bold": False,
            "italic": False,
            "color": "#111111",
            "opacity": 1,
            "rotation": 0,
            "skew": 0,
            "blur": 0,
            "mirror": False,
        }
    if kind == "code":
        return {
            "visible": True,
            "format": "QRCode",
            **centre,
            "module": max(2, round(height / 90)),
            "color": "#000000",
            "paper": "#ffffff",
            "opacity": 1,
        }
    if kind == "metadata":
        from research.fixtures.metadata import CONTAINERS

        container = layer.get("container") or next(
            name for name, spec in CONTAINERS.items() if image_format in spec["formats"]
        )
        fields = list(CONTAINERS.get(container, {}).get("fields", {}))
        return {
            "container": container,
            "field": fields[0] if fields else None,
            "key": "Comment",
            "encoding": "plain",
            "compressed": False,
            "after_pixels": False,
        }
    if kind == "scaling":
        target = max(1, round(width / 4))
        return {
            "method": next(
                item["id"] for item in scaling_methods if item["attackable"]
            ),
            "width": target,
            "size": max(8, round(target / 14)),
            **centre,
            "color": "#000000",
            "panel": False,
            "panel_color": "#ffffff",
        }
    if kind == "alpha":
        return {
            "mode": "black",
            "x": centre["x"],
            "y": round(height * 0.78),
            "size": max(12, round(height / 14)),
            "color": "#000000",
        }
    if kind == "stego":
        return {
            "stego": "openstego",
            "filename": "message.txt",
            "depth": 1,
            "bits": 1,
            "channels": "rgb",
            "order": "lsb",
            "traversal": "xy",
        }
    if kind == "svg":
        return {"placement": "comment", **centre, "size": 24, "color": "#000000"}
    return {"visible": True, "strokes": []}  # heal: removed areas


def complete(recipe):
    """A full editor recipe from a possibly short one; the input is not changed."""
    from research.fixtures.scaling import methods

    if not isinstance(recipe, dict):
        raise ValueError("A recipe must be an object.")
    full = copy.deepcopy(recipe)
    canvas = full.setdefault("canvas", {})
    width, height = (
        int(canvas.setdefault("width", 800)),
        int(canvas.setdefault("height", 450)),
    )
    if width < 16 or height < 16:
        raise ValueError("The canvas needs at least 16 × 16 pixels.")
    canvas.setdefault("background", "#ffffff")
    canvas.setdefault("background_image", None)
    image_format = full.setdefault("format", "png")
    full.setdefault("label", "injection")
    full.setdefault("version", 1)
    layers = full.get("layers")
    if not isinstance(layers, list):
        raise ValueError("A recipe needs a list of layers.")
    scaling_methods = methods()
    completed = []
    for index, layer in enumerate(layers, 1):
        if not isinstance(layer, dict) or layer.get("kind") not in KINDS:
            raise ValueError(f"Layer {index}: choose a kind of {', '.join(KINDS)}.")
        kind = layer["kind"]
        # "text" is the common name; metadata layers call their value "source".
        if kind == "metadata" and "source" not in layer and "text" in layer:
            layer = {**layer, "source": layer["text"]}
        needed = "source" if kind == "metadata" else "text"
        if kind != "heal" and not str(layer.get(needed) or "").strip():
            raise ValueError(f"Layer {index} ({kind}) needs a {needed}.")
        item = {
            "id": layer.get("id") or f"l{index}",
            **_defaults(kind, layer, width, height, image_format, scaling_methods),
            **layer,
        }
        if kind == "metadata":
            item["value"] = transform(item["source"], item["encoding"])
        if kind == "stego":
            item["layout"] = (
                f"b{item['bits']},{item['channels']},{item['order']},{item['traversal']}"
            )
            item["depth"] = int(item["depth"])
        completed.append(item)
    full["layers"] = completed
    texts = sorted(
        (
            layer
            for layer in completed
            if layer["kind"] == "text" and layer["visible"] and layer["text"].strip()
        ),
        key=lambda layer: (layer["y"], layer["x"]),
    )
    full["expected_ocr"] = "\n".join(
        transform(layer["text"], layer["encoding"]) for layer in texts
    )
    full["expected_decoded"] = "\n".join(
        layer["text"] for layer in texts if layer["encoding"] == "base64"
    )
    full.setdefault("obfuscation", [])
    return full
