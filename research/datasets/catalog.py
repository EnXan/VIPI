"""Read the active OCR selection without modifying dataset files."""

import hashlib
import json
from pathlib import Path

from PIL import Image

DATA_ROOT = "research/datasets/data/"


def image_identity(image):
    """Keep catalog IDs stable across the dataset's repository move."""
    if image.startswith(DATA_ROOT):
        return f"datasets/{image.removeprefix(DATA_ROOT)}"
    return image


def image_id(image):
    return hashlib.sha256(image_identity(image).encode()).hexdigest()[:16]


class Catalog:
    def __init__(self, repository_root):
        self.root = Path(repository_root).resolve()
        directory = self.root / "research/datasets/data/catalog/ocr"
        records = json.loads(
            (directory / "ocr_metadata.json").read_text(encoding="utf-8")
        )
        report_path = directory / "ocr_selection_report.json"
        report = (
            json.loads(report_path.read_text(encoding="utf-8"))
            if report_path.exists()
            else {}
        )
        details = {}
        for item in report.get("selected_references", []):
            image = item["image"]
            if image.startswith("datasets/"):
                image = f"{DATA_ROOT}{image.removeprefix('datasets/')}"
            details[image] = item
        self.items = {}
        for record in records:
            identifier = image_id(record["image"])
            if identifier in self.items:
                raise ValueError("Duplicate image in the OCR selection.")
            self.items[identifier] = {
                **record,
                "id": identifier,
                "details": details.get(record["image"], {}),
            }

    def get(self, identifier):
        if identifier not in self.items:
            raise ValueError("Image is not in the active OCR selection.")
        return self.items[identifier]

    def for_path(self, image):
        try:
            relative = Path(image).resolve().relative_to(self.root).as_posix()
        except ValueError as error:
            raise ValueError("Image is not in the active OCR selection.") from error
        identifier = image_id(relative)
        return self.reference(identifier)

    def path(self, identifier):
        path = (self.root / self.get(identifier)["image"]).resolve()
        data_root = (self.root / "research/datasets/data").resolve()
        if not path.is_relative_to(data_root) or not path.is_file():
            raise ValueError("Selected dataset image is unavailable.")
        return path

    def search(self, category="", query=""):
        if category and category not in {
            item["category"] for item in self.items.values()
        }:
            raise ValueError("Unknown dataset category.")
        return [
            item
            for item in self.items.values()
            if (not category or item["category"] == category)
            and (
                not query
                or query.casefold() in (item["image"] + " " + item["text"]).casefold()
            )
        ]

    def category_counts(self):
        counts = {}
        for item in self.items.values():
            counts[item["category"]] = counts.get(item["category"], 0) + 1
        return counts

    def reference(self, identifier):
        item = self.get(identifier)
        details = item["details"]
        regions = details.get("regions") or []
        with Image.open(self.path(identifier)) as image:
            width, height = image.size
            orientation = image.getexif().get(274, 1)

        def orient(x, y):
            return {
                2: (width - x, y),
                3: (width - x, height - y),
                4: (x, height - y),
                5: (y, x),
                6: (height - y, x),
                7: (height - y, width - x),
                8: (y, width - x),
            }.get(orientation, (x, y))

        mapped = []
        for region in regions:
            if region.get("polygon_xy"):
                points = region["polygon_xy"]
                polygon = list(zip(points[::2], points[1::2]))
            elif region.get("bbox_xywh"):
                x, y, w, h = region["bbox_xywh"]
                polygon = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            else:
                continue
            mapped.append(
                {
                    "text": region["text"],
                    "input_polygon": [list(orient(*point)) for point in polygon],
                }
            )
        return {
            "dataset_id": identifier,
            "image": item["image"],
            "category": item["category"],
            "text": item["text"],
            "scope": details.get("scope", "source_declared_text"),
            "quality": details.get("annotation", {}).get("quality", "silver"),
            "reading_order_known": details.get(
                "reading_order_known", item["category"] != "textocr"
            ),
            "regions": mapped,
        }
