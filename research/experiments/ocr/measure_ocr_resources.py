"""Measure one uncached screening image in a fresh child process on macOS/Linux."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from vipi.storage.ocr import write_json
from research.experiments.ocr.ocr_screening import ROOT, check_manifest


def measure(directory):
    manifest = check_manifest(directory)
    if len(manifest["samples"]) != 1:
        raise ValueError("Resource probe requires exactly one image.")
    if any(directory.glob("samples/*/steps/*.json")):
        raise ValueError("Use a fresh probe; cached OCR is not a resource measurement.")
    sample = manifest["samples"][0]
    command = [sys.executable, str(Path(__file__).with_name("ocr_screening.py")),
               "_image", str(directory), "--id", sample["id"], "--stage", "views"]
    started = time.perf_counter()
    with (directory / "views.log").open("w") as stdout, (directory / "stderr.log").open("w") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr)
        # wait4 measures this known child, including all four worker threads;
        # no process-list access or system-wide CPU/RAM estimate is involved.
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    elapsed = time.perf_counter() - started
    # macOS reports ru_maxrss in bytes; Linux reports KiB.
    rss_bytes = usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    paths = [p for p in directory.rglob("*") if p.is_file()]
    result = {
        "sample_id": sample["id"], "image": sample["image"],
        "input_dimensions": sample["dimensions"], "model": manifest["model"],
        "backend": manifest["backend"], "workers": manifest["workers"],
        "threads_per_worker": manifest["threads_per_worker"],
        "concurrency_policy": manifest["design"]["memory"],
        "scope": "fresh process, all 32 unfiltered whole-image views; no tiles or filters",
        "exit_code": process.returncode, "elapsed_seconds": elapsed,
        "user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
        "average_cpu_cores": (usage.ru_utime + usage.ru_stime) / elapsed,
        "average_cpu_machine_percent": (usage.ru_utime + usage.ru_stime) / elapsed / manifest["cpu_count"] * 100,
        "peak_resident_bytes": rss_bytes, "peak_resident_gib": rss_bytes / 1024**3,
        "measurement": "os.wait4 child resource usage; ru_maxrss is process high-water RSS, not total system RAM",
        "artifact_bytes": sum(p.stat().st_size for p in paths),
        "completed_steps": len(list(directory.glob("samples/*/steps/*.json"))),
        "includes": "model/framework initialization, transforms, OCR and persistence; final assembly is timed separately",
    }
    write_json(directory / "resources.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(measure(Path(sys.argv[1]).resolve()))
