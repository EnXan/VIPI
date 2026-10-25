"""Present the active dataset catalog in the local workbench."""

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps


CATEGORY_LABELS = {
    "textocr": "TextOCR",
    "typographic_visual_prompt_injection": "Dagger7164",
    "cyberseceval3_visual_prompt_injection": "CyberSecEval3",
    "mm_safetybench": "MM-SafetyBench",
    "vpi_bench": "VPI-Bench",
    "injection": "Injection",
    "benign": "Benign",
    "context_dependent": "Context dependent",
}


class DatasetBrowser:
    def __init__(self, catalog, dataset="ocr_evaluation"):
        self.catalog = catalog
        self.dataset = dataset

    def listing(self, category="", query="", offset=0, limit=12):
        matches = self.catalog.search(category, query)
        counts = self.catalog.category_counts()
        return {
            "dataset": self.dataset,
            "total": len(matches),
            "catalog_total": len(self.catalog.items),
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
                    "thumbnail_url": f"/api/datasets/{item['id']}/thumbnail?dataset={self.dataset}",
                    "image_url": f"/api/datasets/{item['id']}/image?dataset={self.dataset}",
                    "case_count": len(item.get("cases", [])),
                }
                for item in matches[offset : offset + limit]
            ],
        }

    def thumbnail(self, identifier):
        with Image.open(self.catalog.path(identifier)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((320, 180))
            rgba = image.convert("RGBA")
            image = Image.alpha_composite(
                Image.new("RGBA", image.size, "white"), rgba
            ).convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)
        return buffer
