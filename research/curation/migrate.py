"""Build the combined draft catalog from the two pinned catalogs.

Known values are carried over as prefill and every entry starts unreviewed.
Source texts, contexts, regions and provenance are copied as supplied.
Byte-identical images present in both catalogs become one entry.
"""

import json
from pathlib import Path
import re

from research.ocr_eval.benchmark import ROOT, digest

from .vocabulary import seed

DEFAULT_OUTPUT = Path(".local-assets/dataset-submission")
CATALOG_NAME = "catalog.json"
VOCABULARY_NAME = "vocabulary.json"

# Prefill from the source dataset; every value stays unreviewed.
OCR_LABELS = {
    "textocr": "benign",
    "typographic_visual_prompt_injection": "injection",
    "cyberseceval3_visual_prompt_injection": "injection",
    "vpi_bench": "injection",
    "mm_safetybench": "jailbreak",
}
OCR_CONTENT = {
    "textocr": "real_world",
    "typographic_visual_prompt_injection": "text_image",
    "mm_safetybench": "text_image",
}
VPI_APP_CONTENT = {
    "amazon": "web_page",
    "booking": "web_page",
    "email": "email",
    "messenger": "chat",
}
TYPOGRAPHIC_OBFUSCATION = {"lowcontrast": "low_contrast", "distorted": "distorted_text"}
LICENSE_PATTERNS = (
    (r"CC[ -]BY[ -]NC[ -]4\.0", "CC-BY-NC-4.0"),
    (r"CC[ -]BY[ -]4\.0", "CC-BY-4.0"),
    (r"\bMIT\b", "MIT"),
)
# Detection filename prefixes with a source documented in the detection README
# or shared with an OCR source; others stay unknown for the curator.
DETECTION_SOURCES = {
    "dagger7164": "typographic_visual_prompt_injection",
    "facebook": "cyberseceval3_visual_prompt_injection",
    "vpi_bench": "vpi_bench",
    "anamorpher": "anamorpher",
    "ghostcommit": "ghostcommit",
    "sting": "sting",
    "synthetic": "synthetic",
    "phantom": "phantom",
    "figstep": "figstep",
}
DOCUMENTED_SOURCES = {
    "anamorpher": {"repository": "https://github.com/trailofbits/anamorpher"},
    "ghostcommit": {
        "repository": "https://github.com/asset-group/ghostcommit",
        "license": "MIT",
    },
}


def license_of(rights):
    if not rights:
        return None
    text = " ".join(str(rights.get(key) or "") for key in ("license", "usage_notes"))
    for pattern, name in LICENSE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return None


def blank(identifier, image, image_sha256):
    return {
        "id": identifier,
        "image": image,
        "image_sha256": image_sha256,
        "label": None,
        "techniques": [],
        "goal": [],
        "obfuscation": [],
        "evidence": [],
        "content": None,
        "payload": None,
        "cases": [],
        "ocr_reference": None,
        "source": {},
        "migrated_from": {},
        "curation": {
            "reviewed": False,
            "decision": "keep",
            "reason": None,
            "duplicate_of": None,
        },
    }


def ocr_entry(item, image_sha256):
    source = item.get("source") or {}
    category = item["category"]
    entry = blank(item["id"], f"ocr_eval/{item['image']}", image_sha256)
    entry["label"] = OCR_LABELS.get(category)
    entry["content"] = OCR_CONTENT.get(category)
    sample = source.get("sample_id", "")
    if category == "vpi_bench":
        app = sample.split(":", 1)[-1].split("_", 1)[0]
        entry["content"] = VPI_APP_CONTENT.get(app)
    if category == "typographic_visual_prompt_injection":
        variant = TYPOGRAPHIC_OBFUSCATION.get(sample.rsplit(":", 1)[-1])
        entry["obfuscation"] = [variant] if variant else []
    entry["ocr_reference"] = {
        "text": item["text"],
        "scope": item.get("scope"),
        "quality": item.get("quality"),
        "reading_order_known": item.get("reading_order_known"),
        "regions": item.get("regions"),
    }
    entry["source"] = {
        "dataset": category,
        "repository": source.get("repository"),
        "sample_id": source.get("sample_id"),
        "license": license_of(source.get("rights")),
        "provenance": source.get("provenance"),
        "content_group_id": source.get("content_group_id"),
    }
    entry["migrated_from"] = {"ocr_eval": {"id": item["id"], "image": item["image"]}}
    return entry


def detection_label(item):
    if "jailbreak" in item["techniques"]:
        return "jailbreak"
    plain = {case["expected"] for case in item["cases"] if not case.get("context")}
    return next(iter(plain)) if len(plain) == 1 else None


def detection_source(item, licenses):
    prefix = next(
        (key for key in DETECTION_SOURCES if Path(item["image"]).name.startswith(key)),
        None,
    )
    dataset = DETECTION_SOURCES.get(prefix)
    documented = DOCUMENTED_SOURCES.get(dataset, {})
    return {
        "dataset": dataset,
        "repository": documented.get("repository"),
        "sample_id": None,
        "license": documented.get("license", licenses.get(dataset)),
        "provenance": None,
        "content_group_id": None,
    }


def detection_fields(item):
    """Fields contributed by a detection entry, regardless of its image owner."""
    regions = item.get("payload_regions") or []
    return {
        "label": detection_label(item),
        "techniques": [t for t in item["techniques"] if t != "jailbreak"],
        "obfuscation": list(item["obfuscation"]),
        "payload": item["text"],
        "cases": [
            {key: case[key] for key in ("expected", "context") if key in case}
            for case in item["cases"]
        ],
        "reference": {
            "text": item["text"],
            "scope": "primary_visible_payload",
            "quality": "reviewed_payload",
            "reading_order_known": not regions,
            "regions": regions or None,
        },
    }


def merge_detection(entry, item, licenses):
    """Apply a detection entry to an existing entry with the same image bytes."""
    fields = detection_fields(item)
    entry["label"] = fields["label"] or entry["label"]
    entry["techniques"] = fields["techniques"]
    entry["obfuscation"] = sorted(
        set(entry["obfuscation"]) | set(fields["obfuscation"])
    )
    entry["payload"] = fields["payload"]
    entry["cases"] = fields["cases"]
    if entry["ocr_reference"] is None:
        entry["ocr_reference"] = fields["reference"]
    if not entry["source"]:
        entry["source"] = detection_source(item, licenses)
    entry["migrated_from"]["detection_eval"] = {
        "id": item["id"],
        "image": item["image"],
    }
    return entry


def build(root=ROOT):
    """Return ``(catalog, vocabulary)`` for the pinned catalogs under ``root``."""
    from research.ocr_eval.benchmark import catalogs

    loaded = catalogs(root)
    ocr, detection = loaded["ocr_eval"], loaded["detection_eval"]
    catalog, by_hash, licenses = [], {}, {}
    for identifier, item in ocr.items.items():
        entry = ocr_entry(item, digest(ocr.path(identifier)))
        licenses.setdefault(entry["source"]["dataset"], entry["source"]["license"])
        by_hash[entry["image_sha256"]] = entry
        catalog.append(entry)
    for identifier, item in detection.items.items():
        image_sha256 = digest(detection.path(identifier))
        if image_sha256 in by_hash:
            merge_detection(by_hash[image_sha256], item, licenses)
            continue
        entry = blank(identifier, f"detection_eval/{item['image']}", image_sha256)
        merge_detection(entry, item, licenses)
        entry["source"] = detection_source(item, licenses)
        by_hash[image_sha256] = entry
        catalog.append(entry)
    return catalog, seed()


def write(output, catalog, vocabulary, force=False):
    output = Path(output)
    targets = [output / CATALOG_NAME, output / VOCABULARY_NAME]
    existing = [path for path in targets if path.exists()]
    if existing and not force:
        raise ValueError(
            f"{existing[0]} already exists and may hold labeling work; "
            "pass --force to replace it."
        )
    output.mkdir(parents=True, exist_ok=True)
    for path, value in zip(targets, (catalog, vocabulary)):
        path.write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return targets
