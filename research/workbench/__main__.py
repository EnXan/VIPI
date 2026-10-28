import argparse
import json
import sys
from pathlib import Path

from vipi.config import WORKBENCH_OCR_MODELS
from vipi.ocr.models import (
    DEFAULT_MODEL,
    prepare_models,
)
from .model_registry import (
    MODEL_NAMES as PUBLIC_MODEL_NAMES,
    validate_model,
    LIGHTON_MODELS,
)
from research.ocr_eval.evaluation.runner import extract, reassemble
from research.ocr_eval.evaluation.profiles import DEFAULT_PROFILE, PROFILES
from vipi.ocr.workers import DEFAULT_WORKERS, worker_count
from vipi.ocr.runtime import BACKENDS, DEFAULT_BACKEND


def parse_workers(value):
    try:
        return worker_count(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description="VIPI local image-to-text pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser(
        "prepare-models", help="Prepare OCR model files explicitly"
    )
    prepare.add_argument("--model", choices=PUBLIC_MODEL_NAMES)
    prepare.add_argument("--models-dir", type=Path, default=Path("models/ocr"))
    check = subparsers.add_parser(
        "check-models", help="Round 0: one image per selected OCR model"
    )
    check.add_argument("--model", action="append", choices=PUBLIC_MODEL_NAMES)
    check.add_argument("--image", type=Path)
    check.add_argument("--models-dir", type=Path, default=Path("models/ocr"))
    check.add_argument(
        "--reports-dir", type=Path, default=Path("runs/reports/ocr-round0")
    )
    scan = subparsers.add_parser(
        "extract", help="Run OCR on the original image or with transformations"
    )
    scan.add_argument("image", type=Path)
    scan.add_argument("--model", choices=PUBLIC_MODEL_NAMES, default=DEFAULT_MODEL)
    scan.add_argument("--ocr-profile", choices=PROFILES, default=DEFAULT_PROFILE)
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
    from .detector_options import add_options

    add_options(scan)
    scan.add_argument(
        "--evaluate",
        action="store_true",
        help="Check the image against its active dataset reference",
    )
    scan.add_argument(
        "--workers",
        type=parse_workers,
        default=DEFAULT_WORKERS,
        help="Transformation workers, 1–8 (default: 4); baseline uses one worker",
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
    serve.add_argument(
        "--detector-models-dir",
        type=Path,
        default=Path("models/detector/prompt-guard-2-86m"),
    )
    args = parser.parse_args(argv)
    try:
        detection_options = None
        if args.command == "extract" and (
            args.text_classifier
            or args.image_check != "off"
            or args.context_check != "off"
        ):
            from .detector_options import read_options

            detection_options = read_options(args)
        if args.command == "prepare-models":
            if args.model in LIGHTON_MODELS:
                from huggingface_hub import snapshot_download

                label = args.model.removeprefix("lightonocr-3-").upper()
                snapshot_download(
                    f"lightonai/LightOnOCR-3-{label}",
                    local_dir=args.models_dir / "candidates" / args.model,
                )
            elif args.model in {"google-cloud-vision", "gpt-6-luna"}:
                validate_model(args.model, args.models_dir)
                print("API credentials configured; no model download required.")
            elif args.model in WORKBENCH_OCR_MODELS:
                from .ocr_models import prepare_model

                print(
                    f"Preparing {PUBLIC_MODEL_NAMES[args.model]} "
                    "with its official pipeline"
                )
                prepare_model(args.model, args.models_dir)
                marker = args.models_dir / args.model / "READY"
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("Prepared through the official upstream pipeline.\n")
                print(f"Ready: {PUBLIC_MODEL_NAMES[args.model]}")
            else:
                prepare_models(args.models_dir, args.model)
        elif args.command == "check-models":
            from .round0 import run

            return run(args.model, args.image, args.models_dir, args.reports_dir)
        elif args.command == "serve":
            from .web import create_app

            create_app(
                args.runs_dir,
                args.models_dir,
                detector_models_dir=args.detector_models_dir,
            ).run(
                host="127.0.0.1",
                port=args.port,
                threaded=True,
                use_reloader=False,
                load_dotenv=False,
            )
        else:
            if args.command == "extract" and (
                args.model in WORKBENCH_OCR_MODELS or args.model in LIGHTON_MODELS
            ):
                validate_model(args.model, args.models_dir)
            reference = None
            if args.command == "extract" and args.evaluate:
                from research.ocr_eval.evaluation.catalog import Catalog

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
                    ocr_profile=args.ocr_profile,
                    models_dir=args.models_dir,
                    runs_dir=args.runs_dir,
                    workers=(
                        1
                        if args.model in WORKBENCH_OCR_MODELS
                        or args.ocr_profile == "baseline"
                        else args.workers
                    ),
                    reference=reference,
                    backend=args.backend,
                )
            )
            if detection_options:
                from .detector_options import (
                    progress as detection_progress,
                    output_summary,
                )
                from vipi.detection.pipeline import detect_saved_run as detect

                result["detection"] = detect(
                    args.runs_dir / result["run_id"],
                    options=detection_options,
                    model_dir=args.detector_models_dir,
                    on_event=detection_progress,
                )
                print(output_summary(result["detection"]), file=sys.stderr)
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
                    f"Reference words in final text: "
                    f"{evaluation['final']['coverage']:.0%} "
                    f"({'complete' if evaluation['valid'] else 'incomplete'}); "
                    f"exact words: {evaluation['final']['exact']['coverage']:.0%}",
                    file=sys.stderr,
                )
        if detection_options and (
            any(x["status"] != "completed" for x in result["detection"]["answers"])
            or (
                result["detection"]["missing_text_evidence"]
                and detection_options["text_classifier"] != "off"
            )
        ):
            return 2
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f"OCR failed: {error or 'interrupted'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
