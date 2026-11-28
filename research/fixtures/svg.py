"""SVG output: the composition as an embedded raster plus SVG source text.

VIPI reads an SVG twice (ADR 0078): OCR of a safe render, and the source text
(character data, comments, non-structural attribute values, decoded `data:`
text). An SVG layer places its text in one of these spots, visible or not.
"""

import base64
from xml.sax.saxutils import escape, quoteattr

PLACEMENTS = {
    "comment": "Comment",
    "title": "<title> element",
    "desc": "<desc> element",
    "metadata": "<metadata> element",
    "attribute": "aria-label attribute",
    "data_uri": "data: URI (base64 text)",
    "text_visible": "Visible <text>",
    "text_transparent": "<text> with opacity 0",
    "text_hidden": "<text> with display none",
    "text_offcanvas": "<text> outside the canvas",
    "text_tiny": "<text> at 0.1 px",
    "text_background": "<text> in the background colour",
}


def validate(layer):
    if layer.get("placement") not in PLACEMENTS:
        raise ValueError(f"Choose one of: {', '.join(PLACEMENTS)}.")
    text = layer.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("An SVG layer needs text.")
    clean = {"placement": layer["placement"], "text": text}
    for key, default in (("x", 0), ("y", 0), ("size", 24)):
        value = layer.get(key, default)
        if not isinstance(value, (int, float)):
            raise ValueError(f"An SVG layer needs a numeric {key}.")
        clean[key] = value
    clean["color"] = str(layer.get("color") or "#000000")
    return clean


def _text_element(layer, width, background):
    attributes = {
        "x": layer["x"],
        "y": layer["y"],
        "font-family": "Arial, sans-serif",
        "font-size": layer["size"],
        "fill": layer["color"],
        "text-anchor": "middle",
    }
    placement = layer["placement"]
    if placement == "text_transparent":
        attributes["opacity"] = 0
    elif placement == "text_hidden":
        attributes["display"] = "none"
    elif placement == "text_offcanvas":
        attributes["x"] = -10 * width
    elif placement == "text_tiny":
        attributes["font-size"] = 0.1
    elif placement == "text_background":
        attributes["fill"] = background
    lines = layer["text"].split("\n")
    spans = "".join(
        f'<tspan x="{attributes["x"]}" dy="{0 if index == 0 else "1.2em"}">{escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )
    rendered = " ".join(
        f"{key}={quoteattr(str(value))}" for key, value in attributes.items()
    )
    return f"<text {rendered}>{spans}</text>"


def build(raster_png, size, layers, background="#ffffff"):
    """SVG bytes: hidden head items, the raster, then text elements."""
    width, height = size
    head, body = [], []
    for layer in layers:
        text, placement = layer["text"], layer["placement"]
        if placement == "comment":
            head.append(f"<!-- {text.replace('--', '- -')} -->")
        elif placement in ("title", "desc"):
            head.append(f"<{placement}>{escape(text)}</{placement}>")
        elif placement == "metadata":
            head.append(f"<metadata><note>{escape(text)}</note></metadata>")
        elif placement == "attribute":
            body.append(f"<g aria-label={quoteattr(text)}></g>")
        elif placement == "data_uri":
            encoded = base64.b64encode(text.encode()).decode()
            body.append(
                f'<image width="1" height="1" href="data:text/plain;base64,{encoded}"/>'
            )
        else:
            body.append(_text_element(layer, width, background))
    raster = base64.b64encode(raster_png).decode()
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        + "".join(head)
        + f'<image width="{width}" height="{height}" href="data:image/png;base64,{raster}"/>'
        + "".join(body)
        + "</svg>\n"
    ).encode()


def found(source_text, text):
    """Whether every line of `text` occurs in VIPI's SVG source reading."""
    return all(line.strip() in source_text for line in text.split("\n") if line.strip())
