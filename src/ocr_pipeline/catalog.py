"""Read the active OCR selection without modifying dataset files."""

import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageOps

CATEGORY_LABELS = {
    "textocr": "TextOCR",
    "anamorpher": "Anamorpher",
    "typographic_visual_prompt_injection": "Dagger7164",
    "cyberseceval3_visual_prompt_injection": "CyberSecEval3",
    "mm_safetybench": "MM-SafetyBench",
    "vpi_bench": "VPI-Bench",
}


class Catalog:
    def __init__(self, repository_root):
        self.root = Path(repository_root).resolve()
        directory = self.root / "datasets/catalog/ocr"
        records = json.loads(
            (directory / "ocr_metadata.json").read_text(encoding="utf-8")
        )
        report_path = directory / "ocr_selection_report.json"
        report = (
            json.loads(report_path.read_text(encoding="utf-8"))
            if report_path.exists()
            else {}
        )
        details = {
            item["image"]: item for item in report.get("selected_references", [])
        }
        self.items = {}
        for record in records:
            identifier = hashlib.sha256(record["image"].encode()).hexdigest()[:16]
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
        identifier = hashlib.sha256(relative.encode()).hexdigest()[:16]
        return self.reference(identifier)

    def path(self, identifier):
        path = (self.root / self.get(identifier)["image"]).resolve()
        if not path.is_relative_to(self.root / "datasets") or not path.is_file():
            raise ValueError("Selected dataset image is unavailable.")
        return path

    def listing(self, category="", query="", offset=0, limit=12):
        if category and category not in {
            item["category"] for item in self.items.values()
        }:
            raise ValueError("Unknown dataset category.")
        matches = [
            item
            for item in self.items.values()
            if (not category or item["category"] == category)
            and (
                not query
                or query.casefold() in (item["image"] + " " + item["text"]).casefold()
            )
        ]
        counts = {}
        for item in self.items.values():
            counts[item["category"]] = counts.get(item["category"], 0) + 1
        return {
            "total": len(matches),
            "catalog_total": len(self.items),
            "offset": offset,
            "limit": limit,
            "categories": [
                {"id": key, "label": CATEGORY_LABELS.get(key, key), "count": value}
                for key, value in sorted(counts.items())
            ],
            "matching_ids": [item["id"] for item in matches],
            "items": [
                {
                    "id": item["id"],
                    "image": item["image"],
                    "category": item["category"],
                    "label": CATEGORY_LABELS.get(item["category"], item["category"]),
                    "name": Path(item["image"]).name,
                    "text_preview": item["text"][:180],
                    "thumbnail_url": f"/api/datasets/{item['id']}/thumbnail",
                    "image_url": f"/api/datasets/{item['id']}/image",
                }
                for item in matches[offset : offset + limit]
            ],
        }

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

    def thumbnail(self, identifier):
        with Image.open(self.path(identifier)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((320, 180))
            rgba = image.convert("RGBA")
            image = Image.alpha_composite(
                Image.new("RGBA", image.size, "white"), rgba
            ).convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)
        return buffer
