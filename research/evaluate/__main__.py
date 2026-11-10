"""Command line: frozen split, evaluation runs and the saved baseline."""

import argparse
from pathlib import Path
import sys

from . import runs, splits, suite


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m research.evaluate",
        description="Evaluate a product scan configuration on the frozen split "
        "and compare it with the saved baseline.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    split = commands.add_parser(
        "split", help="Write research/splits.json from the dataset."
    )
    split.add_argument(
        "--check",
        action="store_true",
        help="Only verify that the committed split matches the dataset.",
    )
    status = commands.add_parser(
        "status", help="Report whether the saved baseline matches this checkout."
    )
    status.add_argument("configuration", choices=suite.CONFIGURATIONS)
    status.add_argument("--split", choices=suite.SPLIT_NAMES, default="development")
    run = commands.add_parser(
        "run",
        help="Run or resume an evaluation and compare it with the saved baseline.",
        description="Runs live inference; cloud configurations incur provider "
        "charges. Use --dry-run to check the request first.",
    )
    run.add_argument("configuration", choices=suite.CONFIGURATIONS)
    run.add_argument("--split", choices=suite.SPLIT_NAMES, default="development")
    run.add_argument(
        "--confirm-test-split",
        action="store_true",
        help="Required for the one-time confirmation run on the test split",
    )
    run.add_argument("--run-id", help="Resume this run ID; default: a new ID")
    run.add_argument("--runs-dir", type=Path, default=runs.DEFAULT_RUNS_DIRECTORY)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument(
        "--no-reuse-ocr",
        dest="reuse_ocr",
        action="store_false",
        help="Scan every image from scratch instead of reusing earlier OCR "
        "results with the same OCR settings, OCR sources and image",
    )
    save = commands.add_parser(
        "save-baseline",
        help="Save a complete run as the baseline (research/baselines/).",
    )
    save.add_argument("run_id")
    save.add_argument("--runs-dir", type=Path, default=runs.DEFAULT_RUNS_DIRECTORY)
    return parser


def run_command(args):
    result = runs.run(
        args.configuration,
        args.split,
        runs_directory=args.runs_dir,
        run_id=args.run_id,
        confirm_test=args.confirm_test_split,
        dry_run=args.dry_run,
        reuse_ocr=args.reuse_ocr,
    )
    print(
        f"{result['state']}: {result['configuration']} "
        f"({result['split']}, {result['entries']} entries) run {result['run_id']}"
    )
    print(f"local artifacts {result['directory']}")
    if "reusable_ocr" in result:
        print(
            f"reusable OCR results: {result['reusable_ocr']} of {result['entries']}"
            + ("" if result["reuse_ocr"] else " (not used: --no-reuse-ocr)")
        )
    print(f"baseline {result['baseline'] or 'none saved'}")
    comparison = result.get("comparison")
    if comparison:
        print("same inputs" if comparison["matched"] else "NOT the same inputs")
        for field in comparison["differences"]:
            print(f"differs: {field}")
        print(f"comparison {result['directory']}/comparison.md")
    if result["state"] == "incomplete":
        print(f"resume with --run-id {result['run_id']}")
    if result["state"] == "complete":
        print(f"report {result['directory']}/report.md")
        print(f"save as baseline: save-baseline {result['run_id']}")
    return 0 if result["state"] in {"planned", "complete"} else 1


def dispatch(args):
    if args.command == "run":
        return run_command(args)
    if args.command == "save-baseline":
        target = runs.save_baseline(args.run_id, runs_directory=args.runs_dir)
        print(f"wrote {target.relative_to(splits.ROOT)} (commit this file)")
        return 0
    if args.command == "split":
        if args.check:
            matches = splits.check()
            print("split is current" if matches else "split is out of date")
            return 0 if matches else 1
        print(f"wrote {splits.write().relative_to(splits.ROOT)}")
        return 0
    result = suite.status(args.configuration, args.split)
    print(f"{result['configuration']} ({result['split']}): {result['state']}")
    if "baseline" in result:
        baseline = result["baseline"]
        print(f"baseline {baseline['run_id']} from {baseline['completed_at']}")
        print(f"summary {baseline['summary']}")
    for field in result.get("differences", []):
        print(f"changed: {field}")
    if result["state"] == "none":
        print("no saved baseline; run one and save it before changing code")
    return 0 if result["state"] == "fresh" else 1


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return dispatch(args)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
