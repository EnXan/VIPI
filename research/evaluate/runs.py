"""Run one configuration on one frozen split and save a run as the baseline.

A run wraps the benchmark: it freezes the split's keys as a selection file,
scans them with the configuration's product options, scores the retained
outputs and writes a small summary. When a baseline of the same configuration
and split is saved, the run is compared with it. Everything stays in the local
run directory until ``save_baseline`` copies the summary into the repository.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time

from research.ocr_eval import benchmark, benchmark_report, ocr_reuse
from vipi.storage.files import write_json

from . import compare, execution, splits, suite

DEFAULT_RUNS_DIRECTORY = Path("runs/evaluations")
SAMPLE_SECONDS = 0.5


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def default_run_id(configuration, split):
    return f"{utc_stamp()}-{configuration}-{split}"


def git(root, *arguments):
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True
    ).stdout


def implementation(root):
    """Identify the evaluated code, including uncommitted and untracked changes."""
    diff = git(root, "diff", "HEAD", "--binary")
    untracked = sorted(
        name
        for name in git(root, "ls-files", "--others", "--exclude-standard")
        .decode()
        .splitlines()
        if name
    )
    untracked_hashes = {name: benchmark.digest(Path(root) / name) for name in untracked}
    return {
        "commit": git(root, "rev-parse", "HEAD").decode().strip(),
        "dirty": bool(diff or untracked),
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "untracked_sha256": suite.json_sha256(untracked_hashes),
        "untracked_files": len(untracked),
    }


class ResourceMonitor:
    """Sample CPU time and resident memory of this process and its children.

    Worker processes are sampled while alive, so their CPU time is a lower
    bound up to one sampling interval. GPU/MPS memory lives inside worker
    processes and is not observable here; it is reported as unavailable.
    """

    def __init__(self, interval=SAMPLE_SECONDS):
        import psutil

        self.psutil = psutil
        self.interval = interval
        self.process = psutil.Process()
        self.cpu = {}
        self.peak_rss = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def sample(self):
        processes = [self.process]
        try:
            processes += self.process.children(recursive=True)
        except self.psutil.Error:
            pass
        rss = 0
        for process in processes:
            try:
                with process.oneshot():
                    times = process.cpu_times()
                    rss += process.memory_info().rss
                    self.cpu[(process.pid, process.create_time())] = (
                        times.user + times.system
                    )
            except self.psutil.Error:
                continue
        self.peak_rss = max(self.peak_rss, rss)

    def loop(self):
        while not self.stop.wait(self.interval):
            self.sample()

    def __enter__(self):
        self.started = time.perf_counter()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.sample()
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join()
        self.sample()
        self.result = {
            "started_at": self.started_at,
            "wall_seconds": time.perf_counter() - self.started,
            "cpu_seconds_lower_bound": sum(self.cpu.values()),
            "peak_rss_bytes": self.peak_rss,
            "sampling_seconds": self.interval,
            "gpu": {
                "available": False,
                "reason": "GPU/MPS memory is allocated in worker processes and not "
                "observable from the evaluation process.",
            },
        }
        return False


def prepare(configuration, split, root, *, confirm_test=False):
    """Validate a run request and return its manifest and rows."""
    if split == "test" and not confirm_test:
        raise ValueError(
            "The test split is reserved for one confirmation run before a default "
            "changes; pass --confirm-test-split (or confirm it in the workbench)."
        )
    return suite.manifest(configuration, split, root), suite.selected_rows(root, split)


def reusable(configuration, rows, root, runs_root, exclude=None):
    """Count ``rows`` with an earlier result this checkout can reuse.

    Returns ``(ocr, complete)``: images with reusable OCR, and of those the
    images whose detection can be reused as well."""
    if not any(Path(runs_root).glob("*/benchmark/manifest.json")):
        return 0, 0
    found = ocr_reuse.candidates(
        runs_root,
        suite.CONFIGURATIONS[configuration],
        benchmark.provenance(root),
        exclude=exclude,
    )
    matched = ocr_reuse.matching(rows, found)
    return len(matched), sum(item["detection"] is not None for item in matched.values())


def write_or_match(target, value):
    if target.exists():
        if json.loads(target.read_text(encoding="utf-8")) != value:
            raise ValueError(f"{target} belongs to a different run request.")
        return
    write_json(target, value)


def summary_document(request, report, operations):
    name = request["manifest"]["configuration_name"]
    measured = report["configurations"][name]
    metrics = {**measured["summary"]}
    metrics["time"] = {
        key: value for key, value in metrics["time"].items() if key != "invocations"
    }
    host = report["configuration_sources"][name]["provenance"]
    return {
        "kind": suite.SUMMARY_KIND,
        "schema_version": 2,
        "run_id": request["run_id"],
        "completed_at": report["scored_at"],
        "manifest": request["manifest"],
        "test_split_confirmation": request["manifest"]["split"] == "test",
        "implementation": request["implementation"],
        "host": {
            key: host.get(key) for key in ("platform", "python", "hardware", "packages")
        },
        "operations": {
            "invocations": operations,
            "wall_seconds": sum(item["wall_seconds"] for item in operations),
            "cpu_seconds_lower_bound": sum(
                item["cpu_seconds_lower_bound"] for item in operations
            ),
            "peak_rss_bytes": max(item["peak_rss_bytes"] for item in operations),
            "gpu": operations[-1]["gpu"],
        },
        "metrics": metrics,
        "local_artifacts": request["directory"],
    }


def run_directory(run_id, root=benchmark.ROOT, runs_directory=DEFAULT_RUNS_DIRECTORY):
    if not run_id or "/" in run_id or run_id.startswith("."):
        raise ValueError("Invalid run ID.")
    return (Path(root) / runs_directory / run_id).resolve()


def run(
    configuration,
    split="development",
    root=benchmark.ROOT,
    *,
    runs_directory=DEFAULT_RUNS_DIRECTORY,
    run_id=None,
    confirm_test=False,
    dry_run=False,
    cancel=None,
    reuse_ocr=True,
):
    """Run (or resume) one evaluation and compare it with the saved baseline.

    ``cancel`` (a threading.Event) stops the scan; the run is then incomplete
    and resumes with the same run ID. With ``reuse_ocr`` (the default), images
    with an earlier OCR result of the same OCR identity in the runs folder only
    run detection (ADR 0058). A resumed run keeps the choice it started with."""
    root = Path(root)
    manifest, rows = prepare(configuration, split, root, confirm_test=confirm_test)
    run_id = run_id or default_run_id(configuration, split)
    directory = run_directory(run_id, root, runs_directory)
    baseline = suite.latest_baseline(configuration, split, root)
    plan = {
        "run_id": run_id,
        "configuration": configuration,
        "split": split,
        "entries": len(rows),
        "directory": directory.relative_to(root).as_posix(),
        "baseline": baseline[1]["run_id"] if baseline else None,
    }
    runs_root = root / runs_directory
    request_path = directory / "request.json"
    if request_path.exists():
        reuse_ocr = json.loads(request_path.read_text(encoding="utf-8")).get(
            "reuse_ocr", False
        )
    plan["reuse_ocr"] = reuse_ocr
    if dry_run:
        plan["reusable_ocr"], plan["reusable_complete"] = reusable(
            configuration, rows, root, runs_root, exclude=directory / "benchmark"
        )
        return {"state": "planned", **plan}
    directory.mkdir(parents=True, exist_ok=True)
    selection_path = directory / "selection.json"
    write_or_match(
        selection_path,
        {
            "description": f"{configuration} on the {split} split",
            "keys": [row["key"] for row in rows],
            "split_method": f"{splits.SPLITS_PATH.as_posix()} sha256 "
            f"{manifest['suite']['splits_sha256']}",
        },
    )
    if request_path.exists():
        request = json.loads(request_path.read_text(encoding="utf-8"))
        recorded = suite.comparable(
            request["manifest"], request.get("implementation"), root
        )
        if recorded != manifest:
            raise ValueError(f"{directory} belongs to a different run request.")
    else:
        request = {
            "run_id": run_id,
            "directory": plan["directory"],
            "manifest": manifest,
            "implementation": implementation(root),
            "reuse_ocr": reuse_ocr,
        }
        write_json(request_path, request)

    with ResourceMonitor() as monitor:
        benchmark.main(
            [
                str(directory / "benchmark"),
                "--configuration",
                configuration,
                "--selection-file",
                str(selection_path),
                *(["--reuse-ocr-from", str(runs_root)] if reuse_ocr else []),
            ],
            cancel=cancel,
        )
    operations_path = directory / "operations.json"
    operations = (
        json.loads(operations_path.read_text(encoding="utf-8"))
        if operations_path.exists()
        else []
    ) + [monitor.result]
    write_json(operations_path, operations)

    report = benchmark_report.report(directory / "benchmark")
    (directory / "report.json").write_text(
        json.dumps(report, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    reuse = ocr_reuse.summary(
        directory / "benchmark" / configuration, benchmark.is_local(configuration)
    )
    executed = execution.record(request["manifest"]["configuration"]["scan_options"])
    extra = ocr_reuse.report_lines(reuse, len(rows)) + execution.report_lines(executed)
    (directory / "report.md").write_text(
        benchmark_report.markdown(report).rstrip("\n")
        + "\n"
        + "".join(f"{line}\n" for line in extra),
        encoding="utf-8",
    )
    if not report["inference_complete"]:
        return {"state": "incomplete", **plan}
    summary = summary_document(request, report, operations)
    summary["report_sha256"] = benchmark.digest(directory / "report.json")
    summary["reused"] = reuse
    summary["execution"] = executed
    write_json(directory / "summary.json", summary)
    result = {"state": "complete", **plan}
    if baseline:
        data = compare.compare(baseline[1], summary, root)
        compare.write(data, directory)
        result["comparison"] = {
            "matched": data["matched"],
            "differences": data["differences"],
            "case_counts": data["case_counts"],
        }
    return result


def save_baseline(
    run_id, root=benchmark.ROOT, *, runs_directory=DEFAULT_RUNS_DIRECTORY
):
    """Copy a complete run's summary into the repository as the baseline."""
    root = Path(root)
    source = run_directory(run_id, root, runs_directory) / "summary.json"
    if not source.is_file():
        raise ValueError(f"Run {run_id} is not complete; finish it first.")
    summary = json.loads(source.read_text(encoding="utf-8"))
    target = root / suite.BASELINES / f"{run_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return target
