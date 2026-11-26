"""Views of images with transparent pixels (ADR 0085).

VIPI composites images onto white. An agent may instead see the image on a dark
background or with its alpha channel dropped, so an image with any transparent
pixel is also scanned in those views. Pixel-identical views are scanned once.
"""

from dataclasses import dataclass, field, replace

from .images import MAX_INPUT_PIXELS, composite, decode_rgba, png_bytes

VIEWS = ("white", "black", "rgb")
# Detector reading kind per view; the white view is the ordinary OCR reading.
READINGS = {"white": "ocr", "black": "ocr_black", "rgb": "ocr_rgb"}
IMAGE_CHECK_FIELDS = ("status", "verdict", "probability", "submitted_image_size")


@dataclass(frozen=True)
class View:
    name: str
    png: bytes
    # The earlier view with identical pixels, which is scanned in its place.
    same_as: str | None = None


@dataclass(frozen=True)
class TransparencyViews:
    views: tuple[View, ...]
    # OCR result or the exception of each scanned (distinct) view.
    results: dict = field(default_factory=dict)

    @property
    def distinct(self):
        return tuple(view for view in self.views if view.same_as is None)

    def view(self, name):
        return next(view for view in self.views if view.name == name)

    def scanned(self, white, extract):
        """Record ``white`` OCR and run ``extract`` on the other distinct views.

        A failed view keeps its exception; the other views are still scanned.
        """
        results = {"white": white}
        for view in self.distinct[1:]:
            try:
                results[view.name] = extract(view.png)
            except Exception as error:
                results[view.name] = error
        return replace(self, results=results)

    @property
    def ocr_views(self):
        """Completed OCR results of the distinct views other than white."""
        return {
            name: result
            for name, result in self.results.items()
            if name != "white" and not isinstance(result, Exception)
        }

    @property
    def incomplete(self):
        return tuple(
            f"OCR of the {name} transparency view failed: {result}"
            for name, result in self.results.items()
            if isinstance(result, Exception)
        )

    def report(self, answers=()):
        """The report's `transparency` object; `answers` adds scores per view."""
        from vipi.detection.evidence import reading_scores

        scores = reading_scores(answers, tuple(READINGS.values()))
        images = {
            answer.get("view"): answer
            for answer in answers
            if answer.get("kind") == "image"
        }
        items = []
        for view in self.views:
            scanned = view.same_as or view.name
            item = {
                "name": view.name,
                "same_as": view.same_as,
                "score": scores.get(READINGS[scanned]),
            }
            result = self.results.get(view.name)
            if isinstance(result, Exception):
                item["error"] = str(result)
            elif result is not None:
                item.update(
                    run_id=result.run_id,
                    artifacts=str(result.artifacts) if result.artifacts else None,
                    ocr_seconds=result.elapsed_seconds,
                    ocr_text_characters=len(result.text),
                    ocr_cost=result.cost,
                )
            answer = images.get(view.name) if view.same_as is None else None
            item["image_check"] = (
                {key: answer.get(key) for key in IMAGE_CHECK_FIELDS}
                if answer is not None
                else None
            )
            items.append(item)
        return {"views": items}


def read_views(source, *, max_pixels=MAX_INPUT_PIXELS):
    """The views of an image with transparent pixels, or None for an opaque one."""
    rgba = decode_rgba(source, max_pixels=max_pixels)
    if rgba.getchannel("A").getextrema()[0] == 255:
        return None
    rasters = {
        "white": composite(rgba, "white"),
        "black": composite(rgba, "black"),
        "rgb": rgba.convert("RGB"),
    }
    views, seen = [], {}
    for name in VIEWS:
        pixels = rasters[name].tobytes()
        same_as = seen.setdefault(pixels, name)
        views.append(
            View(name, png_bytes(rasters[name]), None if same_as == name else same_as)
        )
    return TransparencyViews(tuple(views))
