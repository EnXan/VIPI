"""Round 3: frozen small profile, alternating fresh per-image comparisons."""

import argparse
import copy
import importlib.util
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageOps

from research.datasets.catalog import Catalog
from research.evaluation.metrics import compare, final_observations
from research.experiments.ocr import ocr_screening as screening
from vipi.ocr.merge import ASSEMBLY_VERSION, assemble
from vipi.ocr.models import sha256
from vipi.storage.ocr import write_json

ROOT = screening.ROOT
DEFAULT = ROOT / "runs/ocr-screening/2026-10-19-round-03"
STAGES = ("candidate", "control")
SEED = 2026101903
EXTRA_PASSES = [
    {"view_id": "original-unchanged-1x", "filter": "inverted"},
    {"view_id": "opencv-nearest-0.125x", "filter": "grayscale"},
]


def previous_runs():
    return [ROOT / f"runs/ocr-screening/2026-10-19-round-0{i}" for i in (1, 2)]


def select_ids():
    catalog = Catalog(ROOT)
    previous = [s for p in previous_runs() for s in screening.read(p / "manifest.json")["samples"]]
    old_ids = {s["id"] for s in previous}
    old_groups = {s["content_group_id"] for s in previous if s["category"] != "anamorpher"}
    rng = random.Random(SEED)
    selected = []
    for category, filtered in [
        ("textocr", False), ("textocr", False), ("textocr", True),
        ("cyberseceval3_visual_prompt_injection", False), ("mm_safetybench", False),
        ("typographic_visual_prompt_injection", True), ("vpi_bench", False),
    ]:
        pool = [x for x in catalog.items.values() if x["category"] == category
                and ("ocr_obfuscation" in x["image"]) == filtered
                and x["id"] not in old_ids
                and x["details"]["content_group_id"] not in old_groups
                and screening.split_for(x["details"]["content_group_id"]) == "development"
                and (category != "textocr" or 5 <= len(x["details"].get("regions", [])) <= 30)]
        chosen = rng.choice(sorted(pool, key=lambda x: x["id"]))
        selected.append(chosen["id"])
        old_groups.add(chosen["details"]["content_group_id"])
    # Generator configuration only; probe OCR scores/text are not selection criteria.
    records = screening.read(ROOT / "research/datasets/data/catalog/ocr/anamorpher_manifest.json")["records"]
    active = {x["image"]: x for x in catalog.items.values()}
    for method in ("bilinear", "bicubic", "nearest"):
        pool = [active[r["image"]] for r in records if r["image"] in active
                and active[r["image"]]["id"] not in old_ids
                and r["configuration"]["method"] == method
                and r["configuration"]["text_id"] == "blue"
                and r["source_dimensions"] == [3200, 3200]]
        selected.append(rng.choice(sorted(pool, key=lambda x: x["id"]))["id"])
    return selected


def prepare(directory):
    screening.prepare(directory, select_ids(), workers=4)
    manifest = screening.read(directory / "manifest.json")
    base = screening.read(previous_runs()[0] / "round2_candidate.json")["view_ids"]
    views = [*base, "rotate-90", "rotate-180"]
    all_views = [v.id for v in screening.views_for_size(1024, 768) if v.crop is None]
    manifest["profiles"] = {
        name: {"passes": [{"view_id": v, "filter": "unchanged"} for v in ids] + EXTRA_PASSES,
               **({"two_times_max_pixels": 8_000_000} if name == "candidate" else {})}
        for name, ids in (("candidate", views), ("control", all_views))
    }
    manifest["separate_stage_directories"] = True
    manifest["environment"] = {"KMP_USE_SHM": "0"}
    manifest["driver_sha256"] = sha256(Path(__file__))
    manifest["design"].update({
        "seed": SEED, "assembly_version": ASSEMBLY_VERSION,
        "selection": "seven unseen base groups, two filtered inputs, TextOCR 5-30 word regions; three unused 3200px blue Anamorpher variants",
        "selection_method": "seeded choice within fixed source/input strata, without looking at new OCR",
        "profiles": "ten base methods plus two targeted filters; 2x capped only in candidate; control has 32 methods plus same two filters",
        "execution_order": "paired per image; candidate first for even index, control first for odd index; fresh process per profile",
        "timing": "sum of complete fresh per-image child elapsed measurements; OS activity and warm file caches remain",
        "reference_review": "review notes and exclusions saved before first inference; source text unchanged",
    })
    manifest["protocol_sha256"] = screening.protocol_fingerprint(manifest)
    write_json(directory / "manifest.json", manifest)
    snapshot = directory / "source_snapshot"
    for name, expected in manifest["source_hashes"].items():
        source = ROOT / name
        if sha256(source) != expected:
            raise ValueError("Source changed during preparation.")
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = snapshot / "research/experiments/ocr/ocr_round3.py"
    shutil.copyfile(Path(__file__), target)
    # A frozen executable copy keeps concurrent project refactoring out of inference.
    frozen = directory / "frozen_runtime"
    shutil.copytree(snapshot, frozen)
    for name in ("src/vipi/__init__.py", "src/vipi/ocr/__init__.py", "src/vipi/storage/__init__.py",
                 "research/__init__.py", "research/evaluation/__init__.py", "research/experiments/__init__.py"):
        (frozen / name).write_text('"""Frozen experiment package."""\n')
    for name in ("datasets", "models", "runs"):
        (frozen / name).symlink_to(ROOT / name, target_is_directory=True)
    canvas = Image.new("RGB", (1400, 2550), "#eeeeee")
    draw = ImageDraw.Draw(canvas)
    for i, sample in enumerate(manifest["samples"]):
        path = sample["declared_downscale"]["image"] if sample["category"] == "anamorpher" else sample["image"]
        with Image.open(ROOT / path) as source:
            tile = ImageOps.contain(source.convert("RGB"), (680, 450))
        x, y = i % 2 * 700, i // 2 * 510
        canvas.paste(tile, (x + (700-tile.width)//2, y+35))
        draw.text((x+10, y+5), sample["id"] + " " + sample["category"], fill="black")
    canvas.save(directory / "selection-contact-sheet.jpg")
    print(f"Prepared {directory}; inspect references and freeze review before running.")


def result(reference, steps, assembler=assemble):
    text, regions = assembler(steps)
    observations = regions if reference["reading_order_known"] else final_observations(regions, steps)
    score, expected, matched = compare(reference, text, observations)
    pool = set().union(*(compare(reference, s["text"], s["regions"])[2] for s in steps))
    return {"text": text, "score": score, "pool_positions": sorted(pool),
            "final_positions": sorted(matched), "expected": expected}


def replay(directory):
    old_path = previous_runs()[1] / "source_snapshot/src/ocr_pipeline/merge.py"
    spec = importlib.util.spec_from_file_location("round2_assembly_snapshot", old_path)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    rows = []
    views = {p["view_id"] for p in screening.read(directory / "manifest.json")["profiles"]["candidate"]["passes"] if p["filter"] == "unchanged"}
    for previous in previous_runs():
        manifest = screening.read(previous / "manifest.json")
        for sample in manifest["samples"]:
            folder = previous / "samples" / sample["id"]
            folders = [folder / "control", folder / "diagnostics"] if manifest.get("separate_stage_directories") else [folder]
            steps = [screening.read(p) for f in folders for p in sorted((f / "steps").glob("*.json"))]
            control = [s for s in steps if s["filter"] == "unchanged" or {"view_id": s["view_id"], "filter": s["filter"]} in EXTRA_PASSES]
            candidate = [s for s in control if (s["filter"] != "unchanged" or s["view_id"] in views)
                         and not (s["transformation"]["factor"] == 2 and s["width"]*s["height"] > 8_000_000)]
            scores = {name: {"v3": result(sample["reference"], selected, legacy.assemble),
                             "v4": result(sample["reference"], selected)}
                      for name, selected in (("candidate", candidate), ("control", control))}
            rows.append({"round": previous.name, "id": sample["id"], "category": sample["category"], "profiles": scores})
    write_json(directory / "assembly_replay.json", {"samples": rows, "old_version": 3, "new_version": ASSEMBLY_VERSION,
                                                   "ocr_rerun": False, "selection": "current profiles on previously saved control/filter observations"})


def run(directory):
    manifest = screening.check_manifest(directory)
    if sha256(Path(__file__)) != manifest["driver_sha256"]:
        raise ValueError("Driver source changed.")
    review = screening.read(directory / "reference_audit.json")
    exclusions_path = directory / "reference_exclusions.json"
    exclusions_hash = sha256(exclusions_path)
    review_hash = sha256(directory / "reference_audit.json")
    if set(review) != {s["id"] for s in manifest["samples"]}:
        raise ValueError("Review every selected reference before running.")
    timing_path = directory / "measurements.json"
    saved = screening.read(timing_path) if timing_path.exists() else {"measurements": [], "review_sha256": review_hash, "exclusions_sha256": exclusions_hash}
    if (saved["review_sha256"], saved["exclusions_sha256"]) != (review_hash, exclusions_hash):
        raise ValueError("Reference review changed after first inference.")
    write_json(timing_path, saved)
    for i, sample in enumerate(manifest["samples"]):
        for stage in STAGES if i % 2 == 0 else tuple(reversed(STAGES)):
            if any(x["sample_id"] == sample["id"] and x["stage"] == stage and x["exit_code"] == 0 for x in saved["measurements"]):
                continue
            folder = directory / "samples" / sample["id"] / stage / "steps"
            if folder.exists() and list(folder.glob("*.json")):
                raise ValueError("Partial image requires a separate timing audit; do not label it fresh.")
            print(f"IMAGE {i+1}/10 {sample['id']} {stage}", flush=True)
            command = [sys.executable, str(ROOT / "research/experiments/ocr/ocr_screening.py"), "_image", str(directory), "--id", sample["id"], "--stage", stage]
            started = time.perf_counter()
            child = subprocess.Popen(command, cwd=ROOT, env={**os.environ, **manifest["environment"]})
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
            saved["measurements"].append({"sample_id": sample["id"], "stage": stage, "exit_code": child.returncode,
                                          "elapsed_seconds": time.perf_counter()-started, "user_cpu_seconds": usage.ru_utime,
                                          "system_cpu_seconds": usage.ru_stime,
                                          "peak_resident_bytes": usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)})
            write_json(timing_path, saved)
            if child.returncode:
                raise RuntimeError("Child failed; successful observations and measurements retained.")
    replay(directory)
    report(directory)


def report(directory):
    manifest = screening.check_manifest(directory)
    measurements = screening.read(directory / "measurements.json")
    if measurements["review_sha256"] != sha256(directory / "reference_audit.json") or measurements["exclusions_sha256"] != sha256(directory / "reference_exclusions.json"):
        raise ValueError("Reference review changed.")
    exclusions = screening.read(directory / "reference_exclusions.json")
    rows = []
    for sample in manifest["samples"]:
        steps = {}
        for stage in STAGES:
            folder = directory / "samples" / sample["id"] / stage / "steps"
            steps[stage] = [screening.read(p) for p in sorted(folder.glob("*.json"))]
            expected = {f"{n:04d}" for n, _, _ in screening.schedule(sample, stage, directory)}
            if {s["id"] for s in steps[stage]} != expected:
                raise ValueError("Incomplete observations.")
            timings = [x for x in measurements["measurements"] if x["sample_id"] == sample["id"] and x["stage"] == stage and x["exit_code"] == 0]
            if len(timings) != 1:
                raise ValueError("Missing or duplicate complete measurement.")
        by_id = {s["id"]: s for s in steps["control"]}
        if any(s["raster_sha256"] != by_id[s["id"]]["raster_sha256"] for s in steps["candidate"]):
            raise ValueError("Shared inputs differ between fresh profiles.")
        scopes = {}
        for scope in ("source", "reviewed_subset"):
            ref = copy.deepcopy(sample["reference"])
            if scope == "reviewed_subset" and sample["id"] in exclusions:
                if ref["reading_order_known"]:
                    raise ValueError("Exclusions require spatial word annotations.")
                ref["regions"] = [r for r in ref["regions"] if r["text"] not in exclusions[sample["id"]]]
            scores = {stage: result(ref, values) for stage, values in steps.items()}
            lost = set(scores["control"]["pool_positions"]) - set(scores["candidate"]["pool_positions"])
            scopes[scope] = {**scores, "lost_pool_tokens": [scores["control"]["expected"][i] for i in sorted(lost)]}
        rows.append({"id": sample["id"], "category": sample["category"], "scopes": scopes,
                     "passes": {k: len(v) for k, v in steps.items()}})
    summary = {stage: {"elapsed_seconds": sum(x["elapsed_seconds"] for x in measurements["measurements"] if x["stage"] == stage),
                       "peak_resident_bytes": max(x["peak_resident_bytes"] for x in measurements["measurements"] if x["stage"] == stage),
                       "passes": sum(r["passes"][stage] for r in rows)} for stage in STAGES}
    write_json(directory / "analysis.json", {"assembly_version": ASSEMBLY_VERSION, "manifest_sha256": sha256(directory / "manifest.json"),
                                             "report_source_sha256": sha256(Path(__file__)), "samples": rows, "summary": summary})
    lines = ["# OCR Runde 3", "", "Zehn neue Entwicklungsbilder; sieben neue Basisgruppen und drei Varianten derselben blauen Anamorpher-Payload. Kein Holdout. Zusammenführung Version 4. Beide Profile frisch, Ausführungsreihenfolge je Bild abwechselnd.", "",
             "| Profil | Aufrufe | Laufzeit | Maximaler Prozess-RSS |", "|---|---:|---:|---:|"]
    for stage, values in summary.items():
        lines.append(f"| {stage} | {values['passes']} | {values['elapsed_seconds']:.1f} s | {values['peak_resident_bytes']/1024**3:.2f} GiB |")
    for scope in ("source", "reviewed_subset"):
        lines += ["", f"## {scope}", "", "| Bild | Quelle | Kandidat | Kontrolle | Verlorene Pool-Tokens |", "|---|---|---:|---:|---|"]
        for row in rows:
            s = row["scopes"][scope]
            cells = [f"{s[k]['score']['matched']}/{s[k]['score']['total']} ({s[k]['score']['coverage']:.1%})" for k in STAGES]
            lines.append(f"| {row['id']} | {row['category']} | " + " | ".join(cells) + " | " + ", ".join(s["lost_pool_tokens"]) + " |")
    lines += ["", "Kandidat: acht bisherige Methoden + 90°/180°, 2× höchstens 8 MP, dazu Original invertiert und OpenCV Nearest 1/8 mit Graustufen. Kontrolle: 32 Methoden plus dieselben zwei Filter. Keine Kacheln.", "",
              "Laufzeit: Summe vollständiger frischer Bildprozesse einschließlich Modellstart/Transformation/Speicherung; finale Zusammenführung separat. RSS nur des jeweiligen OCR-Prozesses. Normale OS-Aktivität und Dateicaches bleiben. Abdeckung misst exakte Referenztokens mit Satzzeichen, räumlich für TextOCR; keine Präzision oder vollständige Gold-Zertifizierung. Teilreferenz-Ausschlüsse wurden vor der OCR dokumentiert."]
    (directory / "ERGEBNISSE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(directory / "ERGEBNISSE.md", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "report", "replay"))
    parser.add_argument("directory", type=Path, nargs="?", default=DEFAULT)
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "report": report, "replay": replay}[args.command](args.directory.resolve())
