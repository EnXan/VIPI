#!/usr/bin/env python3
"""Propose OCR text regions for CyberSecEval3 using local Tesseract OCR.

By default this runs a reproducible, layout-stratified pilot and writes only a
JSONL report under datasets/.cache/. Use --apply explicitly to fill missing OCR
regions from high-confidence detections; existing annotations are preserved.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATASET_ID = "cyberseceval3_visual_prompt_injection"
SHARD = ROOT / "datasets/catalog/sources/cyberseceval3_visual_prompt_injection.jsonl"
DEFAULT_REPORT = ROOT / "datasets/.cache/cyberseceval3_ocr_pilot.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="Pilot sample size (default: 50; 0 means all)")
    parser.add_argument("--seed", type=int, default=20261002, help="Seed for deterministic layout-stratified sampling")
    parser.add_argument("--psm", type=int, default=6, choices=range(14), help="Tesseract page segmentation mode (default: 6)")
    parser.add_argument("--layout", action="append", help="Optional source text_layout filter (repeatable, e.g. --layout numbered_list)")
    parser.add_argument("--min-score", type=float, default=0.88, help="Minimum combined text/confidence score eligible for --apply")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT, help="JSONL proposal report path")
    parser.add_argument("--apply", action="store_true", help="Apply eligible boxes to records with missing regions; never verifies or upgrades Gold")
    parser.add_argument("--tesseract", default="tesseract", help="Tesseract executable (default: found on PATH)")
    return parser.parse_args()


def read_shard() -> list[dict[str, Any]]:
    records = []
    with SHARD.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Ungültiges JSON in {SHARD}:{number}: {exc}") from exc
    return records


def choose_pilot(records: list[dict[str, Any]], limit: int, seed: int) -> list[dict[str, Any]]:
    if limit <= 0 or limit >= len(records):
        return records
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["visual"].get("text_layout", "unknown")].append(record)
    rng = random.Random(seed)
    for group in groups.values():
        rng.shuffle(group)
    selected: list[dict[str, Any]] = []
    keys = sorted(groups)
    while len(selected) < limit:
        changed = False
        for key in keys:
            if groups[key] and len(selected) < limit:
                selected.append(groups[key].pop())
                changed = True
        if not changed:
            break
    return selected


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return "".join(char for char in value if char.isalnum())


def tesseract_lines(executable: str, image: Path, psm: int) -> list[dict[str, Any]]:
    result = subprocess.run(
        [executable, str(image), "stdout", "--psm", str(psm), "tsv"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in csv.DictReader(result.stdout.splitlines(), delimiter="\t"):
        text = row.get("text", "").strip()
        if not text:
            continue
        try:
            confidence = float(row["conf"])
            box = [int(row[name]) for name in ("left", "top", "width", "height")]
        except (KeyError, ValueError):
            continue
        if box[2] <= 0 or box[3] <= 0:
            continue
        key = tuple(row.get(name, "0") for name in ("page_num", "block_num", "par_num", "line_num"))
        grouped[key].append({"text": text, "conf": confidence, "box": box})

    lines = []
    for words in grouped.values():
        x1 = min(word["box"][0] for word in words)
        y1 = min(word["box"][1] for word in words)
        x2 = max(word["box"][0] + word["box"][2] for word in words)
        y2 = max(word["box"][1] + word["box"][3] for word in words)
        lines.append({
            "text": " ".join(word["text"] for word in words),
            "confidence": sum(word["conf"] for word in words) / len(words),
            "box": [x1, y1, x2 - x1, y2 - y1],
        })
    return lines


def compare_text(expected: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
    target = normalized(expected)
    if not target or not lines:
        return {"score": 0.0, "text_similarity": 0.0, "ocr_confidence": 0.0, "lines": [], "bbox": None, "recognized_text": ""}

    best: dict[str, Any] | None = None
    max_window = min(len(lines), 12)
    for start in range(len(lines)):
        for end in range(start + 1, min(len(lines), start + max_window) + 1):
            candidate = lines[start:end]
            candidate_text = " ".join(line["text"] for line in candidate)
            candidate_normalized = normalized(candidate_text)
            similarity = difflib.SequenceMatcher(None, target, candidate_normalized, autojunk=False).ratio()
            confidence = sum(line["confidence"] for line in candidate) / len(candidate)
            combined = 0.75 * similarity + 0.25 * max(0.0, confidence / 100)
            if best is None or combined > best["score"]:
                x1 = min(line["box"][0] for line in candidate)
                y1 = min(line["box"][1] for line in candidate)
                x2 = max(line["box"][0] + line["box"][2] for line in candidate)
                y2 = max(line["box"][1] + line["box"][3] for line in candidate)
                best = {
                    "score": combined,
                    "text_similarity": similarity,
                    "ocr_confidence": confidence,
                    "lines": candidate,
                    "bbox": [x1, y1, x2 - x1, y2 - y1],
                    "recognized_text": candidate_text,
                }
    assert best is not None
    return best


def analyze_record(record: dict[str, Any], executable: str, psm: int) -> dict[str, Any]:
    image = ROOT / record["asset"]["path"]
    lines = tesseract_lines(executable, image, psm)
    match = compare_text(record["ocr"]["transcript_verbatim"], lines)
    existing_regions = record["ocr"].get("regions")
    if isinstance(existing_regions, list) and existing_regions:
        status = "already_annotated"
    elif match["score"] >= 0.88 and match["text_similarity"] >= 0.85:
        status = "high_confidence"
    elif match["score"] >= 0.70 and match["text_similarity"] >= 0.60:
        status = "review_candidate"
    else:
        status = "low_confidence"
    return {
        "sample_id": record["sample_id"],
        "layout": record["visual"].get("text_layout"),
        "scope": record["ocr"].get("scope"),
        "status": status,
        "score": round(match["score"], 4),
        "text_similarity": round(match["text_similarity"], 4),
        "ocr_confidence": round(match["ocr_confidence"], 2),
        "transcript": record["ocr"]["transcript_verbatim"],
        "recognized_text": match["recognized_text"],
        "bbox_xywh": match["bbox"],
        "image": record["asset"]["path"],
        "tesseract_psm": psm,
    }


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
    temporary.replace(path)


def apply_proposals(records: list[dict[str, Any]], proposals: list[dict[str, Any]], min_score: float) -> int:
    by_id = {record["sample_id"]: record for record in records}
    applied = 0
    for proposal in proposals:
        record = by_id[proposal["sample_id"]]
        if proposal["status"] != "high_confidence" or proposal["score"] < min_score:
            continue
        if record["ocr"].get("regions"):
            continue
        box = proposal["bbox_xywh"]
        if not isinstance(box, list) or len(box) != 4:
            continue
        width, height = record["asset"]["width"], record["asset"]["height"]
        x, y, box_width, box_height = box
        if x < 0 or y < 0 or box_width <= 0 or box_height <= 0 or x + box_width > width or y + box_height > height:
            continue
        record["ocr"]["regions"] = [{
            "role": "injected_text",
            "text": record["ocr"]["transcript_verbatim"],
            "coordinate_system": "absolute_pixels",
            "bbox_xywh": box,
        }]
        typography = record["visual"].setdefault("typography", {})
        if typography.get("text_origin_xy_px") is None:
            typography["text_origin_xy_px"] = [x, y]
        annotation = record["ocr"].setdefault("annotation", {})
        annotation["provenance"] = (annotation.get("provenance", "") + "; ").lstrip("; ") + "auto:tesseract-tsv; text-match score=" + str(proposal["score"])
        if annotation.get("quality") != "gold":
            annotation["quality"] = "silver"
            annotation["verified"] = False
        applied += 1
    return applied


def write_shard(records: list[dict[str, Any]], expected_sample_ids: set[str]) -> None:
    actual_sample_ids = {str(record["sample_id"]) for record in records}
    if actual_sample_ids != expected_sample_ids:
        missing = sorted(expected_sample_ids - actual_sample_ids)
        extra = sorted(actual_sample_ids - expected_sample_ids)
        raise ValueError(
            "Refusing to replace the source shard because its sample IDs changed "
            f"(missing={len(missing)}, extra={len(extra)})."
        )
    atomic_write_jsonl(SHARD, records)
    subprocess.run([sys.executable, str(ROOT / "scripts/build_metadata_catalog.py")], cwd=ROOT, check=True)


def main() -> int:
    args = parse_args()
    executable = shutil.which(args.tesseract)
    if not executable:
        raise SystemExit(f"Tesseract nicht gefunden: {args.tesseract}. Installiere Tesseract oder nutze --tesseract.")
    if not 0 <= args.min_score <= 1:
        raise SystemExit("--min-score muss zwischen 0 und 1 liegen.")
    records = read_shard()
    expected_sample_ids = {str(record["sample_id"]) for record in records}
    records_to_analyze = records
    if args.layout:
        requested_layouts = set(args.layout)
        records_to_analyze = [record for record in records if record["visual"].get("text_layout", "unknown") in requested_layouts]
        if not records_to_analyze:
            raise SystemExit(f"Keine CyberSecEval3-Einträge mit Layout: {', '.join(sorted(requested_layouts))}")
    selected = choose_pilot(records_to_analyze, args.limit, args.seed)
    proposals = [analyze_record(record, executable, args.psm) for record in selected]
    atomic_write_jsonl(args.output.resolve(), proposals)

    counts = Counter(proposal["status"] for proposal in proposals)
    layout_filter = f", Layoutfilter: {', '.join(sorted(args.layout))}" if args.layout else ""
    print(f"Analysiert: {len(proposals)} CyberSecEval3-Bilder (PSM {args.psm}, Seed {args.seed}{layout_filter})")
    print("Layouts: " + ", ".join(f"{key}={value}" for key, value in sorted(Counter(p["layout"] for p in proposals).items())))
    print("Ergebnis: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print(f"Bericht: {args.output.resolve()}")
    eligible = sum(p["status"] == "high_confidence" and p["score"] >= args.min_score for p in proposals)
    print(f"Hochkonfidente Kandidaten bei Schwelle {args.min_score:.2f}: {eligible}")

    if args.apply:
        applied = apply_proposals(records, proposals, args.min_score)
        write_shard(records, expected_sample_ids)
        print(f"Übernommen: {applied}; alle übernommenen Annotationen bleiben Silver/offen.")
    else:
        print("Nur Bericht erstellt; Quell-Shard und Katalog wurden nicht geändert. Für Übernahme erneut mit --apply ausführen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
