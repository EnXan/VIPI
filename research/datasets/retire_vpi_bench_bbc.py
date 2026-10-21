#!/usr/bin/env python3
"""Remove BBC captures from the active VPI-Bench OCR set, retaining a rollback copy."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "research/datasets/data/external/VPI-Bench/capture_plan.json"
SHARD = ROOT / "research/datasets/data/catalog/sources/vpi_bench.jsonl"
SCREENSHOTS = ROOT / "research/datasets/data/external/VPI-Bench/screenshots"
ARCHIVE = ROOT / "research/datasets/data/.cache/vpi_bench_bbc_removed"
AUDIT = ROOT / "research/datasets/data/catalog/reports/vpi_bench_capture_audit.json"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    records = read_jsonl(SHARD)
    bbc_items = [item for item in plan if item.get("platform") == "bbc"]
    bbc_records = [record for record in records if record.get("source_specific", {}).get("platform") == "bbc"]
    planned_screenshots = {str(item["screenshot"]) for item in plan}
    referenced_screenshots = {str(record["asset"]["path"]) for record in records}
    orphan_bbc_paths = [
        path for path in SCREENSHOTS.glob("bbc_*.jpg")
        if path.relative_to(ROOT).as_posix() not in planned_screenshots
        and path.relative_to(ROOT).as_posix() not in referenced_screenshots
    ]
    if not bbc_items and not bbc_records and not orphan_bbc_paths:
        print("BBC is already absent from the active VPI-Bench capture plan and source shard.")
        return 0
    if len(bbc_items) not in {0, 79} or len(bbc_records) != len(bbc_items):
        raise ValueError(f"Unexpected BBC counts: {len(bbc_items)} planned, {len(bbc_records)} in source shard")

    paths = [ROOT / str(item["screenshot"]) for item in bbc_items] + orphan_bbc_paths
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate BBC screenshot paths in capture plan")
    for path in paths:
        if path.parent != SCREENSHOTS or not path.name.startswith("bbc_") or path.suffix.lower() != ".jpg":
            raise ValueError(f"Refusing unexpected screenshot path: {path}")
        if not path.is_file():
            raise FileNotFoundError(path)
        if (ARCHIVE / "screenshots" / path.name).exists():
            raise FileExistsError(ARCHIVE / "screenshots" / path.name)

    bbc_paths = {str(record["asset"]["path"]) for record in bbc_records}
    planned_paths = {str(item["screenshot"]) for item in bbc_items}
    if bbc_paths != planned_paths:
        raise ValueError("BBC screenshot references differ between plan and source shard")

    ARCHIVE.mkdir(parents=True, exist_ok=True)
    (ARCHIVE / "screenshots").mkdir(parents=True, exist_ok=True)
    if not (ARCHIVE / "capture_plan.before.json").exists():
        shutil.copy2(PLAN, ARCHIVE / "capture_plan.before.json")
    if not (ARCHIVE / "vpi_bench.before.jsonl").exists():
        shutil.copy2(SHARD, ARCHIVE / "vpi_bench.before.jsonl")

    for path in paths:
        path.replace(ARCHIVE / "screenshots" / path.name)

    active_plan = [item for item in plan if item.get("platform") != "bbc"]
    active_records = [record for record in records if record.get("source_specific", {}).get("platform") != "bbc"]
    atomic_write(PLAN, json.dumps(active_plan, ensure_ascii=False, indent=2) + "\n")
    atomic_write(
        SHARD,
        "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in active_records),
    )

    result = subprocess.run(
        [sys.executable, str(ROOT / "research/datasets/import_vpi_bench.py"), "--validate-only"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    atomic_write(AUDIT, result.stdout.rstrip() + "\n")
    print(f"Archived {len(paths)} BBC screenshots (including any orphan pilot capture) under {ARCHIVE / 'screenshots'}")
    print(f"Active VPI-Bench plan/source records: {len(active_plan)} / {len(active_records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
