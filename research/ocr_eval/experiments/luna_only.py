"""Small, frozen Luna transcription trial with saved product-run controls.

Prepare and run: ``uv run python -m research.ocr_eval.experiments.luna_only RUN_DIR``.
Use ``--prepare-only`` to freeze the selection without making API calls.
Terminal and interrupted attempts are retained and never automatically retried.
"""

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from unittest.mock import patch

from PIL import Image, ImageOps

from research.ocr_eval.benchmark import ROOT, catalogs, digest
from research.ocr_eval.evaluation.metrics import compare_words, evaluation_policy
from research.ocr_eval.evaluation.words import words
from vipi.config import cache_directory
from vipi.ocr import cloud
from vipi.ocr.costs import decisions_estimated_usd

BASELINE = ROOT / "research/ocr_eval/reports/PRODUCT_OCR_1113_2026-11-02.json"
TEXT_OCR_CASES = ("134dec2f24804b77", "312dbf8b568cfef0", "94939c68120f8ae9")


def save(path, value):
    """Write one durable JSON artifact before starting the next request."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def text_score(reference, text):
    """Reuse word matching while explicitly removing localization requirements.

    Known reading order remains required. Unordered references use distinct
    transcript tokens at a shared synthetic location; these are not model boxes.
    Independent-region geometry conflicts are outside this diagnostic metric.
    """
    reference = deepcopy(reference)
    polygon = [[0, 0], [1, 0], [1, 1], [0, 1]]
    reference["regions_are_independent"] = False
    for region in reference["regions"]:
        region["input_polygon"] = polygon
    observations = [{"text": word, "input_polygon": polygon} for word in words(text)]
    return compare_words(reference, text, observations)[0]


def memberships(row):
    """Use the same categories and overlapping facets as the full benchmark."""
    groups = [f"category/{row['suite']}/{row['category']}"]
    for facet in ("obfuscation", "techniques"):
        groups.extend(f"{facet}/{label}" for label in row[facet])
    if row["family"]:
        groups.append(f"family/{row['family']}")
    return groups


def prepare(directory):
    """Freeze three cases per main category and cover every overlapping subset."""
    baseline = json.loads(BASELINE.read_text())
    configurations = baseline["configurations"]
    controls = {
        name: {row["key"]: row for row in config["rows"]}
        for name, config in configurations.items()
    }
    groups = defaultdict(list)
    rows = controls["cloud-default"]
    for key, row in rows.items():
        for group in memberships(row):
            groups[group].append(key)
    selected = defaultdict(list)
    for group in sorted(groups):
        if not group.startswith("category/"):
            continue
        keys = sorted(groups[group])
        chosen = [keys[0], keys[len(keys) // 2], keys[-1]]
        if group == "category/ocr_eval/textocr":
            chosen = [f"ocr_eval:{identifier}" for identifier in TEXT_OCR_CASES]
        for key in chosen:
            selected[key].append(group)
    # Include all three requested Anamorpher cases; add one example of any
    # remaining uncovered facet. Stable IDs, never Luna outcomes, break ties.
    for group in sorted(
        groups, key=lambda value: (value != "family/anamorpher", value)
    ):
        if group.startswith("category/"):
            continue
        chosen = sorted(groups[group]) if group == "family/anamorpher" else []
        if not chosen and not any(key in selected for key in groups[group]):
            chosen = [min(groups[group])]
        for key in chosen:
            selected[key].append(group)
    data = catalogs()
    samples = []
    for key, reasons in selected.items():
        row = rows[key]
        catalog = data[row["suite"]]
        reference = catalog.reference(row["id"])
        encoded = json.dumps(reference, sort_keys=True, ensure_ascii=False).encode()
        assert hashlib.sha256(encoded).hexdigest() == row["reference_sha256"]
        assert digest(catalog.path(row["id"])) == row["image_sha256"]
        sample = {
            **row,
            "selected_for": reasons,
            "groups": memberships(row),
            "reference": reference,
            "controls": {},
        }
        for name, records in controls.items():
            control = records[key]
            saved = None
            if control["status"] == "completed":
                path = cache_directory() / "runs" / control["run_id"] / "result.json"
                assert digest(path) == control["result_sha256"]
                saved = json.loads(path.read_text())["text"]
            sample["controls"][name] = {
                "status": control["status"],
                "run_id": control.get("run_id"),
                "result_sha256": control.get("result_sha256"),
                "text": saved,
                "published_spatial_score": control["score"],
                "text_score": text_score(reference, saved or ""),
            }
        samples.append(sample)
    sources = sorted((ROOT / "src/vipi").rglob("*.py"))
    sources += sorted((ROOT / "research/ocr_eval/evaluation").glob("*.py"))
    sources += [Path(__file__), ROOT / "uv.lock"]
    hashes = {}
    for source in sources:
        relative = source.relative_to(ROOT)
        target = directory / "executed-sources" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        hashes[str(relative)] = digest(source)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "dataset": json.loads((ROOT / "research/dataset.json").read_text()),
        "baseline_sha256": digest(BASELINE),
        "sources": hashes,
        "selection": "Three stable-ID positions per main category; TextOCR uses the three discussed failures. All Anamorpher cases and one example of each otherwise-uncovered facet are added. Deliberate development sample, not representative.",
        "evaluation": {
            **evaluation_policy(),
            "geometry": "removed for ALL configurations; text-only diagnostic",
        },
        "request": {
            "model": "gpt-6-luna",
            "reasoning_effort": "none",
            "image_detail": "original",
            "prompt": cloud.TRANSCRIPTION_PROMPT,
        },
        "samples": samples,
    }
    save(directory / "manifest.json", manifest)
    return manifest


def run(directory, manifest):
    """Make one direct Luna request per image, retaining raw responses and errors."""
    for relative, expected in manifest["sources"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"Frozen source changed: {relative}")
    engine = cloud.LunaEngine()
    data = catalogs()
    transport = cloud.request_json
    for index, sample in enumerate(manifest["samples"], 1):
        destination = directory / "attempts" / sample["key"].replace(":", "-")
        destination.mkdir(parents=True, exist_ok=True)
        record_path = destination / "record.json"
        if record_path.exists():
            continue
        path = data[sample["suite"]].path(sample["id"])
        if digest(path) != sample["image_sha256"]:
            raise ValueError(f"Frozen image changed: {path}")
        record = {
            "key": sample["key"],
            "status": "started",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        save(record_path, record)

        def capture(url, payload, key):
            response = transport(url, payload, key)
            save(destination / "response.json", response)
            return response

        started = time.perf_counter()
        try:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                with patch.object(cloud, "request_json", capture):
                    result = engine.recognize(image)
            save(destination / "result.json", result)
            record.update(
                status="completed",
                score=text_score(sample["reference"], result["text"]),
            )
        except Exception as error:
            record.update(
                status="failed",
                error=f"{type(error).__name__}: {error}".replace(
                    engine.key, "[redacted]"
                ),
            )
        record["elapsed_seconds"] = time.perf_counter() - started
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        response_path = destination / "response.json"
        record["estimated_usd"] = None
        if response_path.exists():
            usage = json.loads(response_path.read_text()).get("usage") or {}
            incoming_cost = decisions_estimated_usd(usage)
            outgoing = usage.get("output_tokens")
            if incoming_cost is not None and type(outgoing) is int and outgoing >= 0:
                record["estimated_usd"] = incoming_cost + outgoing * 0.50 / 1_000_000
            record["usage"] = usage
        save(record_path, record)
        print(
            f"{index}/{len(manifest['samples'])} {sample['key']} {record['status']}",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    path = args.directory / "manifest.json"
    manifest = (
        json.loads(path.read_text()) if path.exists() else prepare(args.directory)
    )
    print(f"Frozen sample: {len(manifest['samples'])} images", flush=True)
    if not args.prepare_only:
        run(args.directory, manifest)


if __name__ == "__main__":
    main()
