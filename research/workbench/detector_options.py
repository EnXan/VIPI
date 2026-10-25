"""Shared detector arguments for standalone checks and extract-then-detect."""

import json
from pathlib import Path

from vipi.detection.pipeline import TEXT_CLASSIFIERS, settings
from vipi.detection.providers.prompt_guard import MODEL_DIR


def add_options(parser):
    parser.add_argument(
        "--text-classifier",
        choices=TEXT_CLASSIFIERS[:3],
        action="append",
        default=None,
        metavar="MODEL",
        help="Text classifier; repeat for multiple models, omit for none",
    )
    parser.add_argument("--image-check", choices=("off", "openai"), default="off")
    parser.add_argument("--context-check", choices=("off", "openai"), default="off")
    parser.add_argument("--context-file", type=Path)
    parser.add_argument("--thresholds-file", type=Path)
    parser.add_argument("--detector-models-dir", type=Path, default=Path(MODEL_DIR))
    parser.add_argument(
        "--no-reuse",
        action="store_true",
        help="Make fresh checks instead of replaying matching successful answers",
    )


def read_options(args):
    return settings(
        text_classifier="off",
        text_classifiers=args.text_classifier or [],
        image_check=args.image_check,
        context_check=args.context_check,
        context=json.loads(args.context_file.read_text())
        if args.context_file
        else None,
        thresholds=json.loads(args.thresholds_file.read_text())
        if args.thresholds_file
        else None,
        reuse=not args.no_reuse,
    )


def progress(event):
    import sys

    if event["type"] == "check_completed":
        answer = event["answer"]
        score = answer.get("probability")
        print(
            f"[{event['completed']}/{event['total']}] {answer['signal']} · {answer['status']} · {score if score is not None else answer.get('error', 'no score')}",
            file=sys.stderr,
        )


def output_summary(result):
    lines = [f"{result['verdict']} · review_required={result['review_required']}"]
    for signal, value in result["signals"].items():
        lines.append(
            f"{signal}: max_score={value['max_score']} · {value['verdict']} · {value['checks']} checks"
        )
    lines.append(
        f"Saved: {result['run_id']}/detection/{result['check_id']}/result.json"
    )
    return "\n".join(lines)
