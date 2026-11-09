"""Run the product OCR session over the evaluation dataset, retaining every attempt."""

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

from research.catalog import CATALOG_NAME, Catalog
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


def dataset_directory(root=None):
    return Path(root or ROOT) / "research/dataset"


def catalog(root=ROOT):
    return Catalog(dataset_directory(root))


def selection(root=ROOT):
    """Freeze order, image/reference hashes and labels of every entry that has
    reference text; entries without one cannot be scored for OCR."""
    rows = []
    dataset = catalog(root)
    for identifier, item in dataset.items.items():
        reference = dataset.reference(identifier)
        if reference is None:
            continue
        reference_json = json.dumps(reference, sort_keys=True, ensure_ascii=False)
        rows.append(
            {
                "key": identifier,
                "id": identifier,
                "image": item["image"],
                "image_sha256": digest(dataset.path(identifier)),
                "reference_sha256": hashlib.sha256(reference_json.encode()).hexdigest(),
                "reference_words": len(words(reference["text"])),
                "scope": reference["scope"],
                "quality": reference["quality"],
                "label": item["label"],
                "content": item["content"],
                "techniques": item["techniques"],
                "obfuscation": item["obfuscation"],
            }
        )
    return rows


def selection_from_file(path, root=ROOT):
    """Freeze an ordered subset of active catalog keys from a JSON selection."""
    specification = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(specification, dict):
        raise ValueError("Selection file must contain a JSON object.")
    keys = specification.get("keys")
    if (
        not isinstance(keys, list)
        or not keys
        or not all(isinstance(key, str) for key in keys)
    ):
        raise ValueError(
            "Selection file must contain a nonempty string list named keys."
        )
    if len(keys) != len(set(keys)):
        raise ValueError("Selection file contains duplicate keys.")

    complete = selection(root)
    by_key = {row["key"]: row for row in complete}
    key_set = set(keys)
    missing = key_set - set(by_key)
    if missing:
        raise ValueError(f"Selection contains unknown catalog keys: {sorted(missing)}")
    selected = [row for row in complete if row["key"] in key_set]
    if [row["key"] for row in selected] != keys:
        raise ValueError("Selection keys must use the active catalog order.")

    split = specification.get("confidence_split")
    if split is not None:
        if not isinstance(split, dict):
            raise ValueError("Confidence split must map image hashes to split names.")
        hashes = {row["image_sha256"] for row in selected}
        if (
            set(split) != hashes
            or not set(split.values()) <= {"calibration", "evaluation"}
            or set(split.values()) != {"calibration", "evaluation"}
        ):
            raise ValueError("Confidence split must label every selected image hash.")

    filter_record = {
        "description": specification.get("description", "Selected catalog subset"),
        "source_report_sha256": specification.get("source_report_sha256"),
        "keys_sha256": hashlib.sha256(
            json.dumps(keys, separators=(",", ":")).encode()
        ).hexdigest(),
        "confidence_split": split,
        "split_method": specification.get("split_method"),
    }
    return selected, filter_record


def provenance(root=ROOT):
    """Capture executed sources, lockfile, host and installed model runtimes."""
    files = sorted(
        [
            *root.glob("src/vipi/**/*.py"),
            *root.glob("src/vipi/**/*.json"),
            *root.glob("research/ocr_eval/evaluation/*.py"),
            root / "research/catalog.py",
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
    hardware_unavailable = []
    if platform.system() == "Darwin":
        for key in (
            "machdep.cpu.brand_string",
            "hw.memsize",
            "hw.physicalcpu",
            "hw.logicalcpu",
        ):
            try:
                result = subprocess.run(
                    ["sysctl", "-n", key],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except OSError:
                hardware[key] = None
                hardware_unavailable.append(key)
                continue
            if result.returncode == 0:
                hardware[key] = result.stdout.strip()
            else:
                hardware[key] = None
                hardware_unavailable.append(key)
    return {
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "source_hashes": hashes,
        "source_sha256": hashlib.sha256(
            json.dumps(hashes, sort_keys=True).encode()
        ).hexdigest(),
        "dataset": json.loads((root / "research/dataset.json").read_text()),
        "catalog_sha256": digest(dataset_directory(root) / CATALOG_NAME),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "hardware": hardware,
        "hardware_unavailable": hardware_unavailable,
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
            path = dataset_directory() / row["image"]
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
    parser.add_argument(
        "--selection-file",
        type=Path,
        help="JSON file freezing an ordered subset of entry ids from the dataset",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    selected, selection_filter = (
        selection_from_file(args.selection_file)
        if args.selection_file
        else (selection(), None)
    )
    if not args.configuration or len(args.configuration) != len(
        set(args.configuration)
    ):
        raise ValueError("Choose each benchmark configuration at most once.")
    manifest = {
        "schema_version": 1,
        "provenance": provenance(),
        "selection": selected,
        "selection_filter": selection_filter,
        "evaluation_policy": evaluation_policy(),
        "configurations": {name: CONFIGURATIONS[name] for name in args.configuration},
        "protocol": "Sequential images/configurations; local-only workers restart every four images for observed MPS memory growth; no reference access during inference; no benchmark-level retries.",
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
