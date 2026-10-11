import argparse
import json
import sys
from pathlib import Path

from .models import DEFAULT_MODEL, MODEL_NAMES, prepare_models
from .pipeline import extract, reassemble
from .workers import DEFAULT_WORKERS, worker_count
from .runtime import BACKENDS, DEFAULT_BACKEND


def parse_workers(value):
    try:
        return worker_count(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description="VIPI local image-to-text pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser(
        "prepare-models", help="Download pinned OCR models explicitly"
    )
    prepare.add_argument("--model", choices=MODEL_NAMES)
    prepare.add_argument("--models-dir", type=Path, default=Path("models/ocr"))
    scan = subparsers.add_parser(
        "extract", help="Run all fixed transformations and OCR"
    )
    scan.add_argument("image", type=Path)
    scan.add_argument("--model", choices=MODEL_NAMES, default=DEFAULT_MODEL)
    scan.add_argument(
        "--backend",
        choices=BACKENDS,
        default=DEFAULT_BACKEND,
        help="CPU (default), Apple CoreML or NVIDIA CUDA",
    )
    scan.add_argument("--models-dir", type=Path, default=Path("models/ocr"))
    scan.add_argument("--runs-dir", type=Path, default=Path("runs"))
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--output", type=Path)
    scan.add_argument(
        "--evaluate",
        action="store_true",
        help="Check the image against its active dataset reference",
    )
    scan.add_argument(
        "--workers",
        type=parse_workers,
        default=DEFAULT_WORKERS,
        help="Parallel OCR workers, 1–8 (default: 4)",
    )
    merge = subparsers.add_parser(
        "reassemble", help="Reassemble saved OCR results without rerunning OCR"
    )
    merge.add_argument("run_id")
    merge.add_argument("--runs-dir", type=Path, default=Path("runs"))
    merge.add_argument("--json", action="store_true")
    merge.add_argument("--output", type=Path)
    serve = subparsers.add_parser("serve", help="Open the local live OCR interface")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--models-dir", type=Path, default=Path("models/ocr"))
    serve.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-models":
            prepare_models(args.models_dir, args.model)
        elif args.command == "serve":
            from .web import create_app

            create_app(args.runs_dir, args.models_dir).run(
                host="127.0.0.1", port=args.port, threaded=True, use_reloader=False
            )
        else:
            reference = None
            if args.command == "extract" and args.evaluate:
                from .catalog import Catalog

                reference = Catalog(Path.cwd()).for_path(args.image)

            def progress(event):
                if event["type"] == "step_completed":
                    print(
                        f"[{event['completed']}] {event['step']['label']}",
                        file=sys.stderr,
                    )
                elif event["type"] == "run_failed":
                    print(
                        f"Saved partial run: {args.runs_dir / event['run_id']}",
                        file=sys.stderr,
                    )

            result = (
                reassemble(args.run_id, runs_dir=args.runs_dir)
                if args.command == "reassemble"
                else extract(
                    args.image,
                    args.model,
                    progress,
                    models_dir=args.models_dir,
                    runs_dir=args.runs_dir,
                    workers=args.workers,
                    reference=reference,
                    backend=args.backend,
                )
            )
            output = (
                json.dumps(result, ensure_ascii=False, indent=2)
                if args.json
                else result["text"]
            )
            if args.output:
                args.output.write_text(output, encoding="utf-8")
            print(output)
            if result.get("evaluation"):
                evaluation = result["evaluation"]
                print(
                    f"Reference: {'valid' if evaluation['valid'] else 'incomplete'} "
                    f"({evaluation['detection']['coverage']:.0%}); "
                    f"final text: {'valid' if evaluation['final']['valid'] else 'incomplete'}",
                    file=sys.stderr,
                )
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f"OCR failed: {error or 'interrupted'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
