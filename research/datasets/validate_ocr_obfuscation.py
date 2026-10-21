#!/usr/bin/env python3
"""Validate the active OCR filter sample, including pixels and reproducibility."""

from __future__ import annotations

import concurrent.futures
import copy
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

import obfuscate_ocr_images as filters


def main() -> None:
    manifest = json.loads(filters.MANIFEST.read_text())
    baseline, clean_report = filters.baseline()
    full_catalog = json.loads((filters.CATALOG / "ocr_metadata.json").read_text())
    active = [item for item in full_catalog if item["category"] != "anamorpher"]
    report = json.loads((filters.CATALOG / "ocr_selection_report.json").read_text())
    assert len(active) == len(baseline) == 1000
    schema = json.loads((filters.CATALOG / "ocr_metadata.schema.json").read_text())
    Draft202012Validator(schema).validate(full_catalog)
    changed = {index for index, (original, variant) in enumerate(zip(baseline, active, strict=True))
               if original != variant}
    assert changed == {record["catalog_index"] for record in manifest["records"]}
    assert len(changed) == 150
    for original, variant in zip(baseline, active, strict=True):
        assert original["text"] == variant["text"]
        assert original["category"] == variant["category"]
        assert (filters.ROOT / variant["image"]).is_file()
    clean_refs = {record["image"]: record for record in clean_report["selected_references"]}
    active_refs = {record["image"]: record for record in report["selected_references"]}

    def check(record: dict[str, Any]) -> dict[str, Any]:
        source, output = filters.ROOT / record["source_image"], filters.ROOT / record["output_image"]
        assert filters.digest(source) == record["source_sha256"]
        assert filters.digest(output) == record["output_sha256"] == record["review"]["reviewed_output_sha256"]
        assert record["review"]["status"] == "accepted"
        assert filters.size(output) == (record["width"], record["height"])
        original, updated = clean_refs[record["source_image"]], active_refs[record["output_image"]]
        assert updated["sha256"] == record["output_sha256"]
        for field in ("regions", "ignored_regions", "scope", "annotation", "content_group_id", "rights"):
            assert original[field] == updated[field], field
        comparison = subprocess.run(
            ["magick", "compare", "-metric", "RMSE", str(source), str(output), "null:"],
            text=True, capture_output=True,
        )
        assert comparison.returncode in (0, 1), comparison.stderr
        return {"catalog_index": record["catalog_index"], "rmse": comparison.stderr.strip(),
                "pixels_changed": comparison.returncode == 1}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(check, manifest["records"]))
    verified_methods = []
    with tempfile.TemporaryDirectory(prefix="ocr_repeat_") as temporary:
        for method in filters.METHODS:
            original = next(record for record in manifest["records"] if record["method"] == method)
            duplicate = copy.deepcopy(original)
            duplicate["output_image"] = str(Path(temporary) / (method + ".png"))
            assert filters.render_record(duplicate)["output_sha256"] == original["output_sha256"], method
            verified_methods.append(method)
    identical = [result for result in results if not result["pixels_changed"]]
    summary = {
        "total": len(full_catalog), "filter_base_count": 1000, "changed_paths": 150, "unchanged_records": 850,
        "text_and_categories_unchanged": True, "source_hashes_unchanged": True,
        "dimensions_unchanged": True, "regions_scopes_and_annotations_unchanged": True,
        "schema_valid": True, "deterministic_rerender_verified_methods": verified_methods,
        "visually_reviewed": 150, "pixel_identical_outputs": identical,
        "pixel_comparisons": results,
    }
    filters.write_json_atomic(summary, filters.CATALOG / "ocr_obfuscation_validation.json")
    print(json.dumps({key: value for key, value in summary.items() if key != "pixel_comparisons"}, indent=2))
    assert not identical, "Some filters made no pixel changes"


if __name__ == "__main__":
    main()
