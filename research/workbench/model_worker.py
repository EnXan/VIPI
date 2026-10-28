"""Private JSON-line worker; model logs go to stderr, OCR output to a local file."""

import argparse
import contextlib
import json
import sys
import time
import traceback

from PIL import Image

PREFIX = "VIPI_OCR_RESULT "


def emit(value):
    sys.__stdout__.write(PREFIX + json.dumps(value) + "\n")
    sys.__stdout__.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--models-dir", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--threads", type=int, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from .model_registry import create_direct_engine
            from pathlib import Path

            engine = create_direct_engine(
                args.model,
                Path(args.models_dir),
                profile=args.profile,
                backend=args.backend,
                threads=args.threads,
            )
        emit({"ready": True, "initialization_seconds": time.perf_counter() - started})
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        emit({"error": str(error)})
        return 1
    for line in sys.stdin:
        try:
            request = json.loads(line)
            started = time.perf_counter()
            with contextlib.redirect_stdout(sys.stderr):
                with Image.open(request["image"]) as image:
                    result = engine.recognize(image.convert("RGB"))
                Path(request["output"]).write_text(
                    json.dumps(result, ensure_ascii=False), encoding="utf-8"
                )
            emit(
                {"completed": True, "inference_seconds": time.perf_counter() - started}
            )
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            emit({"error": str(error)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
