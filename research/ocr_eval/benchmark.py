"""Run the product scan (OCR and detection) over the evaluation dataset, retaining
every attempt."""

import argparse
from contextlib import ExitStack
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

from vipi.config import ScanOptions, cache_directory
from vipi.detection.pipeline import detect_ocr
from vipi.detection.providers import prepare_provider
from vipi.ocr.session import OcrSession
from vipi.reporting import file_record
from vipi.results import ScanResult
from vipi.scanner import scan_image
from vipi.storage.files import write_json

from research.catalog import CATALOG_NAME, Catalog
from .evaluation.metrics import evaluation_policy
from .evaluation.words import words
from . import ocr_reuse

ROOT = Path(__file__).resolve().parents[2]
# Product scan options (``vipi scan``); the threshold stays at its default and
# the detector at ``auto`` unless a configuration names one.
CONFIGURATIONS = {
    **{
        f"local-{mode}": {"ocr_execution_mode": "local", "ocr_mode": mode}
        for mode in ("speed", "balanced", "quality")
    },
    **{
        f"cloud-{provider}": {"ocr_execution_mode": "cloud", "ocr_provider": provider}
        for provider in ("google", "openai", "mistral")
    },
    # Same cloud OCR and review, final detection by Jev instead of OpenAI.
    **{
        f"cloud-{provider}-jev": {
            "ocr_execution_mode": "cloud",
            "ocr_provider": provider,
            "detector": "jev",
        }
        for provider in ("google", "openai", "mistral")
    },
}


def is_local(configuration):
    return CONFIGURATIONS[configuration]["ocr_execution_mode"] == "local"


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
    """Freeze order, image/reference hashes and labels of every entry. Entries
    without reference text are scanned for detection but not scored for OCR."""
    rows = []
    dataset = catalog(root)
    for identifier, item in dataset.items.items():
        reference = dataset.reference(identifier)
        reference_json = (
            json.dumps(reference, sort_keys=True, ensure_ascii=False)
            if reference
            else None
        )
        rows.append(
            {
                "key": identifier,
                "id": identifier,
                "image": item["image"],
                "image_sha256": digest(dataset.path(identifier)),
                "reference_sha256": hashlib.sha256(reference_json.encode()).hexdigest()
                if reference_json
                else None,
                "reference_words": len(words(reference["text"])) if reference else 0,
                "scope": reference["scope"] if reference else None,
                "quality": reference["quality"] if reference else None,
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

    filter_record = {
        "description": specification.get("description", "Selected catalog subset"),
        "source_report_sha256": specification.get("source_report_sha256"),
        "keys_sha256": hashlib.sha256(
            json.dumps(keys, separators=(",", ":")).encode()
        ).hexdigest(),
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


def detect_reused(ocr, options, provider):
    """Run only detection on an OCR result restored from an earlier run."""
    detection = detect_ocr(
        ocr,
        options=options.detection_options(),
        provider_factory=lambda name: provider,
    )
    return ScanResult(ocr, detection, provider.model, provider.identity)


def scanned_record(result, options):
    scanned = file_record(result)
    return {
        "status": "completed",
        "artifacts": str(result.ocr.artifacts),
        "result_sha256": digest(result.ocr.artifacts / "result.json"),
        "pipeline_seconds": result.ocr.elapsed_seconds,
        "cost": result.ocr.cost,
        "detection": {
            "verdict": scanned["verdict"],
            "max_score": scanned["signals"]
            .get(options.resolved_detector, {})
            .get("max_score"),
            "errors": scanned["errors"],
            "seconds": scanned["detection_seconds"],
            "cost": scanned["detection_cost"],
        },
    }


def worker(directory, configuration, rows, reuse=None):
    """Scan without references; write each result before starting the next image.

    ``reuse`` maps entry keys to earlier results (``ocr_reuse.matching``):
    with a matching detection the earlier result is taken whole, otherwise
    only detection runs. The OCR session opens on the first image that needs
    OCR."""
    reuse = reuse or {}
    if is_local(configuration):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        socket.create_connection = block_network
        socket.socket.connect = block_network
    directory = Path(directory)
    options = ScanOptions(**CONFIGURATIONS[configuration])
    provider = prepare_provider(
        options.resolved_detector, cache_directory() / "prompt-guard"
    )
    with ExitStack() as resources:
        session = None

        def open_session():
            opened = resources.enter_context(
                OcrSession(
                    mode=options.ocr_mode,
                    model=options.resolved_ocr_model,
                    decision_provider=options.resolved_decision_provider,
                )
            )
            write_json(directory / "session.json", opened.metadata)
            return opened

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
                earlier = reuse.get(row["key"])
                whole = bool(earlier and earlier["detection"])
                ocr = (
                    ocr_reuse.restore(earlier, with_detection=whole)
                    if earlier
                    else None
                )
                if ocr is not None:
                    record["artifacts"] = str(ocr.artifacts)
                    write_json(directory / "current.json", record)
                    session_path = directory / "session.json"
                    if not session_path.exists() and Path(earlier["session"]).is_file():
                        # Same OCR identity: the earlier session describes this OCR.
                        session_path.write_bytes(Path(earlier["session"]).read_bytes())
                if ocr is not None and whole:
                    # Same OCR and detection identity: the earlier result stands.
                    record.update(
                        status="completed",
                        artifacts=str(ocr.artifacts),
                        result_sha256=digest(ocr.artifacts / "result.json"),
                        pipeline_seconds=earlier["pipeline_seconds"],
                        cost=earlier["cost"],
                        detection=earlier["detection"],
                    )
                else:
                    if ocr is not None:
                        result = detect_reused(ocr, options, provider)
                    else:
                        session = session or open_session()
                        result = scan_image(
                            path,
                            options=options,
                            session=session,
                            provider=provider,
                            on_event=event,
                        )
                    record.update(scanned_record(result, options))
                if ocr is not None:
                    record["ocr_reused_from"] = {
                        "run_id": earlier["run_id"],
                        "configuration": earlier["configuration"],
                        "run": Path(earlier["artifacts"]).name,
                        "detection": whole,
                    }
            except Exception as error:
                record.update(
                    status="failed", error_type=type(error).__name__, error=str(error)
                )
                if getattr(error, "artifacts", None):
                    record["artifacts"] = str(error.artifacts)
            record.update(
                elapsed_seconds=time.perf_counter() - started, finished_at=utc_now()
            )
            if "ocr_reused_from" in record:
                # Original times, comparable with full runs: the earlier image
                # time, or the earlier OCR time plus this detection.
                record["elapsed_seconds"] = (
                    earlier["elapsed_seconds"]
                    if record["ocr_reused_from"]["detection"]
                    else (record["pipeline_seconds"] or 0)
                    + (record["detection"]["seconds"] or 0)
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


def run_configuration(
    directory, configuration, rows, cancel=None, provenance_record=None, reuse_from=None
):
    """Recycle local workers every four images, retaining crashes as failed attempts.

    Setting ``cancel`` (a threading.Event) stops the worker; the image in
    progress stays unrecorded and is scanned again on resume. With
    ``reuse_from`` (a folder of evaluation runs) and the run's
    ``provenance_record``, images with an earlier OCR result of the same OCR
    identity only run detection (``ocr_reuse``)."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "rows").mkdir(exist_ok=True)
    retain_interrupted_progress(directory)
    remaining = [
        row
        for row in rows
        if not (directory / "rows" / f"{row['key'].replace(':', '-')}.json").exists()
    ]
    reuse = (
        ocr_reuse.matching(
            remaining,
            ocr_reuse.candidates(
                reuse_from,
                CONFIGURATIONS[configuration],
                provenance_record,
                exclude=directory.parent,
            ),
        )
        if reuse_from is not None
        else {}
    )
    invocation = {
        "started_at": utc_now(),
        "planned_images": len(remaining),
        "workers": [],
    }
    started = time.perf_counter()
    context = multiprocessing.get_context("spawn")
    while remaining:
        chunk = remaining[:4] if is_local(configuration) else remaining
        chunk_reuse = {
            row["key"]: reuse[row["key"]] for row in chunk if row["key"] in reuse
        }
        process = context.Process(
            target=worker, args=(str(directory), configuration, chunk, chunk_reuse)
        )
        worker_started = time.perf_counter()
        process.start()
        while process.is_alive():
            process.join(0.5)
            if cancel is not None and cancel.is_set():
                process.terminate()
                process.join()
                (directory / "current.json").unlink(missing_ok=True)
                invocation.update(
                    finished_at=utc_now(),
                    elapsed_seconds=time.perf_counter() - started,
                    cancelled=True,
                )
                write_json(directory / "invocation-current.json", invocation)
                retain_interrupted_progress(directory)
                return
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
        required=True,
        help="Product scan configurations to run, one after another",
    )
    parser.add_argument(
        "--selection-file",
        type=Path,
        help="JSON file freezing an ordered subset of entry ids from the dataset",
    )
    parser.add_argument(
        "--reuse-ocr-from",
        type=Path,
        metavar="RUNS_DIR",
        help="Reuse OCR results of earlier evaluation runs in RUNS_DIR when OCR "
        "settings, OCR sources and the image are identical; detection runs again",
    )
    return parser


def main(argv=None, cancel=None):
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
        if cancel is not None and cancel.is_set():
            break
        run_configuration(
            directory / configuration,
            configuration,
            manifest["selection"],
            cancel,
            provenance_record=manifest["provenance"],
            reuse_from=args.reuse_ocr_from,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
