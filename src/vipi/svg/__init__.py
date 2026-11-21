"""SVG inputs: a source text reading and a safe raster for OCR (ADR 0078)."""

from dataclasses import dataclass
from pathlib import Path

from .document import SvgDocument, read_svg
from .render import RenderedSvg, render_svg

__all__ = ["SvgDocument", "SvgInput", "is_svg", "prepare_svg", "read_svg", "render_svg"]

INCOMPLETE_EMBEDDED_FONT = (
    "The SVG embeds a font that VIPI cannot render; text a browser shows may "
    "differ from the OCR reading."
)


def is_svg(image):
    return isinstance(image, (str, Path)) and Path(image).suffix.lower() == ".svg"


@dataclass(frozen=True)
class SvgInput:
    """A read and rendered SVG file, ready for OCR and detection."""

    data: bytes
    document: SvgDocument
    rendered: RenderedSvg

    @property
    def incomplete(self):
        if "embedded_font" in self.document.features:
            return (INCOMPLETE_EMBEDDED_FONT,)
        return ()

    def report(self, answers=()):
        """The report's `svg` object; `answers` adds the score per reading."""
        scores = {}
        for answer in answers:
            score = answer.get("probability")
            if answer.get("status") != "completed" or score is None:
                continue
            for source in answer.get("source_ids", ()):
                reading = "svg_source" if source == "svg_source" else "ocr"
                scores[reading] = max(score, scores.get(reading, score))
        document, rendered = self.document, self.rendered
        return {
            "intrinsic_size": list(rendered.intrinsic_size),
            "size_source": rendered.size_source,
            "render_size": list(rendered.render_size),
            "scale": rendered.scale,
            "removed_references": list(document.removed_references),
            "features": list(document.features),
            "invisible_characters": document.invisible_characters,
            "source_text_characters": len(document.source_text),
            "scores": scores,
        }


def prepare_svg(path):
    data = Path(path).read_bytes()
    document = read_svg(data)
    return SvgInput(data, document, render_svg(document))
