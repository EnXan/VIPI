"""Command line for the combined catalog draft: validate, summarize, generate."""

import argparse
import json
from pathlib import Path
import sys

from research.ocr_eval.benchmark import ROOT

from . import generate, schema
from .store import CATALOG_NAME, DEFAULT_DIRECTORY, VOCABULARY_NAME, write_json


def load(directory):
    directory = Path(directory)
    return (
        json.loads((directory / CATALOG_NAME).read_text(encoding="utf-8")),
        json.loads((directory / VOCABULARY_NAME).read_text(encoding="utf-8")),
    )


def add_generated(args, catalog, vocabulary):
    try:
        entries = generate.build(
            args.spec, args.images_root, {entry["id"] for entry in catalog}, catalog
        )
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    ids = {entry["id"] for entry in catalog} | {entry["id"] for entry in entries}
    problems = [
        f"{entry['id']}: {message}"
        for entry in entries
        for message in schema.entry_errors(entry, vocabulary, ids)
    ]
    if problems:
        print("\n".join(f"error: {line}" for line in problems), file=sys.stderr)
        return 1
    write_json(Path(args.dir) / CATALOG_NAME, [*catalog, *entries])
    print(f"added {len(entries)} entries ({len(catalog) + len(entries)} in total)")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m research.curation",
        description="Check and extend the combined evaluation catalog draft.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate", "Check the draft against its vocabulary."),
        ("summary", "Count kept images per value, label and text template."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--dir", type=Path, default=DEFAULT_DIRECTORY)
    generated = commands.add_parser(
        "generate", help="Render a generated-image spec and add its entries."
    )
    generated.add_argument(
        "spec",
        type=Path,
        help="Spec JSON, e.g. research/curation/generated/benign_text.json",
    )
    generated.add_argument("--dir", type=Path, default=DEFAULT_DIRECTORY)
    generated.add_argument("--images-root", type=Path, default=ROOT / "research")
    commands.choices["summary"].add_argument(
        "--table",
        action="store_true",
        help="Print the label balance per content as a table instead of JSON",
    )
    commands.choices["validate"].add_argument(
        "--images-root",
        type=Path,
        default=ROOT / "research",
        help="Directory holding ocr_eval/ and detection_eval/ images",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        catalog, vocabulary = load(args.dir)
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.command == "generate":
        return add_generated(args, catalog, vocabulary)
    if args.command == "validate":
        errors, warnings = schema.validate(catalog, vocabulary, args.images_root)
        for line in errors:
            print(f"error: {line}")
        print(f"{len(errors)} errors, {len(warnings)} warnings")
        for message, count in schema.warning_counts(warnings).items():
            print(f"warning: {count}x {message}")
        return 1 if errors else 0
    data = schema.summary(catalog, vocabulary)
    print(schema.balance_table(data) if args.table else json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
