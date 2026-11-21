"""Read an SVG file once: source text, a render-safe copy and present features.

The source reading is what a model sees when it reads the file as text. The
render-safe copy keeps only same-document (`#…`) and `data:` references, as a
browser does for an SVG shown with `<img>`.
"""

import base64
from dataclasses import dataclass
import pyexpat
import re
from xml.sax.saxutils import escape, quoteattr

from .text import (
    SVG_MEDIA_TYPE,
    decode_text,
    expand_data_uris,
    is_text_media_type,
    normalize_invisible,
    parse_data_uri,
)

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
# Text in these elements continues the surrounding line instead of starting one.
INLINE_TEXT_ELEMENTS = {"tspan", "textPath"}
ANIMATION_ELEMENTS = {
    "animate",
    "animateColor",
    "animateMotion",
    "animateTransform",
    "discard",
    "set",
}
FONT_ELEMENTS = {"font", "font-face", "glyph"}
IMAGE_ELEMENTS = {"image", "feImage"}
# Attributes whose values are geometry, paint, units, references or animation
# timing. Their values are left out of the source reading unless they contain
# prose (PROSE), so path data and styling do not drown the text.
STRUCTURAL_ATTRIBUTES = frozenset(
    """
    accumulate additive alignment-baseline amplitude aria-describedby
    aria-labelledby attributeName attributeType
    azimuth baseFrequency baseProfile baseline-shift begin bias by calcMode class
    clip clip-path clip-rule clipPathUnits color color-interpolation
    color-interpolation-filters cx cy d diffuseConstant direction display
    divisor dominant-baseline dur dx dy edgeMode elevation end exponent fill
    fill-opacity fill-rule filter filterUnits flood-color flood-opacity
    font-family font-size font-size-adjust font-stretch font-style font-variant
    font-weight fr from fx fy gradientTransform gradientUnits height href id
    image-rendering in in2 intercept isolation k1 k2 k3 k4 kernelMatrix
    kernelUnitLength keyPoints keySplines keyTimes lengthAdjust letter-spacing
    lighting-color limitingConeAngle marker-end marker-mid marker-start
    markerHeight markerUnits markerWidth mask maskContentUnits maskUnits
    mix-blend-mode mode numOctaves offset opacity operator order orient overflow
    paint-order pathLength patternContentUnits patternTransform patternUnits
    pointer-events points pointsAtX pointsAtY pointsAtZ preserveAlpha
    preserveAspectRatio primitiveUnits r radius refX refY repeatCount repeatDur
    restart result role rotate rx ry scale seed shape-rendering slope spacing
    specularConstant specularExponent spreadMethod startOffset stdDeviation
    stitchTiles stop-color stop-opacity stroke stroke-dasharray
    stroke-dashoffset stroke-linecap stroke-linejoin stroke-miterlimit
    stroke-opacity stroke-width style surfaceScale tableValues targetX targetY
    text-anchor text-decoration text-rendering textLength to transform
    transform-origin type unicode-bidi values vector-effect version viewBox
    visibility width word-spacing writing-mode x x1 x2 xChannelSelector y y1 y2
    yChannelSelector z zoomAndPan
    """.split()
)
# Four whitespace-separated words: prose hidden in a structural attribute.
PROSE = re.compile(r"(?:[^\W\d_]{2,}\s+){3}[^\W\d_]{2,}")
FONT_FACE = re.compile(r"@font-face\s*\{[^}]*\}", re.IGNORECASE)
SIZE_ATTRIBUTES = ("width", "height", "viewBox", "font-size")


@dataclass(frozen=True)
class SvgDocument:
    """What the scan needs from one SVG file."""

    source_text: str
    detector_text: str
    invisible_characters: int
    render_markup: str
    size_attributes: dict
    removed_references: tuple[str, ...]
    features: tuple[str, ...]


def local_name(name):
    return name.rsplit(":", 1)[-1]


class _Reader:
    """One pass over the expat events of a document (and nested SVGs)."""

    def __init__(self):
        self.parts = []
        self.run = []  # character data since the last tag, for the markup
        self.text_run = []  # character data of the current line of text
        self.stack = []
        self.markup = []
        self.removed = []
        self.features = set()
        self.size_attributes = {}

    def read(self, data):
        parser = pyexpat.ParserCreate()
        parser.ordered_attributes = True
        parser.StartElementHandler = self.start
        parser.EndElementHandler = self.end
        parser.CharacterDataHandler = self.characters
        parser.CommentHandler = self.comment
        parser.ProcessingInstructionHandler = self.instruction
        parser.EntityDeclHandler = self.entity
        try:
            parser.Parse(data, True)
        except pyexpat.ExpatError as error:
            raise ValueError(f"SVG could not be parsed: {error}") from None
        return self

    def characters(self, data):
        self.run.append(data)
        self.text_run.append(data)

    def flush_markup(self):
        self.markup.append(escape("".join(self.run)))
        self.run.clear()

    def flush(self):
        """End the current line of text at a non-inline element boundary."""
        self.flush_markup()
        raw = "".join(self.text_run)
        self.text_run.clear()
        if self.stack and self.stack[-1] == "style":
            blocks = FONT_FACE.findall(raw)
            if any("data:" in block for block in blocks):
                self.features.add("embedded_font")
            if "@keyframes" in raw.lower():
                self.features.add("animation")
        self.add_text(raw)

    def add_text(self, text):
        text = expand_data_uris(text, self.nested_text).strip()
        if text:
            self.parts.append(text)

    def nested_text(self, payload):
        try:
            return _Reader().read(payload).merge_into(self).text
        except ValueError:
            return payload.decode("utf-8", errors="replace")

    def merge_into(self, parent):
        parent.removed.extend(self.removed)
        parent.features.update(self.features)
        return self

    @property
    def text(self):
        return "\n".join(self.parts)

    def start(self, name, attributes):
        local = local_name(name)
        if not self.stack:
            self.check_root(name, attributes)
        if local in INLINE_TEXT_ELEMENTS:
            self.flush_markup()
        else:
            self.flush()
        self.note_element(local)
        kept = []
        for key, value in zip(attributes[::2], attributes[1::2]):
            value = self.attribute(local, key, value)
            if value is not None:
                kept.append(f" {key}={quoteattr(value)}")
        self.markup.append(f"<{name}{''.join(kept)}>")
        self.stack.append(local)

    def end(self, name):
        local = local_name(name)
        if local in INLINE_TEXT_ELEMENTS:
            self.flush_markup()
        else:
            self.flush()
        self.stack.pop()
        self.markup.append(f"</{name}>")

    def check_root(self, name, attributes):
        values = dict(zip(attributes[::2], attributes[1::2]))
        prefix = name.rsplit(":", 1)[0] if ":" in name else None
        namespace = values.get(f"xmlns:{prefix}" if prefix else "xmlns")
        if local_name(name) != "svg" or namespace not in {None, SVG_NAMESPACE}:
            raise ValueError("Not an SVG document.")
        self.size_attributes = {
            key: values[key] for key in SIZE_ATTRIBUTES if key in values
        }

    def note_element(self, local):
        if local == "script":
            self.features.add("script")
        elif local in ANIMATION_ELEMENTS:
            self.features.add("animation")
        elif local == "foreignObject":
            self.features.add("foreign_object")
        elif local in FONT_ELEMENTS:
            self.features.add("embedded_font")

    def attribute(self, element, key, value):
        """Record the attribute's text; return the value to render, or None."""
        local = local_name(key)
        if key == "xmlns" or key.startswith(("xmlns:", "xml:")):
            return value
        if local.lower().startswith("on"):
            self.features.add("script")
        if local == "href":
            return self.reference(element, value)
        if local not in STRUCTURAL_ATTRIBUTES or PROSE.search(value):
            self.add_text(value)
        return value

    def reference(self, element, value):
        target = value.strip()
        if target.startswith("#"):
            return value
        if target[:5].lower() != "data:":
            self.removed.append(target)
            self.add_text(target)
            return None
        parsed = parse_data_uri(target)
        if element in IMAGE_ELEMENTS:
            self.features.add("embedded_image")
        if parsed is None:
            self.add_text(target)
            return value
        media_type, payload = parsed
        if media_type != SVG_MEDIA_TYPE:
            # The whole value is the URI, so wrapped base64 is decoded as one.
            if is_text_media_type(media_type):
                self.add_text(decode_text(payload))
            return value
        try:
            nested = _Reader().read(payload).merge_into(self)
        except ValueError:
            self.add_text(decode_text(payload))
            self.removed.append("data:image/svg+xml (not a valid SVG)")
            return None
        self.add_text(nested.text)
        markup = base64.b64encode(nested.render_markup.encode()).decode("ascii")
        return f"data:{SVG_MEDIA_TYPE};base64,{markup}"

    def comment(self, data):
        self.flush()
        self.add_text(data)

    def instruction(self, target, data):
        self.flush()
        self.add_text(f"{target} {data}")

    def entity(self, name, is_parameter, value, base, system_id, public_id, notation):
        if value:
            self.add_text(value)
        if system_id:
            self.removed.append(system_id)

    @property
    def render_markup(self):
        return '<?xml version="1.0" encoding="UTF-8"?>' + "".join(self.markup)


def read_svg(data: bytes) -> SvgDocument:
    """Parse SVG bytes without loading DTDs, external entities or resources."""
    reader = _Reader().read(data)
    if reader.removed:
        reader.features.add("external_reference")
    source_text = reader.text
    detector_text, invisible = normalize_invisible(source_text)
    if invisible:
        reader.features.add("invisible_characters")
    return SvgDocument(
        source_text=source_text,
        detector_text=detector_text,
        invisible_characters=invisible,
        render_markup=reader.render_markup,
        size_attributes=reader.size_attributes,
        removed_references=tuple(dict.fromkeys(reader.removed)),
        features=tuple(sorted(reader.features)),
    )
