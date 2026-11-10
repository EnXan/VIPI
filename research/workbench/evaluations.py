"""Evaluate a configuration on a split and keep the baseline, from the workbench.

The workbench calls the same functions as ``python -m research.evaluate``; it
adds a background thread, progress and stopping.
"""

import json
from pathlib import Path
import threading

from research.evaluate import runs, suite
from research.ocr_eval import benchmark


def read_json(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


class EvaluationService:
    def __init__(self, busy, root=benchmark.ROOT, runner=runs.run):
        self.busy = busy
        self.root = Path(root)
        self.runner = runner
        self.active = {}  # run_id -> {"cancel": Event, "error": str | None}

    def directory(self, run_id):
        return runs.run_directory(run_id, self.root)

    def baseline(self, configuration, split):
        """The saved baseline and whether it matches this checkout."""
        result = suite.status(configuration, split, self.root)
        return {
            "state": result["state"],
            "run_id": result.get("baseline", {}).get("run_id"),
            "completed_at": result.get("baseline", {}).get("completed_at"),
            "differences": result.get("differences", []),
        }

    def plan(self, configuration, split, confirm_test):
        return runs.run(
            configuration,
            split,
            self.root,
            confirm_test=confirm_test,
            dry_run=True,
        )

    def start(self, configuration, split, confirm_test, run_id=None, reuse_ocr=True):
        """Start a new run, or resume ``run_id``; returns the run ID.

        A resumed run keeps the OCR reuse choice it started with."""
        if run_id is not None:
            request = read_json(self.directory(run_id) / "request.json")
            if request is None:
                raise ValueError("Unknown evaluation run.")
            configuration = request["manifest"]["configuration_name"]
            split = request["manifest"]["split"]
            confirm_test = split == "test"
        planned = self.plan(configuration, split, confirm_test)  # validates
        run_id = run_id or planned["run_id"]
        if not self.busy.acquire(blocking=False):
            raise RuntimeError("A scan or evaluation is already running.")
        state = {
            "cancel": threading.Event(),
            "error": None,
            "manifest": {
                "configuration_name": configuration,
                "split": split,
                "suite": {"entries": planned["entries"]},
            },
        }
        self.active[run_id] = state

        def work():
            try:
                self.runner(
                    configuration,
                    split,
                    self.root,
                    run_id=run_id,
                    confirm_test=confirm_test,
                    cancel=state["cancel"],
                    reuse_ocr=reuse_ocr,
                )
            except Exception as error:
                state["error"] = str(error) or type(error).__name__
            finally:
                state["finished"] = True
                self.busy.release()

        threading.Thread(target=work, daemon=True).start()
        return run_id

    def stop(self, run_id):
        state = self.active.get(run_id)
        if state is None or state.get("finished"):
            return False
        state["cancel"].set()
        return True

    def progress(self, directory, configuration, entries):
        rows = directory / "benchmark" / configuration / "rows"
        done = len(list(rows.glob("*.json"))) if rows.is_dir() else 0
        return {"done": done, "total": entries}

    def describe(self, run_id, details=True):
        """State, progress and, with ``details``, metrics and comparison."""
        directory = self.directory(run_id)
        request = read_json(directory / "request.json")
        state = self.active.get(run_id, {})
        if request is None and not state:
            raise KeyError(run_id)
        # A starting run has no request file until its inputs are hashed.
        manifest = request["manifest"] if request else state["manifest"]
        configuration = manifest["configuration_name"]
        summary = read_json(directory / "summary.json")
        if state and not state.get("finished"):
            status = "stopping" if state["cancel"].is_set() else "running"
        elif summary:
            status = "complete"
        elif state.get("error"):
            status = "failed"
        else:
            status = "stopped"
        saved = read_json(self.root / suite.BASELINES / f"{run_id}.json")
        return {
            "run_id": run_id,
            "configuration": configuration,
            "split": manifest["split"],
            "state": status,
            "error": state.get("error"),
            "progress": self.progress(
                directory, configuration, manifest["suite"]["entries"]
            ),
            "metrics": summary["metrics"] if summary and details else None,
            "contents": self.contents(directory, configuration) if details else [],
            "comparison": read_json(directory / "comparison.json") if details else None,
            "is_baseline": saved is not None,
            "report_url": f"/api/evaluations/{run_id}/report.md"
            if (directory / "report.md").is_file()
            else None,
            "comparison_url": f"/api/evaluations/{run_id}/comparison.md"
            if (directory / "comparison.md").is_file()
            else None,
        }

    @staticmethod
    def contents(directory, configuration):
        """Per content type: OCR coverage and detection outcome of this run."""
        report = read_json(directory / "report.json")
        if report is None:
            return []
        groups = report["configurations"][configuration]["groups"]
        return [
            {
                "content": group["label"],
                "images": group["images"],
                "word_coverage": group["word_weighted_coverage"],
                "recall": group["detection"]["recall"],
                "false_positive_rate": group["detection"]["false_positive_rate"],
                "accuracy": group["detection"]["accuracy"],
            }
            for group in groups
            if group["facet"] == "content"
        ]

    def listing(self):
        directory = self.root / runs.DEFAULT_RUNS_DIRECTORY
        names = (
            sorted(
                (p.name for p in directory.iterdir() if (p / "request.json").is_file()),
                reverse=True,
            )
            if directory.is_dir()
            else []
        )
        return [self.describe(name, details=False) for name in names]

    def save_baseline(self, run_id):
        return runs.save_baseline(run_id, self.root)

    def markdown(self, run_id, name):
        if name not in {"report.md", "comparison.md"}:
            raise KeyError(name)
        path = self.directory(run_id) / name
        if not path.is_file():
            raise KeyError(name)
        return path
