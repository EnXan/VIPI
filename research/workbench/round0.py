"""One common image per active model; no dataset or detector benchmark."""

from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from PIL import Image, ImageDraw, ImageFont

from research.ocr_eval.evaluation.runner import extract
from vipi.ocr.transforms import decode_image
from vipi.storage.files import write_json, sha256
from .model_registry import MODEL_NAMES, model_options, readiness_path


def run(models, image, models_dir, reports_dir):
    models = list(models or MODEL_NAMES)
    root = Path(reports_dir) / uuid.uuid4().hex
    root.mkdir(parents=True)
    source = root / "input.png"
    expected = None
    if image is not None:
        decode_image(image).save(source)
    else:
        expected = "Baseline OCR 123"
        raster = Image.new("RGB", (640, 160), "white")
        ImageDraw.Draw(raster).text(
            (30, 45), expected, fill="black", font=ImageFont.load_default(size=36)
        )
        raster.save(source)
    report = {
        "round": 0,
        "input": str(source.resolve()),
        "input_sha256": sha256(source),
        "scope": "one common image per model; functional verification only",
        "models": [],
    }
    readiness = (
        json.loads(readiness_path(models_dir).read_text())
        if readiness_path(models_dir).is_file()
        else {"models": {}}
    )
    available = {
        row["id"]: row for row in model_options(models_dir, include_readiness=False)
    }
    for model in models:
        started = time.perf_counter()
        row = {"model": model, "state": "running"}
        report["models"].append(row)
        write_json(root / "report.json", report)
        print(f"Checking {MODEL_NAMES[model]} on one image", flush=True)
        try:
            if not available[model]["available"]:
                raise ValueError(available[model]["reason"])
            reference = (
                {
                    "text": expected,
                    "reading_order_known": True,
                    "regions": [],
                    "scope": "synthetic",
                    "quality": "synthetic",
                }
                if expected
                else None
            )
            result = extract(
                source,
                model,
                models_dir=models_dir,
                runs_dir=root / "runs",
                reference=reference,
            )
            row.update(
                run_id=result["run_id"], text=result["text"], cost=result.get("cost")
            )
            if not result["text"].strip():
                raise RuntimeError(
                    "OCR returned no text for the text-bearing check image."
                )
            prep = result["variants"][0].get("preprocessing", {})
            if prep.get("finish_reason") == "context_limit":
                raise RuntimeError(
                    "Model exhausted its context before completing the transcription."
                )
            row.update(
                state="completed",
                run_id=result["run_id"],
                text=result["text"],
                cost=result.get("cost"),
                initialization_seconds=sum(
                    step.get("timing", {}).get("engine_acquire_seconds", 0)
                    + step.get("preprocessing", {}).get(
                        "runtime_initialization_seconds", 0
                    )
                    for step in result["variants"]
                ),
                inference_seconds=sum(
                    step.get("preprocessing", {}).get(
                        "runtime_inference_seconds",
                        step.get("timing", {}).get("ocr_seconds", 0),
                    )
                    for step in result["variants"]
                ),
                word_coverage=(result.get("evaluation") or {})
                .get("final", {})
                .get("coverage"),
            )
        except (Exception, KeyboardInterrupt) as error:
            row.update(state="failed", error=str(error) or "Interrupted")
            if isinstance(error, KeyboardInterrupt):
                raise
        finally:
            row["elapsed_seconds"] = time.perf_counter() - started
            row["checked_at"] = datetime.now(timezone.utc).isoformat()
            if readiness_path(models_dir).is_file():
                readiness = json.loads(readiness_path(models_dir).read_text())
            readiness["models"][model] = {
                **row,
                "report": str((root / "report.json").resolve()),
            }
            write_json(readiness_path(models_dir), readiness)
            write_json(root / "report.json", report)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    report["state"] = "completed"
    write_json(root / "report.json", report)
    print(f"Round 0 report: {root / 'report.json'}", flush=True)
    return 0 if all(row["state"] == "completed" for row in report["models"]) else 1
