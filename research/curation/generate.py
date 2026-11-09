"""Render a generated-image spec and turn it into catalog entries.

Rendering lives in ``render.py``. Images are written to
``<images root>/generated/incoming/<id>.png``; the id is the start of the PNG's
SHA-256, so rendering the same spec again adds nothing. A spec sets ``label``,
``content`` and optionally ``style``; each item sets ``text``, ``kind`` and
``obfuscation`` and may set ``style``, ``content``, ``label``, ``techniques``,
``goal``, ``evidence``, ``license`` and ``provenance``. For ``split_text`` and
``flowchart``, ``|`` in the text marks the panels or steps. An item with a
``template`` is an interface screenshot rendered by ``screens.py``; its OCR
reference covers the target text only. An item with a ``base_image`` (a path
under the images root) puts its text over that photo as faint white text
(``high_transparency``); it may also apply the image-level transforms in
``DERIVED``. With ``text_regions``, split fragments are placed at normalized
photo coordinates and target-only distortion stays on those fragments. Its OCR
reference covers the overlaid text only. An item with empty ``text`` (an
``image_only`` attack or its wordless benign counterpart) saves no payload or OCR reference; the template draws
the visual cues from the spec.
An item with ``from`` (a catalog entry id) applies the image-level
obfuscations in ``DERIVED`` to that entry's image and copies its labels, text,
OCR reference and source, noting the derivation in the provenance.
"""

import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

from PIL import Image

from . import screens
from .render import finish, overlay, overlay_regions, reading_text, render, visible_text

IMAGE_FOLDER = "generated/incoming"
RENDER_WORKERS = min(6, os.cpu_count() or 1)
DERIVED = {"blur", "distorted_text", "mirrored_text", "rotated_text"}
DERIVED_BACKGROUND = (255, 255, 255)


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def plain_text(item):
    return "template" not in item and "base_image" not in item


def texts(item):
    """Payload (the characters shown) and OCR reference (what a reader reads)."""
    if not item.get("text"):  # wordless image: no payload and no OCR reference
        return None, None
    if "template" in item:
        shown = screens.visible(item)
    else:
        shown = visible_text(item["text"], item["obfuscation"])
    reference = shown if "base64" in item["obfuscation"] else item["text"]
    return reading_text(shown), reading_text(reference)


def entry(spec, item, number, data, image_path):
    digest = hashlib.sha256(data).hexdigest()
    shown, reference = texts(item)
    image_only = shown is None
    name = Path(spec["path"]).stem
    return {
        "id": digest[:16],
        "image": image_path,
        "image_sha256": digest,
        "label": item.get("label", spec["label"]),
        "techniques": item.get("techniques", []),
        "goal": item.get("goal", []),
        "obfuscation": item["obfuscation"],
        "evidence": item.get("evidence", []),
        "content": item.get("content", spec["content"]),
        "payload": None if image_only else shown,
        "cases": [{"expected": item.get("label", spec["label"])}],
        "ocr_reference": None
        if image_only
        else {
            "text": reference,
            "scope": "rendered_text" if plain_text(item) else "target_text_only",
            "quality": "gold",
            "reading_order_known": True,
            "regions": None,
        },
        "source": {
            "dataset": "vipi_generated",
            "repository": "https://github.com/EnXan/VIPI",
            "sample_id": f"vipi_generated:{name}:{number:03d}",
            "license": item.get("license", "Apache-2.0"),
            "provenance": item.get(
                "provenance",
                f"research/curation/generated/{name}.json ({item['kind']})",
            ),
            "content_group_id": f"vipi_generated:{name}:{number:03d}",
        },
        "migrated_from": {},
        "curation": {
            "reviewed": False,
            "decision": "keep",
            "reason": None,
            "duplicate_of": None,
        },
    }


def derived_entry(original, item, data, image_path):
    digest = hashlib.sha256(data).hexdigest()
    added = item["obfuscation"]
    source = original["source"]
    note = f"{', '.join(added)} applied by research/curation/render.py"
    return {
        **original,
        "id": digest[:16],
        "image": image_path,
        "image_sha256": digest,
        "obfuscation": sorted({*original["obfuscation"], *added}),
        "source": {
            **source,
            "sample_id": f"{source.get('sample_id') or original['id']}:{'+'.join(added)}",
            "provenance": f"{source.get('provenance')}; {note}; replaces entry "
            f"{original['id']}",
        },
        "migrated_from": {},
        "curation": {
            "reviewed": False,
            "decision": "keep",
            "reason": None,
            "duplicate_of": None,
        },
    }


def image(spec, item, number, images_root, originals):
    if "from" in item:
        if not item["obfuscation"] or set(item["obfuscation"]) - DERIVED:
            raise ValueError(f"Derived items take only {', '.join(sorted(DERIVED))}")
        if item["from"] not in originals:
            raise ValueError(f"Unknown entry {item['from']!r}")
        path = Path(images_root) / originals[item["from"]]["image"]
        with Image.open(path) as original:
            picture = original.convert("RGB")
        return finish(picture, item["obfuscation"], number, DERIVED_BACKGROUND)
    if "base_image" in item:
        if item["obfuscation"] != ["high_transparency"] and not (
            item["obfuscation"]
            and set(item["obfuscation"])
            <= {"blur", "distorted_text", "mirrored_text", "rotated_text"}
        ):
            raise ValueError(
                "Photo items take high_transparency or image-level transforms"
            )
        with Image.open(Path(images_root) / item["base_image"]) as photo:
            regional_text = "text_regions" in item
            if regional_text:
                picture = overlay_regions(
                    photo, item["text"], item["text_regions"], item["obfuscation"]
                )
            else:
                picture = overlay(photo, item["text"])
        if item["obfuscation"] == ["high_transparency"]:
            return picture
        image_obfuscation = item["obfuscation"]
        if regional_text:
            image_obfuscation = [
                name for name in image_obfuscation if name != "distorted_text"
            ]
        return finish(picture, image_obfuscation, number, (255, 255, 255))
    if "template" in item:
        return screens.screen(item, number)
    style = item.get("style", spec.get("style", "typographic"))
    return render(item["text"], item["obfuscation"], number, style)


def build(spec_path, images_root, known_ids=(), catalog=()):
    """Render a spec; write new images and return their catalog entries.

    ``catalog`` provides the entries that ``from`` items derive from."""
    originals = {original["id"]: original for original in catalog}
    spec = {
        **json.loads(Path(spec_path).read_text(encoding="utf-8")),
        "path": spec_path,
    }
    folder = Path(images_root) / IMAGE_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    numbered = list(enumerate(spec["items"], 1))
    # screenshots wait on a browser process each, so render items in parallel
    with ThreadPoolExecutor(RENDER_WORKERS) as pool:
        images = list(
            pool.map(
                lambda pair: png_bytes(
                    image(spec, pair[1], pair[0], images_root, originals)
                ),
                numbered,
            )
        )
    entries = []
    for (number, item), data in zip(numbered, images):
        identifier = hashlib.sha256(data).hexdigest()[:16]
        if identifier in known_ids:
            continue
        (folder / f"{identifier}.png").write_bytes(data)
        path = f"{IMAGE_FOLDER}/{identifier}.png"
        if "from" in item:
            entries.append(derived_entry(originals[item["from"]], item, data, path))
        else:
            entries.append(entry(spec, item, number, data, path))
    return entries
