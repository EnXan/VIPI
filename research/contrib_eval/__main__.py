"""Command line for contribution evaluation splits and baseline freshness."""

import argparse
import json
import sys

from . import splits, suite


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m research.contrib_eval",
        description="Frozen evaluation splits and baseline freshness checks.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    split = commands.add_parser(
        "split", help="Write research/splits.json from the pinned catalogs."
    )
    split.add_argument(
        "--check",
        action="store_true",
        help="Only verify that the committed split matches the catalogs.",
    )
    for command, description in (
        ("manifest", "Print the suite/configuration identity of a path."),
        ("status", "Report whether the latest committed baseline is fresh."),
    ):
        sub = commands.add_parser(command, help=description)
        sub.add_argument("path", choices=sorted(suite.PATHS))
        sub.add_argument("--split", choices=suite.SPLIT_NAMES, default="development")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "split":
        if args.check:
            matches = splits.check()
            print("split is current" if matches else "split is out of date")
            return 0 if matches else 1
        print(f"wrote {splits.write().relative_to(splits.ROOT)}")
        return 0
    if args.command == "manifest":
        print(json.dumps(suite.manifest(args.path, args.split), indent=2))
        return 0
    result = suite.status(args.path, args.split)
    print(f"{result['path']} ({result['split']}): {result['state']}")
    if "baseline" in result:
        baseline = result["baseline"]
        print(f"baseline {baseline['run_id']} from {baseline['completed_at']}")
        print(f"summary {baseline['summary']}")
    for field in result.get("differences", []):
        print(f"changed: {field}")
    if result["state"] == "none":
        print("no committed baseline; run a baseline before changing code")
    return 0 if result["state"] == "fresh" else 1


if __name__ == "__main__":
    sys.exit(main())
