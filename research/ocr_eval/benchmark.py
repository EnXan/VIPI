"""Run the product OCR session over both pinned catalogs, retaining every attempt."""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import multiprocessing
import os
from pathlib import Path
import platform
import socket
import subprocess
import time

from vipi.config import cache_directory
from vipi.ocr.session import OcrSession
from vipi.storage.files import write_json

from research.detection_eval.evaluation.catalog import Catalog as DetectionCatalog
from .evaluation.catalog import Catalog as OcrCatalog
from .evaluation.metrics import evaluation_policy
from .evaluation.words import words

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATIONS = {
    "local-speed": {"mode": "speed", "execution_mode": "local"},
    "cloud-default": {"execution_mode": "cloud"},
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def catalogs(root=ROOT):
    return {"ocr_eval": OcrCatalog(root), "detection_eval": DetectionCatalog(root)}


def selection(root=ROOT):
    """Freeze order, image/reference hashes and existing category annotations."""
    rows = []
    for suite, catalog in catalogs(root).items():
        for identifier, item in catalog.items.items():
            reference = catalog.reference(identifier)
            reference_json = json.dumps(reference, sort_keys=True, ensure_ascii=False)
            rows.append(
                {
                    "key": f"{suite}:{identifier}",
                    "suite": suite,
                    "id": identifier,
                    "image": item["image"],
                    "image_sha256": digest(catalog.path(identifier)),
                    "reference_sha256": hashlib.sha256(
                        reference_json.encode()
                    ).hexdigest(),
                    "reference_words": len(words(reference["text"])),
                    "scope": reference["scope"],
                    "quality": reference["quality"],
                    "category": item["category"],
                    "techniques": item.get("techniques", []),
                    "obfuscation": item.get("obfuscation", []),
                    "family": "anamorpher"
                    if Path(item["image"]).name.startswith("anamorpher_")
                    else None,
                }
            )
    return rows


def provenance(root=ROOT):
    """Capture executed sources, lockfile, host and installed model runtimes."""
    files = sorted(
        [
            *root.glob("src/vipi/**/*.py"),
            *root.glob("src/vipi/**/*.json"),
            *root.glob("research/ocr_eval/evaluation/*.py"),
            root / "research/detection_eval/evaluation/catalog.py",
            root / "research/ocr_eval/benchmark.py",
            root / "uv.lock",
        ]
    )
    hashes = {p.relative_to(root).as_posix(): digest(p) for p in files}
    packages = {}
    for name in (
        "vipi-scanner",
        "torch",
        "transformers",
        "rapidocr",
        "onnxruntime",
        "Pillow",
        "numpy",
    ):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    hardware = {}
    if platform.system() == "Darwin":
        for key in (
            "machdep.cpu.brand_string",
            "hw.memsize",
            "hw.physicalcpu",
            "hw.logicalcpu",
        ):
            hardware[key] = subprocess.check_output(
                ["sysctl", "-n", key], text=True
            ).strip()
    return {
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "source_hashes": hashes,
        "source_sha256": hashlib.sha256(
            json.dumps(hashes, sort_keys=True).encode()
        ).hexdigest(),
        "dataset": json.loads((root / "research/dataset.json").read_text()),
        "catalog_hashes": {
            suite: digest(root / f"research/{suite}" / filename)
            for suite, filename in (
                ("ocr_eval", "catalog.json"),
                ("detection_eval", "cases.json"),
            )
        },
        "platform": platform.platform(),
        "python": platform.python_version(),
        "hardware": hardware,
        "packages": packages,
    }


def block_network(*args, **kwargs):
    raise RuntimeError("Network access is forbidden in the local OCR benchmark.")


def worker(directory, configuration, rows):
    """Scan without references; write each result before starting the next image."""
    if configuration == "local-speed":
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        socket.create_connection = block_network
        socket.socket.connect = block_network
    directory = Path(directory)
    with OcrSession(**CONFIGURATIONS[configuration]) as session:
        write_json(directory / "session.json", session.metadata)
        for row in rows:
            path = ROOT / "research" / row["suite"] / row["image"]
            if digest(path) != row["image_sha256"]:
                raise ValueError(f"Image changed after selection: {row['key']}")
            record = {"key": row["key"], "status": "running", "started_at": utc_now()}
            started = time.perf_counter()

            def event(value):
                if "artifacts" not in record:
                    record["artifacts"] = str(
                        cache_directory() / "runs" / value["run_id"]
                    )
                    write_json(directory / "current.json", record)

            write_json(directory / "current.json", record)
            try:
                result = session.extract(path, on_event=event)
                record.update(
                    status="completed",
                    artifacts=str(result.artifacts),
                    result_sha256=digest(result.artifacts / "result.json"),
                    pipeline_seconds=result.elapsed_seconds,
                    cost=result.cost,
                )
            except Exception as error:
                record.update(
                    status="failed", error_type=type(error).__name__, error=str(error)
                )
                if getattr(error, "artifacts", None):
                    record["artifacts"] = str(error.artifacts)
            record.update(
                elapsed_seconds=time.perf_counter() - started, finished_at=utc_now()
            )
            write_json(
                directory / "rows" / f"{row['key'].replace(':', '-')}.json", record
            )
            print(
                f"{configuration} {row['key']} {record['status']} {record['elapsed_seconds']:.2f}s",
                flush=True,
            )
            (directory / "current.json").unlink(missing_ok=True)


def retain_interrupted_progress(directory):
    """Preserve the last timing checkpoint and mark an unfinished attempt failed."""
    current = directory / "current.json"
    if current.exists():
        record = json.loads(current.read_text())
        record.update(
            status="failed",
            error_type="InterruptedInvocation",
            error="Previous invocation stopped before recording the result; duration unknown.",
            elapsed_seconds=None,
            finished_at=utc_now(),
        )
        terminal = directory / "rows" / f"{record['key'].replace(':', '-')}.json"
        if not terminal.exists():
            write_json(terminal, record)
        current.unlink()
    checkpoint = directory / "invocation-current.json"
    if checkpoint.exists():
        invocation = json.loads(checkpoint.read_text())
        invocation["interrupted"] = True
        history = directory / "invocations.json"
        previous = json.loads(history.read_text()) if history.exists() else []
        write_json(history, [*previous, invocation])
        checkpoint.unlink()


def run_configuration(directory, configuration, rows):
    """Recycle local workers every four images, retaining crashes as failed attempts."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "rows").mkdir(exist_ok=True)
    retain_interrupted_progress(directory)
    remaining = [
        row
        for row in rows
        if not (directory / "rows" / f"{row['key'].replace(':', '-')}.json").exists()
    ]
    invocation = {
        "started_at": utc_now(),
        "planned_images": len(remaining),
        "workers": [],
    }
    started = time.perf_counter()
    context = multiprocessing.get_context("spawn")
    while remaining:
        chunk = remaining[:4] if configuration == "local-speed" else remaining
        process = context.Process(
            target=worker, args=(str(directory), configuration, chunk)
        )
        worker_started = time.perf_counter()
        process.start()
        process.join()
        invocation["workers"].append(
            {
                "exitcode": process.exitcode,
                "seconds": time.perf_counter() - worker_started,
            }
        )
        current = directory / "current.json"
        if current.exists():
            record = json.loads(current.read_text())
            record.update(
                status="failed",
                error_type="WorkerExit",
                error=f"Worker exited {process.exitcode}.",
                elapsed_seconds=(
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(record["started_at"])
                ).total_seconds(),
                finished_at=utc_now(),
            )
            write_json(
                directory / "rows" / f"{record['key'].replace(':', '-')}.json", record
            )
            current.unlink()
        next_rows = [
            row
            for row in remaining
            if not (
                directory / "rows" / f"{row['key'].replace(':', '-')}.json"
            ).exists()
        ]
        if len(next_rows) == len(remaining):
            raise RuntimeError(
                f"Worker exited {process.exitcode} before scanning an image; see worker output."
            )
        remaining = next_rows
        invocation.update(
            finished_at=utc_now(), elapsed_seconds=time.perf_counter() - started
        )
        write_json(directory / "invocation-current.json", invocation)
    invocation.update(
        finished_at=utc_now(), elapsed_seconds=time.perf_counter() - started
    )
    history_path = directory / "invocations.json"
    history = json.loads(history_path.read_text()) if history_path.exists() else []
    write_json(history_path, [*history, invocation])
    (directory / "invocation-current.json").unlink(missing_ok=True)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", type=Path, help="New or matching resumable benchmark directory"
    )
    parser.add_argument(
        "--configuration",
        choices=CONFIGURATIONS,
        nargs="+",
        default=list(CONFIGURATIONS),
        help="Run sequentially; default: local-speed then cloud-default",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "provenance": provenance(),
        "selection": selection(),
        "evaluation_policy": evaluation_policy(),
        "configurations": CONFIGURATIONS,
        "protocol": "Sequential images/configurations; fresh local process every four images for observed MPS memory growth; no reference access during inference; no benchmark-level retries.",
    }
    path = directory / "manifest.json"
    if path.exists():
        if json.loads(path.read_text()) != manifest:
            raise ValueError(
                "Benchmark inputs or sources changed; use a new directory."
            )
    else:
        write_json(path, manifest)
    for configuration in args.configuration:
        run_configuration(
            directory / configuration, configuration, manifest["selection"]
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
