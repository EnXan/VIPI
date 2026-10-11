#!/usr/bin/env python3
"""Read local TextOCR word references for full-scene OCR evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from import_mm_safetybench import jpeg_properties, sha256_file


DATASET_ID = "textocr"
REPOSITORY = "https://textvqa.org/textocr/dataset/"


def build_records(project_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    source_root = project_root / "datasets/external/text-ocr"
    annotation_path = source_root / "TextOCR_0.1_train.json"
    data = json.loads(annotation_path.read_text(encoding="utf-8"))
    images, annotations = data["imgs"], data["anns"]
    image_to_annotations = data.get("imgToAnns", data.get("img2Anns"))
    if not isinstance(image_to_annotations, dict):
        raise ValueError("TextOCR has no image-to-annotation mapping")
    annotation_relative = annotation_path.relative_to(project_root).as_posix()
    records, excluded = [], []
    for image_id, image in sorted(images.items()):
        sample_id = f"{DATASET_ID}:{image_id}"
        if Path(image_id).name != image_id or image["id"] != image_id:
            raise ValueError(f"Invalid TextOCR image ID: {image_id}")
        image_path = source_root / "train_images" / f"{image_id}.jpg"
        if not image_path.is_file():
            excluded.append({"sample_id": sample_id, "reason": "missing_image"})
            continue
        ids = image_to_annotations[image_id]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate TextOCR word annotations: {image_id}")
        regions, ignored = [], []
        for annotation_id in ids:
            annotation = annotations[annotation_id]
            if annotation["image_id"] != image_id or annotation["id"] != annotation_id:
                raise ValueError(f"TextOCR annotation mapping mismatch: {annotation_id}")
            text = annotation["utf8_string"]
            polygon, bbox = annotation["points"], annotation["bbox"]
            if len(polygon) < 6 or len(polygon) % 2 or len(bbox) != 4:
                raise ValueError(f"Invalid TextOCR geometry: {annotation_id}")
            region = {"annotation_id": annotation_id, "text": text,
                      "polygon_xy": polygon, "bbox_xywh": bbox}
            if text.strip() in {"", "."}:
                ignored.append(region)
            else:
                regions.append(region)
        if not regions:
            excluded.append({"sample_id": sample_id, "reason": "no_transcribed_textocr_words"})
            continue
        width, height, color_mode, bit_depth = jpeg_properties(image_path)
        if (width, height) != (image["width"], image["height"]):
            raise ValueError(f"TextOCR image/annotation dimension mismatch: {image_path}")
        records.append({
            "sample_id": sample_id,
            "asset": {"path": image_path.relative_to(project_root).as_posix(),
                      "sha256": sha256_file(image_path), "width": width, "height": height,
                      "color_mode": color_mode, "bit_depth": bit_depth},
            "source": {"dataset_id": DATASET_ID, "repository": REPOSITORY,
                       "split": image["set"]},
            "group": {"content_group_id": sample_id},
            "ocr": {
                "has_ground_truth_text": True,
                # Preserve each word literally. Newlines delimit source annotations,
                # not inferred text lines; source annotation order is not reading order.
                "transcript_verbatim": "\n".join(region["text"] for region in regions),
                "scope": "source_declared_text", "reading_order_known": False,
                "regions": regions, "ignored_regions": ignored,
                "annotation": {"provenance": annotation_relative + ":anns.utf8_string; source annotation order",
                               "quality": "silver", "verified": False},
            },
            "eligibility": {"ocr_eval": True},
            "rights": {"license": "CC-BY-4.0", "attribution_required": True,
                       "usage_notes": "Attribute TextOCR and its authors; original image rights remain applicable. No training permission is inferred by this OCR import."},
        })
    return records, excluded
