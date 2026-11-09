"""Read the evaluation dataset (ADR 0053) without changing it.

The dataset folder holds ``catalog.json``, ``vocabulary.json`` and the images
the catalog points to. One class serves every reader: listing and filtering,
image paths, the OCR reference of an image and the verdicts a detector is
expected to give.
"""

from collections import Counter
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "research/dataset"
CATALOG_NAME = "catalog.json"
FILTERS = ("label", "content", "source")
ORIENTATION_TAG = 274  # EXIF orientation; regions are given for the stored pixels


class Catalog:
    def __init__(self, directory=DIRECTORY):
        self.directory = Path(directory).resolve()
        path = self.directory / CATALOG_NAME
        if not path.is_file():
            raise ValueError(
                f"No dataset in {self.directory}. Run: uv run python -m research.download"
            )
        self.items = {}
        for entry in json.loads(path.read_text(encoding="utf-8")):
            if entry["id"] in self.items:
                raise ValueError(f"Duplicate entry {entry['id']} in the dataset.")
            self.items[entry["id"]] = entry

    def get(self, identifier):
        if identifier not in self.items:
            raise ValueError("Image is not in the dataset.")
        return self.items[identifier]

    def path(self, identifier):
        path = (self.directory / self.get(identifier)["image"]).resolve()
        if not path.is_relative_to(self.directory) or not path.is_file():
            raise ValueError("Dataset image is unavailable.")
        return path

    @staticmethod
    def value(entry, field):
        if field == "source":
            return entry["source"].get("dataset") or "unknown"
        return entry[field]

    def search(self, query="", **filters):
        """Entries matching every given filter (label, content, source) and the
        query, which is looked up in the image name and the visible text."""
        unknown = set(filters) - set(FILTERS)
        if unknown:
            raise ValueError(f"Filter by {', '.join(FILTERS)}.")
        needle = query.casefold()
        return [
            entry
            for entry in self.items.values()
            if all(
                not wanted or self.value(entry, field) == wanted
                for field, wanted in filters.items()
            )
            and (not needle or needle in self.searchable(entry))
        ]

    @staticmethod
    def searchable(entry):
        reference = entry["ocr_reference"] or {}
        return " ".join(
            [
                entry["id"],
                entry["image"],
                entry["payload"] or "",
                reference.get("text") or "",
            ]
        ).casefold()

    def counts(self, field):
        return dict(Counter(self.value(entry, field) for entry in self.items.values()))

    def reference(self, identifier):
        """The OCR reference in the shape the OCR metrics expect, or None when
        the image has no reference text."""
        entry = self.get(identifier)
        reference = entry["ocr_reference"]
        if not reference:
            return None
        regions = reference.get("regions") or []
        orient = self.orientation(identifier) if regions else None
        return {
            "dataset_id": identifier,
            "image": entry["image"],
            "label": entry["label"],
            "content": entry["content"],
            "text": reference["text"],
            "scope": reference["scope"],
            "quality": reference["quality"],
            "reading_order_known": reference["reading_order_known"],
            "regions": [
                {
                    "text": region["text"],
                    "input_polygon": [list(orient(*p)) for p in polygon],
                }
                for region in regions
                if (polygon := self.polygon(region))
            ],
            # detection payload regions are separate fragments, not one reading
            "regions_are_independent": reference["scope"] == "primary_visible_payload"
            and bool(regions),
        }

    @staticmethod
    def polygon(region):
        if region.get("polygon_xy"):
            points = region["polygon_xy"]
            return list(zip(points[::2], points[1::2]))
        if region.get("bbox_xywh"):
            x, y, w, h = region["bbox_xywh"]
            return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        return None

    def orientation(self, identifier):
        with Image.open(self.path(identifier)) as image:
            width, height = image.size
            orientation = image.getexif().get(ORIENTATION_TAG, 1)
        mapping = {
            2: lambda x, y: (width - x, y),
            3: lambda x, y: (width - x, height - y),
            4: lambda x, y: (x, height - y),
            5: lambda x, y: (y, x),
            6: lambda x, y: (height - y, x),
            7: lambda x, y: (height - y, width - x),
            8: lambda x, y: (y, width - x),
        }
        return mapping.get(orientation, lambda x, y: (x, y))

    def cases(self, identifier):
        """Expected detector verdicts: first without caller context, from the
        label (benign is not flagged; injection and jailbreak are), then any
        caller-context cases from the catalog."""
        entry = self.get(identifier)
        cases = [{"expected": "benign" if entry["label"] == "benign" else "injection"}]
        for case in entry["cases"]:
            if case.get("context"):
                cases.append({"expected": case["expected"], "context": case["context"]})
        return cases
