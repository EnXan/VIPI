"""Frozen second development batch: fresh small-profile and full-view comparison."""

import argparse
import csv
import importlib.util
from pathlib import Path
import time

from PIL import Image, ImageDraw, ImageOps

from research.datasets.catalog import Catalog
from research.evaluation.metrics import compare, final_observations, EVALUATION_VERSION
from vipi.ocr.merge import assemble, ASSEMBLY_VERSION
from vipi.ocr.models import sha256
from vipi.storage.ocr import write_json
from research.experiments.ocr import ocr_screening as screening
ROOT = screening.ROOT
FIRST = ROOT / "runs/ocr-screening/2026-10-19-round-01"
SECOND = ROOT / "runs/ocr-screening/2026-10-19-round-02"
BASE_IDS = [
    "19976af64305f3f7", "e1d0ef54e2c292e8", "bfa845dd785b0e32",
    "506a9aff70c1e56b", "35d3c43945db08f2", "b866376a2050a2ee",
    "8fcf413fa6a2530f",
]
ANAMORPHER_IDS = ["anamorpher_0188", "anamorpher_0492", "anamorpher_1364"]
STAGES = ("candidate", "control", "diagnostics")


def prepare(directory):
    catalog = Catalog(ROOT)
    first = screening.read(FIRST / "manifest.json")
    previous_groups = {x["content_group_id"] for x in first["samples"]}
    ids = [*BASE_IDS, *[
        next(x["id"] for x in catalog.items.values() if x["details"].get("sample_id") == name)
        for name in ANAMORPHER_IDS
    ]]
    for identifier in BASE_IDS:
        if catalog.get(identifier)["details"]["content_group_id"] in previous_groups:
            raise ValueError("Base content group was used in round 1.")
    if {x["id"] for x in first["samples"]}.intersection(ids):
        raise ValueError("Image repeated from round 1.")
    screening.prepare(directory, ids, workers=4)
    manifest = screening.read(directory / "manifest.json")
    candidate = screening.read(FIRST / "round2_candidate.json")
    manifest["profiles"] = {
        "candidate": {"view_ids": candidate["view_ids"], "filters": ["unchanged"], "two_times_max_pixels": 8_000_000},
        "control": {"view_ids": None, "filters": ["unchanged"]},
        "diagnostics": {"passes": [
            {"view_id": "original-unchanged-1x", "filter": "grayscale"},
            {"view_id": "original-unchanged-1x", "filter": "inverted"},
            {"view_id": "opencv-nearest-0.125x", "filter": "grayscale"},
        ]},
    }
    manifest["separate_stage_directories"] = True
    manifest["design"].update({
        "selection": "seven new base-source development groups and three unused blue-payload Anamorpher variants",
        "seed": 2026101902,
        "selection_method": "source/filtered strata; manual frozen IDs from seeded candidate inspection, before new OCR",
        "base_filtered_inputs": 2,
        "anamorpher": "different alignment, 64px text, dither profile, including nearest offset 2; blue group reused for generator coverage only",
        "views": "fresh candidate and fresh 32-view control in separate directories; no OCR reuse between stages",
        "stages": list(STAGES),
        "reference_review": "separate reference_audit.json; source transcripts unchanged",
        "old_round_assembly": 2, "new_assembly": ASSEMBLY_VERSION,
        "evaluation_version": EVALUATION_VERSION,
    })
    manifest["selection_basis"] = {
        "round1_manifest_sha256": sha256(FIRST / "manifest.json"),
        "candidate_sha256": sha256(FIRST / "round2_candidate.json"),
    }
    manifest["protocol_sha256"] = screening.protocol_fingerprint(manifest)
    write_json(directory / "manifest.json", manifest)
    snapshot = directory / "source_snapshot"
    for name, expected in manifest["source_hashes"].items():
        source = ROOT / name
        if sha256(source) != expected:
            raise ValueError("Code changed during preparation.")
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    canvas = Image.new("RGB", (1400, 2550), "#eeeeee")
    draw = ImageDraw.Draw(canvas)
    for i, sample in enumerate(manifest["samples"]):
        path = sample["declared_downscale"]["image"] if sample["category"] == "anamorpher" else sample["image"]
        with Image.open(ROOT / path) as source:
            tile = ImageOps.contain(source.convert("RGB"), (680, 450))
        col, row = i % 2, i // 2
        canvas.paste(tile, (col*700+(700-tile.width)//2, row*510+35))
        draw.text((col*700+10, row*510+5), sample["id"]+" "+sample["category"], fill="black")
        draw.text((col*700+10, row*510+485), "Declared downscale control" if sample["category"] == "anamorpher" else "Active catalog input", fill="black")
    canvas.save(directory / "selection-contact-sheet.jpg")
    print("Frozen round 2; review references before running.", flush=True)


def final_score(reference, steps, assembler=assemble):
    started = time.perf_counter()
    text, regions = assembler(steps)
    seconds = time.perf_counter()-started
    observations = regions if reference["reading_order_known"] else final_observations(regions, steps)
    result = compare(reference, text, observations)[0]
    return {"score": result, "text": text, "assembly_seconds": seconds}


def replay_round1(directory):
    """Replay only; do not alter any original round-1 reports or observations."""
    first = screening.read(FIRST / "manifest.json")
    spec = importlib.util.spec_from_file_location("assembly_v2_snapshot", FIRST / "source_snapshot/src/ocr_pipeline/merge.py")
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    rows = screening.load_samples(FIRST, first)
    keep = set(screening.read(FIRST / "round2_candidate.json")["view_ids"])
    results = []
    for row in rows:
        item = {"id": row["sample"]["id"], "category": row["sample"]["category"]}
        for label in ("control", "candidate"):
            steps = [s for s in row["steps"] if s["filter"] == "unchanged" and (
                label == "control" or s["view_id"] in keep and not (
                    s["transformation"]["factor"] == 2 and s["width"]*s["height"] > 8_000_000))]
            item[label] = {"old": final_score(row["sample"]["reference"], steps, legacy.assemble),
                           "new": final_score(row["sample"]["reference"], steps)}
        results.append(item)
    write_json(directory / "round1_assembly_replay.json", {
        "old_version": 2, "new_version": ASSEMBLY_VERSION,
        "evaluation_version_used_for_both": EVALUATION_VERSION,
        "ocr_rerun": False, "samples": results,
    })


def report(directory):
    manifest = screening.check_manifest(directory)
    stages = {name: screening.read(directory / f"{name}_status.json") for name in STAGES}
    if any(s["state"] != "completed" for s in stages.values()):
        raise ValueError("All stages must complete before final reporting.")
    audit = screening.read(directory / "reference_audit.json")
    results, step_rows = [], []
    for sample in manifest["samples"]:
        reference = sample["reference"]
        steps = {}
        for stage in STAGES:
            folder = directory / "samples" / sample["id"] / stage
            observed = [screening.read(p) for p in sorted((folder / "steps").glob("*.json"))]
            expected = {f"{n:04d}" for n, _, _ in screening.schedule(sample, stage, directory)}
            if {s["id"] for s in observed} != expected:
                raise ValueError(f"Incomplete {stage}: {sample['id']}")
            steps[stage] = observed
            for step in observed:
                score = compare(reference, step["text"], step["regions"])[0]
                step_rows.append({"sample_id": sample["id"], "category": sample["category"], "stage": stage,
                                  "view_id": step["view_id"], "filter": step["filter"], "coverage": score["coverage"],
                                  "matched": score["matched"], "total": score["total"], **step["timing"]})
        control_by_id = {s["id"]: s for s in steps["control"]}
        for step in steps["candidate"]:
            if step["raster_sha256"] != control_by_id[step["id"]]["raster_sha256"]:
                raise ValueError("Shared view rasters differ between fresh stages.")
        coverage_sets = {}
        for stage in ("candidate", "control"):
            coverage_sets[stage] = set().union(*(compare(reference, s["text"], s["regions"])[2] for s in steps[stage]))
        _, expected, _ = compare(reference, steps["control"][0]["text"], steps["control"][0]["regions"])
        lost = coverage_sets["control"]-coverage_sets["candidate"]
        timings = {stage: next(x for x in stages[stage]["outcomes"] if x["sample_id"] == sample["id"]) for stage in STAGES}
        item = {"id": sample["id"], "category": sample["category"], "review": audit[sample["id"]],
                "original": compare(reference, steps["control"][0]["text"], steps["control"][0]["regions"])[0],
                "candidate": final_score(reference, steps["candidate"]),
                "control": final_score(reference, steps["control"]),
                "candidate_with_diagnostics": final_score(reference, sorted(steps["candidate"]+steps["diagnostics"], key=lambda s:s["index"])),
                "passes": {k: len(v) for k,v in steps.items()}, "timings": timings,
                "reference_positions_lost_from_pool": sorted(lost),
                "tokens_lost_from_pool": [expected[i] for i in sorted(lost)],
                "candidate_pool_coverage": len(coverage_sets["candidate"])/max(1,len(expected)),
                "control_pool_coverage": len(coverage_sets["control"])/max(1,len(expected))}
        results.append(item)
        for name in ("candidate", "control", "candidate_with_diagnostics"):
            (directory / "samples" / sample["id"] / f"{name}.txt").write_text(item[name]["text"], encoding="utf-8")
    with (directory / "per_step.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(step_rows[0]))
        writer.writeheader()
        writer.writerows(step_rows)
    output = {"assembly_version": ASSEMBLY_VERSION, "evaluation_version": EVALUATION_VERSION,
              "manifest_sha256": sha256(directory / "manifest.json"), "report_source_sha256": sha256(Path(__file__)),
              "samples": results, "stages": stages,
              "limitations": ["Seven new base groups, three new Anamorpher variants of the same development payload.",
                              "Purposeful small development batch; no holdout evaluation or threshold calibration.",
                              "Both profiles freshly inferred in separate processes. Candidate stage precedes control; no random execution order.",
                              "CPU screening with normal OS activity and warm file caches, not an isolated hardware benchmark.",
                              "Original annotations unchanged; unverified/ambiguous words remain limitations."]}
    write_json(directory / "analysis.json", output)
    lines = ["# OCR: Runde 2", "", "Zehn neue Bilder: sieben neue Basis-Inhaltsgruppen und drei neue Varianten derselben blauen Anamorpher-Payload. Kein Holdout verwendet. PP-OCRv6, CPU, vier Worker, je zwei ONNX-Threads; maximal 12 MP gleichzeitig, größere Ansichten allein.", "", f"Zusammenführung Version {ASSEMBLY_VERSION}, Auswertung Version {EVALUATION_VERSION}. Kandidat und Kontrolle wurden unabhängig frisch berechnet. Die erste Runde bleibt unverändert archiviert.", "", "## Abdeckung", "", "| Bild | Quelle | Original | 32 Ansichten | Kandidat | Kandidat + Zusatzfilter | Verlorene Tokens im Beobachtungspool |", "|---|---|---:|---:|---:|---:|---|"]
    for item in results:
        values = [item["original"]["coverage"], *[item[k]["score"]["coverage"] for k in ("control", "candidate", "candidate_with_diagnostics")]]
        lines.append(f"| {item['id']} | {item['category']} | "+" | ".join(f"{v:.1%}" for v in values)+" | "+", ".join(item["tokens_lost_from_pool"])+" |")
    lines += ["", "Abdeckung zählt exakte Referenztokens einschließlich Satzzeichen nach der vorhandenen Normalisierung. TextOCR wird räumlich bewertet. Die Originalspalte bewertet rohe OCR, die übrigen Spalten den tatsächlich zusammengesetzten Text. Die Treffermenge aller Ansichten ist nur eine diagnostische Obergrenze.", "", "## Gemessene Laufzeit und Ressourcen", "", "| Profil | OCR-Aufrufe | Laufzeit gesamt | Maximaler Prozess-RSS |", "|---|---:|---:|---:|"]
    for stage in STAGES:
        status = stages[stage]
        count = sum(item["passes"][stage] for item in results)
        peak = max(x.get("peak_resident_bytes",0) for x in status["outcomes"])/1024**3
        lines.append(f"| {stage} | {count} | {status['elapsed_seconds']:.1f} s | {peak:.2f} GiB |")
    lines += ["", "Die Profile liefen nacheinander: Kandidat, Kontrolle, Zusatzfilter. Modellstart, Transformationen und Speicherung sind enthalten; finale Zusammenführung ist separat im JSON zeitlich erfasst. RSS ist der Spitzenwert des jeweiligen OCR-Prozesses einschließlich Worker-Threads, kein systemweiter Speicherverbrauch. Wiederaufgenommene Teilläufe sind für Laufzeitvergleiche gesondert zu prüfen.", "", "## Referenzprüfung", ""]
    lines += [f"- {x['id']}: {x['review']}" for x in results]
    lines += ["", "## Dateien", "", "- `analysis.json`: Einzelmetriken, Zeiten, Speicher, verlorene Referenztokens.", "- `per_step.csv`: alle Einzelansichten und Filter.", "- `round1_assembly_replay.json`: alte/neue Zusammenführung auf gespeicherten OCR-Beobachtungen, mit derselben neuen Auswertung für beide.", "- `samples/<id>/<stage>/`: tatsächliche Raster und Roh-OCR je unabhängigem Profil.", "", "Die Standard-CLI/Web-Pipeline verwendet weiterhin ihren bisherigen Transformationsumfang. Das kleinere Profil wird hier als Entwicklungskandidat geprüft. Die räumliche Zusammenführung, native Wortzuordnung und Behandlung identischer Raster wurden im gemeinsamen Code korrigiert."]
    (directory / "ERGEBNISSE.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(f"Report: {directory / 'ERGEBNISSE.md'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "report", "replay"))
    parser.add_argument("directory", type=Path, nargs="?", default=SECOND)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepare(directory)
    elif args.command == "run":
        for stage in STAGES:
            if screening.run(directory, stage):
                raise RuntimeError(f"Stage {stage} failed; successful observations retained.")
        replay_round1(directory)
        report(directory)
    elif args.command == "replay":
        replay_round1(directory)
    else:
        report(directory)


if __name__ == "__main__":
    main()
