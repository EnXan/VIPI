"""Read detection images and their caller-context cases without changing data."""

import hashlib
import json
from collections import Counter
from pathlib import Path


class Catalog:
    def __init__(self, repository_root):
        self.directory = Path(repository_root).resolve() / "research/detection_eval"
        records = json.loads(
            (self.directory / "cases.json").read_text(encoding="utf-8")
        )
        self.items = {}
        for record in records:
            identifier = hashlib.sha256(record["image"].encode()).hexdigest()[:16]
            if identifier in self.items:
                raise ValueError("Duplicate image in the detection selection.")
            cases = record["cases"]
            if not cases or any(
                case["expected"] not in {"injection", "benign"} for case in cases
            ):
                raise ValueError("Detection images require labeled cases.")
            payloads = {case["payload"] for case in cases}
            if len(payloads) != 1:
                raise ValueError("Cases sharing an image must share its exact payload.")
            expected = {case["expected"] for case in cases}
            category = (
                "context_dependent" if len(expected) > 1 else next(iter(expected))
            )
            self.items[identifier] = {
                **record,
                "id": identifier,
                "category": category,
                "text": cases[0]["payload"],
            }

    def get(self, identifier):
        if identifier not in self.items:
            raise ValueError("Image is not in the detection selection.")
        return self.items[identifier]

    def path(self, identifier):
        path = (self.directory / self.get(identifier)["image"]).resolve()
        if (
            not path.is_relative_to((self.directory / "images").resolve())
            or not path.is_file()
        ):
            raise ValueError("Selected dataset image is unavailable.")
        return path

    def search(self, category="", query=""):
        if category and category not in self.category_counts():
            raise ValueError("Unknown dataset category.")
        return [
            item
            for item in self.items.values()
            if (not category or item["category"] == category)
            and (
                not query
                or query.casefold()
                in " ".join(
                    [
                        item["image"],
                        item["text"],
                        *item["techniques"],
                        *item["obfuscation"],
                        *(case.get("context", "") for case in item["cases"]),
                    ]
                ).casefold()
            )
        ]

    def category_counts(self):
        return dict(Counter(item["category"] for item in self.items.values()))

    def reference(self, identifier):
        item = self.get(identifier)
        regions = []
        for region in item.get("payload_regions") or []:
            if "bbox_xywh" in region:
                x, y, width, height = region["bbox_xywh"]
                polygon = [
                    [x, y],
                    [x + width, y],
                    [x + width, y + height],
                    [x, y + height],
                ]
            elif "polygon_xy" in region:
                points = region["polygon_xy"]
                polygon = list(zip(points[::2], points[1::2]))
            else:
                raise ValueError("Payload regions require bbox_xywh or polygon_xy.")
            regions.append({"text": region["text"], "input_polygon": polygon})
        return {
            "dataset_id": identifier,
            "image": item["image"],
            "category": item["category"],
            "text": item["text"],
            "scope": "primary_visible_payload",
            "quality": "reviewed_payload",
            "reading_order_known": not bool(regions),
            "regions": regions,
            "regions_are_independent": bool(regions),
        }
