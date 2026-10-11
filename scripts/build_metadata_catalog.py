#!/usr/bin/env python3
"""Combine normalized per-source JSONL shards into the shared metadata catalog."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
import sys
from typing import Iterator, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent / "datasets"))
from typography_metadata import standardize_record


REQUIRED_FIELDS = {
    "schema_version",
    "sample_id",
    "asset",
    "source",
    "group",
    "visual",
    "ocr",
    "security",
    "eligibility",
    "rights",
    "source_specific",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources-dir",
        type=Path,
        default=project_root / "datasets/catalog/sources",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "datasets/catalog/metadata.jsonl",
    )
    return parser.parse_args(argv)


def read_records(sources_dir: Path) -> Iterator[dict[str, object]]:
    source_files = sorted(sources_dir.glob("*.jsonl"))
    if not source_files:
        raise ValueError(f"No source JSONL files found in {sources_dir}")
    for source_file in source_files:
        with source_file.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON in {source_file}:{line_number}: {exc}"
                    ) from exc
                missing = REQUIRED_FIELDS - record.keys()
                if missing:
                    raise ValueError(
                        f"Record in {source_file}:{line_number} is missing {sorted(missing)}"
                    )
                yield standardize_record(record)


def write_atomic(records: Iterator[dict[str, object]], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    seen_ids: set[str] = set()
    count = 0
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for record in records:
                sample_id = str(record["sample_id"])
                if sample_id in seen_ids:
                    raise ValueError(f"Duplicate sample_id across source shards: {sample_id}")
                seen_ids.add(sample_id)
                json.dump(record, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                count += 1
        Path(temporary_name).replace(output)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return count


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    count = write_atomic(read_records(args.sources_dir.resolve()), args.output.resolve())
    print(f"Wrote {count} records to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
