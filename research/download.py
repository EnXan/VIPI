"""Download the pinned evaluation dataset into research/dataset/."""

import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download

PATTERNS = ["catalog.json", "vocabulary.json", "images/*"]


def build_parser():
    """Build the CLI contract without starting inference or model downloads."""
    return argparse.ArgumentParser(description=__doc__)


def main(argv=None):
    build_parser().parse_args(argv)
    root = Path(__file__).resolve().parent
    dataset = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
    target = root / "dataset"
    snapshot_download(
        repo_id=dataset["repo_id"],
        repo_type="dataset",
        revision=dataset["revision"],
        allow_patterns=PATTERNS,
        local_dir=target,
        token=False,
    )
    print(f"Downloaded the evaluation dataset at {dataset['revision']} into {target}.")


if __name__ == "__main__":
    main()
