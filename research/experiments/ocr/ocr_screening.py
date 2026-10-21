"""Resumable, offline transformation screening on a frozen small OCR selection.

This experiment uses the production transforms, OCR adapters and assembly. It
does not change the production scan or use references to guide OCR execution.
Run each image in a fresh process so large ONNX allocation arenas are released.
"""

import argparse
from concurrent.futures import as_completed
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

import cv2
from PIL import Image

from research.datasets.catalog import Catalog
from vipi.ocr.engine_pool import EnginePool
from research.evaluation.metrics import compare, final_observations
from vipi.ocr.merge import ASSEMBLY_VERSION, assemble
from vipi.ocr.models import FILES, REQUIRED, sha256, validate_model
from vipi.ocr.runtime import threads_per_worker
from vipi.storage.ocr import write_json
from vipi.ocr.transforms import (
    FILTERS, apply_filter, decode_image, render_view, views_for_size,
)

ROOT = Path(__file__).resolve().parents[3]
VERSION = 2
DEFAULT_IDS = (
    "f40d5ffa8509655f", "5b0db29db65623f3", "f036ac749f52f386",
    "7751e5a6e4185fee", "5572af300a56a5ef", "50ee400401ffab1a",
    "0f2be1a03e8ebf28",
)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def protocol_fingerprint(manifest):
    return digest({key: manifest.get(key) for key in (
        "profiles", "separate_stage_directories", "model", "backend", "workers",
        "threads_per_worker", "models", "samples", "source_hashes",
        "environment",
    )})


def source_hashes():
    paths = [Path(__file__), *[
        ROOT / "src/vipi/ocr" / name for name in (
            "transforms.py", "engines.py", "merge.py", "models.py",
            "runtime.py", "engine_pool.py", "workers.py", "model_files.json",
        )
    ], ROOT / "research/evaluation/metrics.py", ROOT / "research/datasets/catalog.py",
        ROOT / "src/vipi/storage/ocr.py", ROOT / "src/vipi/storage/files.py",
        ROOT / "src/vipi/storage/events.py"]
    return {p.relative_to(ROOT).as_posix(): sha256(p) for p in paths}


def split_for(group):
    if group.startswith("anamorpher_payload_"):
        return "holdout" if group.endswith("orange") else "development"
    return "holdout" if int(hashlib.sha256(("42:" + group).encode()).hexdigest(), 16) % 5 == 0 else "development"


def prepare(directory, ids=None, workers=4, expected_split="development"):
    if directory.exists():
        raise ValueError("Choose a new experiment directory; existing runs are resumed with run.")
    catalog = Catalog(ROOT)
    selected = list(ids or DEFAULT_IDS)
    if ids is None:
        for sample in ("anamorpher_0000", "anamorpher_0288", "anamorpher_0576"):
            selected.append(next(x["id"] for x in catalog.items.values() if x["details"].get("sample_id") == sample))
    if len(set(selected)) != len(selected):
        raise ValueError("Repeated image IDs.")
    models = ROOT / "models/ocr"
    validate_model("ppocr-v6", models, verify=True)
    samples = []
    for identifier in selected:
        item = catalog.get(identifier)
        group = item["details"]["content_group_id"]
        if split_for(group) != expected_split:
            raise ValueError(
                f"Expected {expected_split} content groups, got {split_for(group)}."
            )
        with Image.open(catalog.path(identifier)) as image:
            dimensions = list(image.size)
        reference = catalog.reference(identifier)
        samples.append({
            "id": identifier, "image": item["image"], "category": item["category"],
            "sha256": sha256(catalog.path(identifier)), "reference": reference,
            "dimensions": dimensions, "content_group_id": group,
            "filtered_input": "ocr_obfuscation" in item["image"],
            "reference_review": "source_reference_not_yet_visually_checked",
            "scope": item["details"].get("scope"),
            "declared_downscale": item["details"].get("downscale"),
        })
    versions = {}
    for name in ("numpy", "Pillow", "opencv-python", "rapidocr", "onnxruntime", "torch", "tensorflow"):
        versions[name] = importlib.metadata.version(name)
    manifest = {
        "version": VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
        "model": "ppocr-v6", "backend": "cpu", "workers": workers,
        "threads_per_worker": threads_per_worker(workers),
        "platform": platform.platform(), "cpu_count": os.cpu_count(),
        "libraries": versions, "source_hashes": source_hashes(),
        "models": {FILES[k]["file"]: sha256(models / FILES[k]["file"]) for k in REQUIRED["ppocr-v6"]},
        "catalog_sha256": sha256(ROOT / "research/datasets/data/catalog/ocr/ocr_metadata.json"),
        "selection_report_sha256": sha256(ROOT / "research/datasets/data/catalog/ocr/ocr_selection_report.json"),
        "design": {
            "selection": "purposeful development sample, 3 TextOCR + 4 other base sources + 3 Anamorpher generators",
            "base_filtered_inputs": 2, "seed": 20261019,
            "split": "SHA256('42:' + content_group_id) modulo 5; 0=holdout; Anamorpher blue=development, orange=holdout",
            "holdout": "not evaluated or used for tuning",
            "views": "all 32 unfiltered whole-image views; no tiles",
            "memory": "at most 12 MP in flight; a larger view runs alone; fresh process per image",
            "timing": "measured CPU run, per-step OCR wall time under up to four workers; not additive elapsed time",
        },
        "samples": samples,
    }
    directory.mkdir(parents=True)
    write_json(directory / "manifest.json", manifest)
    # A split over the entire index keeps unseen group variants out of future tuning.
    write_json(directory / "split.json", {x["id"]: {"group": x["details"]["content_group_id"], "split": split_for(x["details"]["content_group_id"])} for x in catalog.items.values()})
    print(f"Prepared {len(samples)} images in {directory}", flush=True)


def check_manifest(directory):
    manifest = read(directory / "manifest.json")
    if manifest["source_hashes"] != source_hashes():
        raise ValueError("Experiment or OCR source changed; use a new experiment version.")
    if manifest.get("protocol_sha256") and manifest["protocol_sha256"] != protocol_fingerprint(manifest):
        raise ValueError("Frozen experiment protocol changed; use a new experiment.")
    for filename, expected in manifest["models"].items():
        if sha256(ROOT / "models/ocr" / filename) != expected:
            raise ValueError("Model changed.")
    for sample in manifest["samples"]:
        if sha256(ROOT / sample["image"]) != sample["sha256"]:
            raise ValueError(f"Image changed: {sample['id']}")
    return manifest


def schedule(sample, stage, directory):
    views = [v for v in views_for_size(*sample["dimensions"]) if v.crop is None]
    manifest_path = directory / "manifest.json"
    profile = read(manifest_path).get("profiles", {}).get(stage) if manifest_path.exists() else None
    if profile is not None:
        selected_views = profile.get("view_ids")
        pairs = {(p["view_id"], p["filter"]) for p in profile.get("passes", [])}
        result = []
        for index, view in enumerate(views):
            if view.factor == 2 and view.width * view.height > profile.get("two_times_max_pixels", float("inf")):
                continue
            for fi, name in enumerate(FILTERS):
                selected = (view.id, name) in pairs if "passes" in profile else (
                    (selected_views is None or view.id in selected_views)
                    and name in profile["filters"]
                )
                if selected:
                    result.append((index * len(FILTERS) + fi + 1, view, name))
        if not result:
            raise ValueError(f"Profile {stage} has no applicable OCR passes.")
        return result
    if stage == "filters":
        chosen = read(directory / "filter_plan.json")["view_ids"]
    else:
        chosen = [v.id for v in views]
    result = []
    for index, view in enumerate(views):
        for fi, name in enumerate(FILTERS):
            if view.id not in chosen or (stage == "views") != (name == "unchanged"):
                continue
            number = index * len(FILTERS) + fi + 1
            result.append((number, view, name))
    return result


class PixelBudget:
    def __init__(self, limit=12_000_000):
        self.limit = limit
        self.used = 0
        self.condition = threading.Condition()

    @contextmanager
    def claim(self, pixels):
        with self.condition:
            self.condition.wait_for(lambda: self.used == 0 or self.used + pixels <= self.limit)
            self.used += pixels
        try:
            yield
        finally:
            with self.condition:
                self.used -= pixels
                self.condition.notify_all()


def run_image(directory, identifier, stage):
    manifest = check_manifest(directory)
    sample = next(x for x in manifest["samples"] if x["id"] == identifier)
    destination = directory / "samples" / identifier
    if manifest.get("separate_stage_directories"):
        destination /= stage
    (destination / "steps").mkdir(parents=True, exist_ok=True)
    (destination / "images").mkdir(exist_ok=True)
    cv2.setNumThreads(1)
    original = decode_image(ROOT / sample["image"])
    tasks = schedule(sample, stage, directory)
    if stage == "filters":
        for number, _, _ in schedule(sample, "views", directory):
            if not (destination / "steps" / f"{number:04d}.json").is_file():
                raise ValueError("Complete unfiltered views before testing filters.")
    missing = [(n, v, f) for n, v, f in tasks if not (destination / "steps" / f"{n:04d}.json").exists()]
    status = {"sample_id": identifier, "stage": stage, "state": "running", "planned": len(tasks), "reused": len(tasks)-len(missing)}
    status_file = destination / f"{stage}_status.json"
    write_json(status_file, status)
    started = time.perf_counter()
    budget = PixelBudget()
    lock = threading.Lock()
    completed = 0

    with EnginePool(manifest["model"], ROOT / "models/ocr", manifest["workers"], manifest["backend"]) as pool:
        def work(task):
            nonlocal completed
            number, view, name = task
            with budget.claim(view.width * view.height):
                engine = pool.engine()
                start = time.perf_counter()
                raster = apply_filter(render_view(original, view), name)
                transform_seconds = time.perf_counter() - start
                start = time.perf_counter()
                image_path = destination / "images" / f"{number:04d}.png"
                raster.save(image_path)
                image_save_seconds = time.perf_counter() - start
                start = time.perf_counter()
                observed = engine.recognize(raster)
                ocr_seconds = time.perf_counter() - start
                for region in observed["regions"]:
                    region["input_polygon"] = view.map_polygon(region["polygon"])
                step = {
                    "id": f"{number:04d}", "index": number, "view_id": view.id,
                    "filter": name, "width": view.width, "height": view.height,
                    "label": f"{view.id} · {name}", "transformation": asdict(view),
                    "image": image_path.relative_to(directory).as_posix(),
                    "raster_sha256": sha256(image_path), **observed,
                    "timing": {"transform_seconds": transform_seconds, "image_save_seconds": image_save_seconds, "ocr_seconds": ocr_seconds},
                }
                # References are consulted only in the later report process.
                write_json(destination / "steps" / f"{number:04d}.json", step)
                with lock:
                    completed += 1
                    status.update(completed=completed, elapsed_seconds=time.perf_counter()-started)
                    write_json(status_file, status)
                    print(f"{identifier} {stage} {completed + status['reused']}/{len(tasks)} {view.id}/{name}: {ocr_seconds:.2f}s, {len(observed['text'])} chars", flush=True)
        futures = [pool.executor.submit(work, task) for task in missing]
        errors = []
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as error:
                errors.append(str(error))
                print(f"ERROR {identifier}: {error}", flush=True)
    status.update(state="failed" if errors else "completed", elapsed_seconds=time.perf_counter()-started, errors=errors)
    history = destination / "sessions.jsonl"
    with history.open("a", encoding="utf-8") as file:
        file.write(json.dumps(status) + "\n")
    write_json(status_file, status)
    return 1 if errors else 0


def run(directory, stage):
    manifest = check_manifest(directory)
    status_path = directory / f"{stage}_status.json"
    previous = read(status_path) if status_path.exists() else {}
    if previous.get("state") == "completed":
        for sample in manifest["samples"]:
            saved = directory / "samples" / sample["id"]
            if manifest.get("separate_stage_directories"):
                saved /= stage
            for number, _, _ in schedule(sample, stage, directory):
                if not (saved / "steps" / f"{number:04d}.json").is_file():
                    raise ValueError("Completed stage has missing results.")
        print(f"Stage {stage} already completed; original timings preserved.", flush=True)
        return 0
    started = time.perf_counter()
    outcomes = []
    for i, sample in enumerate(manifest["samples"], 1):
        print(f"IMAGE {i}/{len(manifest['samples'])}: {sample['category']} {sample['id']}", flush=True)
        command = [sys.executable, str(Path(__file__).resolve()), "_image", str(directory), "--id", sample["id"], "--stage", stage]
        child_started = time.perf_counter()
        process = subprocess.Popen(command, cwd=ROOT)
        measurement = {}
        if hasattr(os, "wait4"):
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
            measurement = {
                "user_cpu_seconds": usage.ru_utime,
                "system_cpu_seconds": usage.ru_stime,
                "peak_resident_bytes": usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
            }
        else:
            process.wait()
        outcomes.append({"sample_id": sample["id"], "exit_code": process.returncode,
                         "elapsed_seconds": time.perf_counter() - child_started, **measurement})
        write_json(directory / f"{stage}_status.json", {"state": "running", "outcomes": outcomes, "elapsed_seconds": time.perf_counter()-started})
    write_json(directory / f"{stage}_status.json", {"state": "completed" if all(x["exit_code"] == 0 for x in outcomes) else "failed", "outcomes": outcomes, "elapsed_seconds": time.perf_counter()-started})
    return 0 if all(x["exit_code"] == 0 for x in outcomes) else 1


def load_samples(directory, manifest):
    rows = []
    for sample in manifest["samples"]:
        files = sorted((directory / "samples" / sample["id"] / "steps").glob("*.json"))
        steps = [read(p) for p in files]
        planned = schedule(sample, "views", directory)
        expected = {f"{n:04d}" for n, _, _ in planned}
        if not expected <= {x["id"] for x in steps}:
            raise ValueError(f"Incomplete base views for {sample['id']}")
        ref = sample["reference"]
        matches = {}
        scores = {}
        for step in steps:
            scores[step["id"]], _, matches[step["id"]] = compare(ref, step["text"], step["regions"])
        rows.append({"sample": sample, "steps": steps, "matches": matches, "scores": scores})
    return rows


def selected_summary(row, identifiers):
    steps = [x for x in row["steps"] if x["id"] in identifiers]
    text, regions = assemble(steps)
    reference = row["sample"]["reference"]
    observations = regions if reference["reading_order_known"] else final_observations(regions, steps)
    final, _, _ = compare(reference, text, observations)
    union = set().union(*(row["matches"][x["id"]] for x in steps))
    return {"final": final, "oracle_tokens_across_steps": len(union), "text": text,
            "ocr_work_seconds": sum(x["timing"]["ocr_seconds"] for x in steps), "passes": len(steps)}


def greedy_views(rows, max_views=8):
    views = sorted({x["view_id"] for x in rows[0]["steps"] if x["filter"] == "unchanged"})
    chosen = ["original-unchanged-1x"]
    history = []
    # Average each image's fractional coverage gain so long references cannot dominate.
    while len(chosen) < max_views:
        options = []
        for view in views:
            if view in chosen:
                continue
            gain, work, count = 0.0, 0.0, 0
            for row in rows:
                current = set().union(*(row["matches"][x["id"]] for x in row["steps"] if x["view_id"] in chosen and x["filter"] == "unchanged"))
                step = next(x for x in row["steps"] if x["view_id"] == view and x["filter"] == "unchanged")
                added = len(row["matches"][step["id"]] - current)
                count += added
                total = row["scores"][step["id"]]["total"]
                gain += added / max(1, total)
                work += step["timing"]["ocr_seconds"]
            options.append((gain / max(work, 1e-9), gain, view, count, work))
        if not options:
            break
        _, gain, view, count, work = max(options)
        if gain <= 0:
            break
        chosen.append(view)
        history.append({"view_id": view, "additional_reference_tokens": count, "mean_coverage_gain": gain/len(rows), "ocr_work_seconds": work})
    return chosen, history


def report(directory):
    manifest = check_manifest(directory)
    rows = load_samples(directory, manifest)
    chosen, history = greedy_views(rows)
    summaries = []
    by_step = {}
    for row in rows:
        sample = row["sample"]
        base = [x for x in row["steps"] if x["filter"] == "unchanged"]
        full_union = set().union(*(row["matches"][x["id"]] for x in base))
        original = row["scores"]["0001"]
        for step in row["steps"]:
            key = step["view_id"] + "/" + step["filter"]
            stats = by_step.setdefault(key, {"view_id": step["view_id"], "filter": step["filter"], "images": 0, "coverage_sum": 0, "complete_images": 0, "extra_tokens_vs_original": 0, "unique_tokens_among_base_views": 0, "ocr_work_seconds": 0, "ocr_seconds_by_image": []})
            evaluation = row["scores"][step["id"]]
            stats["images"] += 1
            stats["coverage_sum"] += evaluation["coverage"]
            stats["complete_images"] += int(evaluation["valid"])
            stats["extra_tokens_vs_original"] += len(row["matches"][step["id"]] - row["matches"]["0001"])
            others = set().union(*(row["matches"][x["id"]] for x in base if x["id"] != step["id"]))
            if step["filter"] == "unchanged":
                stats["unique_tokens_among_base_views"] += len(full_union - others)
            stats["ocr_work_seconds"] += step["timing"]["ocr_seconds"]
            stats["ocr_seconds_by_image"].append(step["timing"]["ocr_seconds"])
        all_ids = {x["id"] for x in row["steps"]}
        base_ids = {x["id"] for x in base}
        small_ids = {x["id"] for x in base if x["view_id"] in chosen}
        item = {"id": sample["id"], "category": sample["category"], "filtered_input": sample["filtered_input"], "reference_review": sample["reference_review"], "original": original,
                "all_unfiltered": selected_summary(row, base_ids),
                "shortlist": selected_summary(row, small_ids),
                "all_observed": selected_summary(row, all_ids),
                "step_scores": row["scores"]}
        # Paired filter effects and their extra tokens over the complete unfiltered pool.
        item["filters"] = [{"id": x["id"], "view_id": x["view_id"], "filter": x["filter"], "score": row["scores"][x["id"]],
             "extra_tokens_beyond_unfiltered": len(row["matches"][x["id"]] - full_union),
             "coverage_delta_vs_same_view": row["scores"][x["id"]]["coverage"] - row["scores"][f"{(x['index']-1)//5*5+1:04d}"]["coverage"]}
            for x in row["steps"] if x["filter"] != "unchanged"]
        summaries.append(item)
        out = directory / "samples" / sample["id"]
        write_json(out / "analysis.json", item)
        for label in ("all_unfiltered", "shortlist", "all_observed"):
            (out / f"{label}.txt").write_text(item[label]["text"], encoding="utf-8")
    stats = []
    for item in by_step.values():
        item["mean_coverage"] = item.pop("coverage_sum") / item["images"]
        stats.append(item)
    output = {"version": VERSION, "assembly_version": ASSEMBLY_VERSION, "shortlist_view_ids": chosen, "greedy_selection": history, "samples": summaries, "transformations": sorted(stats, key=lambda x: (-x["mean_coverage"], x["ocr_work_seconds"]))}
    write_json(directory / "report.json", output)
    lines = ["# OCR screening — first development batch", "", "CPU / PP-OCRv6; 32 unfiltered full-image views, no tiles. Purposeful sample; no holdout evaluation.", "", "Reference normalization: production NFKC/casefold/token comparison; TextOCR uses word-region matching. Extra text is unassessed. Oracle token unions are diagnostics, not emitted OCR text.", "", "| Image | Source | Original | Final, 32 views | Final, shortlist | Final, with filters |", "|---|---|---:|---:|---:|---:|"]
    for item in summaries:
        values = [item["original"]["coverage"], *[item[k]["final"]["coverage"] for k in ("all_unfiltered", "shortlist", "all_observed")]]
        lines.append(f"| {item['id']} | {item['category']} | " + " | ".join(f"{v:.1%}" for v in values) + " |")
    lines += ["", "## Development shortlist", "", *[f"- `{v}`" for v in chosen], "", "This shortlist is selected against development references. It needs validation on unseen content groups. Removing views can change assembly votes and lose a reading even when oracle coverage is unchanged.", "", "## Unfiltered transformation comparison", "", "| View | Mean reference coverage | Complete images | Extra tokens vs original | Unique tokens | OCR work, seconds |", "|---|---:|---:|---:|---:|---:|"]
    for stat in output["transformations"]:
        if stat["filter"] == "unchanged":
            lines.append(f"| {stat['view_id']} | {stat['mean_coverage']:.1%} | {stat['complete_images']}/{stat['images']} | {stat['extra_tokens_vs_original']} | {stat['unique_tokens_among_base_views']} | {stat['ocr_work_seconds']:.2f} |")
    lines += ["", "OCR work is the sum of measured per-call wall times under concurrent execution, not end-to-end batch time. Fresh model initialization and PNG persistence are excluded from that column; stage status files record actual elapsed time.", "", "## Reference review", "", *[f"- {x['id']}: {x['reference_review']}" for x in summaries]]
    (directory / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report written: {directory / 'REPORT.md'}", flush=True)


def plan_filters(directory):
    manifest = check_manifest(directory)
    rows = load_samples(directory, manifest)
    chosen, history = greedy_views(rows, max_views=3)
    # Always test original plus two views: if gains saturate, use coverage/time.
    ranked = sorted({x["view_id"] for x in rows[0]["steps"] if x["filter"] == "unchanged"}, key=lambda view: (
        -sum(next(row["scores"][s["id"]]["coverage"] for s in row["steps"] if s["view_id"] == view and s["filter"] == "unchanged") for row in rows),
        sum(next(s["timing"]["ocr_seconds"] for s in row["steps"] if s["view_id"] == view and s["filter"] == "unchanged") for row in rows)))
    chosen += [v for v in ranked if v not in chosen][:3-len(chosen)]
    plan = {"view_ids": chosen, "filters": list(FILTERS[1:]), "reason": "original plus up to two incremental-coverage/time candidates on development only", "greedy_selection": history,
            "base_results_sha256": digest([[s for s in row["steps"] if s["filter"] == "unchanged"] for row in rows])}
    path = directory / "filter_plan.json"
    if path.exists() and read(path) != plan:
        raise ValueError("Filter plan already frozen; choose a new experiment for changes.")
    write_json(path, plan)
    print(json.dumps(plan, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "report", "plan-filters", "_image"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--stage", choices=("views", "filters", "candidate", "control", "diagnostics"), default="views")
    parser.add_argument("--id")
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepare(directory, args.ids, args.workers)
    elif args.command == "run":
        return run(directory, args.stage)
    elif args.command == "_image":
        return run_image(directory, args.id, args.stage)
    elif args.command == "report":
        report(directory)
    else:
        plan_filters(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
