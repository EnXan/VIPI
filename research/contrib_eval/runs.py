"""Run scoped baseline and candidate evaluations on one frozen split.

A run wraps the existing OCR benchmark: it freezes the split's keys as a
selection file, runs only the path's benchmark configuration, scores the
retained outputs with the benchmark report and writes a small summary for the
repository. Full per-case artifacts stay in the local run directory.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time

from research.ocr_eval import benchmark, benchmark_report
from vipi.storage.files import write_json

from . import splits, suite

DEFAULT_RUNS_DIRECTORY = Path("runs/contrib")
ROLES = ("baseline", "candidate")
SAMPLE_SECONDS = 0.5


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def default_run_id(path, role, split):
    return f"{utc_stamp()}-{role}-{path.replace('/', '-')}-{split}"


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


def load_baseline(reference, root):
    """Load a committed baseline summary from its path or run ID."""
    path = Path(reference)
    if not path.suffix:
        matches = sorted(
            Path(root).glob(f"research/*/reports/contrib/{reference}.json")
        )
        if len(matches) != 1:
            raise ValueError(
                f"Baseline run {reference!r} not found in committed reports."
            )
        path = matches[0]
    elif not path.is_absolute():
        path = Path(root) / path
    summary = json.loads(path.read_text(encoding="utf-8"))
    if summary.get("kind") != suite.SUMMARY_KIND or summary.get("role") != "baseline":
        raise ValueError(f"{path} is not a baseline summary.")
    return path, summary


def compare_to_baseline(manifest, against, mismatch_reason, root):
    path, baseline = load_baseline(against, root)
    changed = suite.differences(baseline["manifest"], manifest)
    if changed and not mismatch_reason:
        raise ValueError(
            "Candidate inputs differ from the baseline: "
            + ", ".join(changed)
            + ". Refresh the baseline, or pass --allow-mismatch with a reason to "
            "record a non-matched run."
        )
    return {
        "baseline_run_id": baseline["run_id"],
        "baseline_summary": path.relative_to(root).as_posix(),
        "matched": not changed,
        "differences": changed,
        "mismatch_reason": mismatch_reason if changed else None,
    }


def prepare(
    path, role, split, root, *, against=None, mismatch_reason=None, confirm_test=False
):
    """Validate a run request and return its manifest, rows and comparison."""
    if role not in ROLES:
        raise ValueError(f"Choose role {' or '.join(ROLES)}.")
    if split == "test" and not confirm_test:
        raise ValueError(
            "The test split is reserved for one confirmation run before a default "
            "changes; pass --confirm-test-split to use it."
        )
    if role == "candidate" and not against:
        raise ValueError("A candidate run requires --against <baseline run ID>.")
    if role == "baseline" and against:
        raise ValueError("--against applies only to candidate runs.")
    manifest = suite.manifest(path, split, root)
    comparison = (
        compare_to_baseline(manifest, against, mismatch_reason, root)
        if role == "candidate"
        else None
    )
    return manifest, suite.selected_rows(root, split), comparison


def write_or_match(target, value):
    if target.exists():
        if json.loads(target.read_text(encoding="utf-8")) != value:
            raise ValueError(f"{target} belongs to a different run request.")
        return
    write_json(target, value)


def summary_document(request, report, operations, root):
    configuration = request["manifest"]["configuration"]["benchmark_configuration"]
    name = next(iter(configuration))
    measured = report["configurations"][name]
    metrics = {**measured["summary"]}
    metrics["time"] = {
        key: value for key, value in metrics["time"].items() if key != "invocations"
    }
    host = report["configuration_sources"][name]["provenance"]
    return {
        "kind": suite.SUMMARY_KIND,
        "schema_version": 1,
        "role": request["role"],
        "run_id": request["run_id"],
        "completed_at": report["scored_at"],
        "manifest": request["manifest"],
        "comparison": request["comparison"],
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


def run(
    path,
    role,
    split="development",
    root=benchmark.ROOT,
    *,
    runs_directory=DEFAULT_RUNS_DIRECTORY,
    run_id=None,
    against=None,
    mismatch_reason=None,
    confirm_test=False,
    dry_run=False,
):
    """Run (or resume) one scoped evaluation and write its committed summary."""
    root = Path(root)
    manifest, rows, comparison = prepare(
        path,
        role,
        split,
        root,
        against=against,
        mismatch_reason=mismatch_reason,
        confirm_test=confirm_test,
    )
    run_id = run_id or default_run_id(path, role, split)
    directory = (root / runs_directory / run_id).resolve()
    plan = {
        "run_id": run_id,
        "path": path,
        "split": split,
        "role": role,
        "entries": len(rows),
        "directory": directory.relative_to(root).as_posix(),
        "comparison": comparison,
    }
    if dry_run:
        return {"state": "planned", **plan}
    directory.mkdir(parents=True, exist_ok=True)
    selection_path = directory / "selection.json"
    write_or_match(
        selection_path,
        {
            "description": f"{path} on the {split} split",
            "keys": [row["key"] for row in rows],
            "split_method": f"{splits.SPLITS_PATH.as_posix()} sha256 "
            f"{manifest['suite']['splits_sha256']}",
        },
    )
    request_path = directory / "request.json"
    if request_path.exists():
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if request["manifest"] != manifest or request["comparison"] != comparison:
            raise ValueError(f"{directory} belongs to a different run request.")
    else:
        request = {
            "role": role,
            "run_id": run_id,
            "directory": plan["directory"],
            "manifest": manifest,
            "comparison": comparison,
            "implementation": implementation(root),
        }
        write_json(request_path, request)

    configuration = manifest["configuration"]["benchmark_configuration"]
    with ResourceMonitor() as monitor:
        benchmark.main(
            [
                str(directory / "benchmark"),
                "--configuration",
                next(iter(configuration)),
                "--selection-file",
                str(selection_path),
            ]
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
    if not report["inference_complete"]:
        return {"state": "incomplete", **plan}
    summary = summary_document(request, report, operations, root)
    summary["report_sha256"] = benchmark.digest(directory / "report.json")
    target = root / suite.path_definition(path)["reports"] / f"{run_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return {"state": "complete", "summary": target.relative_to(root).as_posix(), **plan}
