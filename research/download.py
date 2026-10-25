"""Download a pinned evaluation dataset into the local research workspace."""

import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "suite", choices=("all", "detection_eval", "ocr_eval"), nargs="?", default="all"
    )
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    dataset = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
    patterns = {
        "detection_eval": ["detection_eval/cases.json", "detection_eval/images/*"],
        "ocr_eval": ["ocr_eval/catalog.json", "ocr_eval/images/*"],
    }
    selected = patterns if args.suite == "all" else {args.suite: patterns[args.suite]}
    snapshot_download(
        repo_id=dataset["repo_id"],
        repo_type="dataset",
        revision=dataset["revision"],
        allow_patterns=[
            pattern for entries in selected.values() for pattern in entries
        ],
        local_dir=root,
        token=False,
    )
    print(f"Downloaded {', '.join(selected)} at {dataset['revision']} into {root}.")


if __name__ == "__main__":
    main()
