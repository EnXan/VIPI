#!/usr/bin/env python3
"""Download a dataset repository from the Hugging Face Hub."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "research/datasets/data/.cache/huggingface"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a Hugging Face dataset repository to a local directory."
    )
    parser.add_argument(
        "dataset_id",
        help="Dataset ID on Hugging Face, for example 'ylecun/mnist'.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Destination directory. Defaults to "
            "research/datasets/data/external/<dataset-owner>/<dataset-name>."
        ),
    )
    parser.add_argument(
        "--revision",
        default="main",
        help="Branch, tag, or commit to download (default: main).",
    )
    parser.add_argument(
        "--include",
        action="append",
        dest="allow_patterns",
        metavar="PATTERN",
        help="Only download matching files. May be specified more than once.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        dest="ignore_patterns",
        metavar="PATTERN",
        help="Skip matching files. May be specified more than once.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Download files again even if they are already cached.",
    )
    return parser.parse_args(argv)


def default_output_dir(dataset_id: str) -> Path:
    parts = dataset_id.strip("/").split("/")
    if len(parts) != 2 or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Dataset ID must have the form '<owner>/<dataset-name>'.")
    return (
        PROJECT_ROOT
        / "research"
        / "datasets"
        / "data"
        / "external"
        / parts[0]
        / parts[1]
    )


def download_dataset(args: argparse.Namespace) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'huggingface_hub'. Install it with: "
            "uv sync --extra research"
        ) from exc

    output_dir = (args.output_dir or default_output_dir(args.dataset_id)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    downloaded_path = snapshot_download(
        repo_id=args.dataset_id,
        repo_type="dataset",
        revision=args.revision,
        cache_dir=CACHE_DIR,
        local_dir=output_dir,
        allow_patterns=args.allow_patterns,
        ignore_patterns=args.ignore_patterns,
        force_download=args.force_download,
        token=os.environ.get("HF_TOKEN"),
    )
    return Path(downloaded_path)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        downloaded_path = download_dataset(args)
    except Exception as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    print(f"Dataset downloaded to: {downloaded_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
