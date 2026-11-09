"""Command line for the dataset: validate, summarize, generate, add, submit."""

import argparse
import json
from pathlib import Path
import sys

from . import contribute, generate, schema
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
        description="Check and extend the evaluation dataset in research/dataset/.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate", "Check the dataset against its vocabulary and images."),
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
    generated.add_argument(
        "--images-root", type=Path, help="Image folder root; default: --dir"
    )
    commands.choices["summary"].add_argument(
        "--table",
        action="store_true",
        help="Print the label balance per content as a table instead of JSON",
    )
    commands.choices["validate"].add_argument(
        "--images-root", type=Path, help="Image folder root; default: --dir"
    )
    add = commands.add_parser(
        "add",
        help="Add your own images as unreviewed entries.",
        description="Copy images into research/dataset/images/ and add one "
        "unreviewed entry each. Label, transcribe and review them on the "
        "workbench Label page afterwards.",
    )
    add.add_argument("images", nargs="+", type=Path, help="PNG, JPEG or WEBP files")
    add.add_argument("--label", required=True, help="benign, injection or jailbreak")
    add.add_argument("--content", required=True, help="Content type, e.g. web_page")
    add.add_argument(
        "--source",
        required=True,
        help="Short name of where the images come from, e.g. my_screenshots",
    )
    add.add_argument(
        "--license", required=True, help="License of the images, e.g. CC-BY-4.0"
    )
    add.add_argument(
        "--provenance",
        required=True,
        help="How the images were made or where they were found",
    )
    add.add_argument("--repository", help="URL of the source, if any")
    add.add_argument("--dir", type=Path, default=DEFAULT_DIRECTORY)
    changed = commands.add_parser(
        "changes", help="List your changes since the downloaded revision."
    )
    changed.add_argument("--dir", type=Path, default=DEFAULT_DIRECTORY)
    upload = commands.add_parser(
        "upload",
        help="Open a dataset pull request with only your changes.",
        description="Applies your changes since the downloaded revision to the "
        "current main of the dataset and opens a pull request. Log in first "
        "with: uv run hf auth login",
    )
    upload.add_argument("--message", default="Add evaluation images")
    upload.add_argument("--dry-run", action="store_true")
    upload.add_argument("--dir", type=Path, default=DEFAULT_DIRECTORY)
    return parser


def add_images(args):
    added, skipped = contribute.add_images(
        args.images,
        args.dir,
        label=args.label,
        content=args.content,
        source={
            "dataset": args.source,
            "license": args.license,
            "provenance": args.provenance,
            "repository": args.repository,
        },
    )
    for path, identifier in skipped:
        print(f"skipped {path}: already in the dataset as {identifier}")
    print(f"added {len(added)} entries; label them on the workbench Label page")
    return 0


def show_changes(args, catalog):
    _, revision = contribute.pinned_dataset()
    found = contribute.changes(catalog, contribute.remote_files(revision)[0])
    for name, keys in found.items():
        print(f"{name}: {len(keys)}" + (f" ({', '.join(keys)})" if keys else ""))
    return 0


def upload_changes(args):
    data = contribute.upload(args.dir, args.message, dry_run=args.dry_run)
    counts = ", ".join(f"{len(keys)} {name}" for name, keys in data["changes"].items())
    print(f"your changes: {counts}; dataset main is {data['main_revision'][:8]}")
    for line in data["conflicts"]:
        print(f"conflict: {line}")
    if data["conflicts"]:
        return 1
    if args.dry_run:
        print("dry run: nothing uploaded")
    else:
        print(f"opened {data['pull_request']}")
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        catalog, vocabulary = load(args.dir)
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    args.images_root = getattr(args, "images_root", None) or args.dir
    try:
        if args.command == "add":
            return add_images(args)
        if args.command == "changes":
            return show_changes(args, catalog)
        if args.command == "upload":
            return upload_changes(args)
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
