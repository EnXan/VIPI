"""Standalone detector CLI; has no OCR/runtime dependency."""

import argparse
import json
import sys
from pathlib import Path

from .detector_options import (
    add_options,
    output_summary,
    progress,
    read_options,
)
from vipi.detection.evidence import run_directory
from vipi.detection.pipeline import detect_saved_run as detect
from vipi.detection.providers.prompt_guard import MODEL_DIR, prepare_model


def main(argv=None):
    parser = argparse.ArgumentParser(description="VIPI prompt-injection detector")
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("detect", help="Inspect a saved OCR run")
    scan.add_argument("run_id")
    scan.add_argument("--runs-dir", type=Path, default=Path("runs"))
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--output", type=Path)
    add_options(scan)
    prepare = commands.add_parser(
        "prepare-detector",
        help="Explicitly download Prompt Guard weights using authorized Hugging Face access",
    )
    prepare.add_argument("--revision", required=True)
    prepare.add_argument("--detector-models-dir", type=Path, default=Path(MODEL_DIR))
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-detector":
            manifest = prepare_model(args.detector_models_dir, revision=args.revision)
            print(f"Ready: {manifest['model']} @ {manifest['revision']}")
            return 0
        result = detect(
            run_directory(args.runs_dir, args.run_id),
            options=read_options(args),
            model_dir=args.detector_models_dir,
            on_event=progress,
        )
        output = (
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else output_summary(result)
        )
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        print(output)
        # Report-only: suspicious/unclear content does not change the exit code.
        return (
            2
            if any(x["status"] != "completed" for x in result["answers"])
            or (result["missing_text_evidence"] and args.text_classifier)
            else 0
        )
    except (Exception, KeyboardInterrupt) as error:
        print(f"Detection failed: {error or 'interrupted'}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
