"""Offline diagnosis of the cheap 1/8 view on the three development batches.

Run with the round-3 frozen runtime on PYTHONPATH to use the measured assembly.
The extension is selected after round 3; its timing is not freshly measured.
"""

import argparse
import importlib.util
from pathlib import Path

from research.experiments.ocr import ocr_screening as screening
from research.experiments.ocr.ocr_round3 import DEFAULT, ROOT, result
from vipi.ocr.merge import ASSEMBLY_VERSION
from vipi.ocr.models import sha256
from vipi.storage.ocr import write_json


def analyze(directory):
    manifest = screening.check_manifest(directory)
    if not (directory / "analysis.json").is_file():
        raise ValueError("Complete the fresh comparison before post-hoc extension.")
    old_root = ROOT / "runs/ocr-screening/2026-10-19-round-02"
    relative = "src/ocr_pipeline/merge.py"
    old_path = old_root / "source_snapshot" / relative
    if sha256(old_path) != screening.read(old_root / "manifest.json")["source_hashes"][relative]:
        raise ValueError("Legacy assembly snapshot changed.")
    spec = importlib.util.spec_from_file_location("assembly_v3_audit", old_path)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    changes = []
    for sample in manifest["samples"]:
        for stage in ("candidate", "control"):
            steps = [screening.read(p) for p in sorted((directory / "samples" / sample["id"] / stage / "steps").glob("*.json"))]
            before = result(sample["reference"], steps, legacy.assemble)
            after = result(sample["reference"], steps)
            changes.append({"id": sample["id"], "stage": stage, "before": before, "after": after})
    write_json(directory / "assembly_change_on_round3.json", {
        "old_version": 3, "new_version": ASSEMBLY_VERSION, "legacy_source_sha256": sha256(old_path),
        "samples": changes, "ocr_rerun": False,
    })
    passes = {(p["view_id"], p["filter"]) for p in manifest["profiles"]["candidate"]["passes"]}
    extra = ("pillow-nearest-0.125x", "unchanged")
    rows = []
    for number in (1, 2, 3):
        previous = ROOT / f"runs/ocr-screening/2026-10-19-round-0{number}"
        prior_manifest = screening.read(previous / "manifest.json")
        for sample in prior_manifest["samples"]:
            folder = previous / "samples" / sample["id"]
            folders = [folder / "control"] if number == 3 else (
                [folder / "control", folder / "diagnostics"] if number == 2 else [folder])
            observed = [screening.read(p) for f in folders for p in sorted((f / "steps").glob("*.json"))]
            control = [s for s in observed if s["filter"] == "unchanged" or (s["view_id"], s["filter"]) in passes]
            current = [s for s in control if (s["view_id"], s["filter"]) in passes
                       and not (s["transformation"]["factor"] == 2 and s["width"]*s["height"] > 8_000_000)]
            added = [s for s in control if (s["view_id"], s["filter"]) == extra]
            if len(added) != 1:
                raise ValueError("Missing or duplicate 1/8 view.")
            scores = {key: result(sample["reference"], selected) for key, selected in (
                ("candidate", current), ("candidate_plus_eighth", sorted(current + added, key=lambda s: s["index"])), ("control", control))}
            for score in scores.values():
                lost = set(scores["control"]["pool_positions"]) - set(score["pool_positions"])
                score["lost_pool_tokens"] = [scores["control"]["expected"][i] for i in sorted(lost)]
            rows.append({"round": number, "id": sample["id"], "profiles": scores,
                         "extra_ocr_work_seconds": added[0]["timing"]["ocr_seconds"]})
    next_profile = manifest["profiles"]["candidate"].copy()
    next_profile["passes"] = [*next_profile["passes"], {"view_id": extra[0], "filter": extra[1]}]
    write_json(directory / "posthoc_eighth.json", {"assembly_version": ASSEMBLY_VERSION,
                                                  "source_sha256": sha256(Path(__file__)), "samples": rows,
                                                  "next_profile": next_profile,
                                                  "limitations": "Post-hoc development replay; no new OCR, fresh timing or holdout validation."})
    lines = ["# Nachträgliche Prüfung: Pillow Nearest 1/8", "",
             "Diese Ansicht wurde nach Sichtung von Runde 3 ergänzt. Alle Werte sind Replays gespeicherter Beobachtungen; keine neue OCR oder frische Laufzeitmessung. Gleiche blaue Anamorpher-Payload in allen drei Runden.", "",
             "| Runde | Bild | Kandidat | + Nearest 1/8 | Kontrolle | Pool-Verlust nach Ergänzung |", "|---|---|---:|---:|---:|---|"]
    for row in rows:
        scores = row["profiles"]
        if row["round"] == 3 or scores["candidate"]["score"] != scores["candidate_plus_eighth"]["score"]:
            cells = [f"{scores[k]['score']['matched']}/{scores[k]['score']['total']}" for k in ("candidate", "candidate_plus_eighth", "control")]
            lines.append(f"| {row['round']} | {row['id']} | " + " | ".join(cells) + " | " + ", ".join(scores["candidate_plus_eighth"]["lost_pool_tokens"]) + " |")
    regressions = [row["id"] for row in rows if row["profiles"]["candidate_plus_eighth"]["score"]["matched"] < row["profiles"]["control"]["score"]["matched"]]
    lines += ["", f"Finale Rückschritte gegenüber der Kontrolle: {', '.join(regressions) if regressions else 'keine auf diesen 30 Entwicklungsbildern'}.",
              "Der zusätzliche Aufruf und seine OCR-Arbeitszeit sind im JSON dokumentiert. Die Summe einzelner Aufrufzeiten unter parallelen Workern ist kein gemessener zusätzlicher End-to-End-Aufwand. Der erweiterte Vorschlag ist nicht als Standardprofil aktiviert."]
    (directory / "NACHTRAG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(directory / "NACHTRAG.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=DEFAULT)
    analyze(parser.parse_args().directory.resolve())
