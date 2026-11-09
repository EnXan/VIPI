"""Command line for contribution evaluation splits and baseline freshness."""

import argparse
import json
from pathlib import Path
import sys

from . import compare, runs, splits, suite


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m research.contrib_eval",
        description="Frozen evaluation splits and baseline freshness checks.",
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
    for command, description in (
        ("manifest", "Print the suite/configuration identity of a path."),
        ("status", "Report whether the latest committed baseline is fresh."),
    ):
        sub = commands.add_parser(command, help=description)
        sub.add_argument("path", choices=sorted(suite.PATHS))
        sub.add_argument("--split", choices=suite.SPLIT_NAMES, default="development")
    run = commands.add_parser(
        "run",
        help="Run or resume a scoped baseline/candidate evaluation.",
        description="Runs live inference and may incur provider charges. Use "
        "--dry-run to check the request first.",
    )
    run.add_argument("path", choices=sorted(suite.PATHS))
    run.add_argument("--role", choices=runs.ROLES, required=True)
    run.add_argument("--split", choices=suite.SPLIT_NAMES, default="development")
    run.add_argument("--against", help="Baseline run ID or summary path (candidate)")
    run.add_argument(
        "--allow-mismatch",
        metavar="REASON",
        help="Record a non-matched candidate run instead of refusing it",
    )
    run.add_argument(
        "--confirm-test-split",
        action="store_true",
        help="Required for the one-time confirmation run on the test split",
    )
    run.add_argument("--run-id", help="Resume this run ID; default: a new ID")
    run.add_argument("--runs-dir", type=Path, default=runs.DEFAULT_RUNS_DIRECTORY)
    run.add_argument("--dry-run", action="store_true")
    comparison = commands.add_parser(
        "compare",
        help="Compare a candidate run with its baseline and write the report.",
    )
    comparison.add_argument("baseline", help="Baseline run ID")
    comparison.add_argument("candidate", help="Candidate run ID")
    return parser


def run_command(args):
    result = runs.run(
        args.path,
        args.role,
        args.split,
        runs_directory=args.runs_dir,
        run_id=args.run_id,
        against=args.against,
        mismatch_reason=args.allow_mismatch,
        confirm_test=args.confirm_test_split,
        dry_run=args.dry_run,
    )
    print(
        f"{result['state']}: {result['role']} {result['path']} "
        f"({result['split']}, {result['entries']} entries) run {result['run_id']}"
    )
    print(f"local artifacts {result['directory']}")
    comparison = result.get("comparison")
    if comparison:
        state = "matched" if comparison["matched"] else "NOT matched"
        print(f"against baseline {comparison['baseline_run_id']}: {state}")
        for field in comparison["differences"]:
            print(f"differs: {field}")
    if result["state"] == "incomplete":
        print(f"resume with --run-id {result['run_id']}")
    if result["state"] == "complete":
        print(f"summary {result['summary']} (commit this file)")
    return 0 if result["state"] in {"planned", "complete"} else 1


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return dispatch(args)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def dispatch(args):
    if args.command == "run":
        return run_command(args)
    if args.command == "compare":
        data = compare.compare(args.baseline, args.candidate)
        json_path, markdown_path = compare.write(data)
        counts = data["case_counts"]
        print("matched inputs" if data["matched"] else "NOT matched inputs")
        print(
            f"newly failed {counts['newly_failed']}, recovered {counts['recovered']}, "
            f"regressed {counts['regressed']}, improved {counts['improved']}"
        )
        print(f"wrote {markdown_path.relative_to(splits.ROOT)}")
        print(f"wrote {json_path.relative_to(splits.ROOT)}")
        return 0
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
