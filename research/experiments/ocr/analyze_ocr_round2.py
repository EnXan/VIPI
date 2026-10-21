"""Offline round-2 audit using the frozen assembly and evaluation snapshots.

No inference or changes to catalog references. The rotation extension is a
post-hoc development diagnostic, not a freshly timed or held-out profile.
"""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[3]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_modules(directory, manifest):
    package = "_round2_frozen_audit"
    module = types.ModuleType(package)
    module.__path__ = []
    sys.modules[package] = module
    loaded = []
    for name in ("merge", "evaluation"):
        relative = f"src/ocr_pipeline/{name}.py"
        path = directory / "source_snapshot" / relative
        if sha256(path) != manifest["source_hashes"][relative]:
            raise ValueError(f"Snapshot changed: {relative}")
        spec = importlib.util.spec_from_file_location(f"{package}.{name}", path)
        item = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = item
        spec.loader.exec_module(item)
        loaded.append(item)
    return loaded


def reviewed_reference(reference, excluded):
    result = copy.deepcopy(reference)
    if excluded:
        if result["reading_order_known"]:
            raise ValueError("Review exclusions require annotated word regions.")
        removed = {r["text"] for r in result["regions"] if r["text"] in excluded}
        if removed != set(excluded):
            raise ValueError("Predeclared exclusions do not match source regions.")
        result["regions"] = [r for r in result["regions"] if r["text"] not in excluded]
    return result


def audit(directory):
    manifest = read(directory / "manifest.json")
    merge, evaluation = frozen_modules(directory, manifest)
    exclusions = read(directory / "reference_exclusions.json")
    for stage in ("candidate", "control", "diagnostics"):
        if read(directory / f"{stage}_status.json")["state"] != "completed":
            raise ValueError(f"Stage incomplete: {stage}")

    def summary(reference, steps):
        text, regions = merge.assemble(steps)
        observations = regions if reference["reading_order_known"] else evaluation.final_observations(regions, steps)
        final, expected, matched = evaluation.compare(reference, text, observations)
        pool = set().union(*(evaluation.compare(reference, s["text"], s["regions"])[2] for s in steps))
        return {"final": final, "pool_matched": len(pool), "pool_total": len(expected),
                "pool_positions": sorted(pool), "final_positions": sorted(matched), "text": text}

    rows = []
    for sample in manifest["samples"]:
        stages = {stage: [read(p) for p in sorted((directory / "samples" / sample["id"] / stage / "steps").glob("*.json"))]
                  for stage in ("candidate", "control", "diagnostics")}
        for stage, steps in stages.items():
            status = read(directory / "samples" / sample["id"] / stage / f"{stage}_status.json")
            if status["state"] != "completed" or len(steps) != status["planned"]:
                raise ValueError(f"Incomplete sample: {sample['id']} / {stage}")
        rotations = [s for s in stages["control"] if s["view_id"] in {"rotate-90", "rotate-180"}]
        bilinear = [s for s in stages["control"] if s["view_id"] == "opencv-bilinear-0.25x"]
        profiles = {"candidate": stages["candidate"], "control": stages["control"],
                    "candidate_plus_rotations": sorted(stages["candidate"] + rotations, key=lambda s: s["index"]),
                    "candidate_plus_rotations_and_bilinear": sorted(stages["candidate"] + rotations + bilinear, key=lambda s: s["index"]),
                    "candidate_plus_diagnostics": sorted(stages["candidate"] + stages["diagnostics"], key=lambda s: s["index"])}
        row = {"id": sample["id"], "category": sample["category"],
               "excluded_region_labels": exclusions.get(sample["id"], []), "scores": {}}
        for scope, reference in (("source", sample["reference"]),
                                 ("reviewed_subset", reviewed_reference(sample["reference"], row["excluded_region_labels"]))):
            scores = {name: summary(reference, steps) for name, steps in profiles.items()}
            _, expected, _ = evaluation.compare(reference, stages["control"][0]["text"], stages["control"][0]["regions"])
            for name, score in scores.items():
                lost = set(scores["control"]["pool_positions"]) - set(score["pool_positions"])
                score["lost_pool_tokens_vs_control"] = [expected[i] for i in sorted(lost)]
            scores["best_single"] = max((evaluation.compare(reference, s["text"], s["regions"])[0] for s in stages["control"]), key=lambda s: s["matched"])
            scores["diagnostics"] = []
            for step in stages["diagnostics"]:
                baseline = next(s for s in stages["control"] if s["view_id"] == step["view_id"])
                current, _, matched = evaluation.compare(reference, step["text"], step["regions"])
                before = evaluation.compare(reference, baseline["text"], baseline["regions"])[0]
                added = matched - set(scores["control"]["pool_positions"])
                scores["diagnostics"].append({"view_id": step["view_id"], "filter": step["filter"],
                                              "matched": current["matched"], "baseline_matched": before["matched"],
                                              "new_tokens_vs_full_control_pool": [expected[i] for i in sorted(added)]})
            row["scores"][scope] = scores
        rows.append(row)
    output = {"manifest_sha256": sha256(directory / "manifest.json"),
              "exclusions_sha256": sha256(directory / "reference_exclusions.json"),
              "audit_source_sha256": sha256(Path(__file__)), "samples": rows,
              "limitations": ["Exclusions were declared before inference. Remaining source labels are not globally Gold.",
                              "Rotation/bilinear extensions are chosen after inspecting round 2; observations reused, no fresh runtime measurement.",
                              "Coverage is exact source-token recall; extra OCR output is not penalized. No precision claim."]}
    (directory / "supplement.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    lines = ["# Ergänzende Prüfung: Referenzen und Rotationen", "",
             "Die räumlichen Wortregionen mit vorab dokumentierten unsicheren Quelllabels werden ausschließlich für eine zweite Auswertung ausgeschlossen. Katalog, Transkript und OCR bleiben unverändert. Dies ist keine vollständige Gold-Annotation.", "",
             "| Bild | Quell-Tokens | Teilmenge | 32 Ansichten | Kandidat | + 90°/180° | + Rotationen/Bilinear 1/4 | + Filter |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        scores = row["scores"]["reviewed_subset"]
        totals = (row["scores"]["source"]["control"]["final"]["total"], scores["control"]["final"]["total"])
        cells = [f"{scores[name]['final']['matched']}/{scores[name]['final']['total']} ({scores[name]['final']['coverage']:.1%})"
                 for name in ("control", "candidate", "candidate_plus_rotations", "candidate_plus_rotations_and_bilinear", "candidate_plus_diagnostics")]
        lines.append(f"| {row['id']} | {totals[0]} | {totals[1]} | " + " | ".join(cells) + " |")
    lines += ["", "Die zusätzlichen Rotationen und OpenCV Bilinear 1/4 wurden nach Sichtung der zweiten Runde gewählt und aus gespeicherten Kontrollbeobachtungen ergänzt. Ihr Ergebnis ist eine Entwicklungsdiagnose; Laufzeit und Generalisierung dieser erweiterten Profile sind nicht frisch gemessen.", "",
              "`supplement.json` enthält zusätzlich die unveränderte Quellauswertung, vollständige Verluste im Beobachtungspool, beste Einzelansicht und gepaarte Filterdiagnosen. Pool-Abdeckung ist keine Garantie für den ausgegebenen Text. Die Metrik bestraft zusätzlichen OCR-Text nicht und misst keine Präzision."]
    (directory / "ERGÄNZUNG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(directory / "ERGÄNZUNG.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=ROOT / "runs/ocr-screening/2026-10-19-round-02")
    audit(parser.parse_args().directory.resolve())
