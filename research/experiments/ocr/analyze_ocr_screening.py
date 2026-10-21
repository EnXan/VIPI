"""Audited reports from saved screening observations, with no further inference.

Keeps legacy scores and separately checks a discovered final word-box mapping
limitation: a raw line can omit spaces present in its own native word boxes.
"""

import csv
import json
from pathlib import Path
import sys

from research.evaluation.metrics import compare, final_observations, tokens
from vipi.ocr.merge import bounds, line_candidates, assemble
from research.experiments.ocr.ocr_screening import check_manifest, greedy_views, load_samples, read, schedule
from vipi.ocr.models import sha256
from vipi.storage.ocr import write_json


def compact(text):
    return "".join(tokens(text))


def native_final_observations(regions, steps):
    """Use only selected native words demonstrably present in each emitted line.

    No ground truth participates in reconstruction. If selected words do not
    reproduce the complete emitted line modulo spaces, use the legacy mapping.
    """
    candidates = {step["id"]: line_candidates([step]) for step in steps}
    observations, repaired = [], 0
    for region in regions:
        selected = region.get("selected_step_id")
        anchor = next((x for x in region.get("evidence", []) if x["step_id"] == selected), region)
        candidate = next((x for x in candidates.get(selected, []) if x["input_polygon"] == anchor["input_polygon"] and x["text"] == anchor["text"]), None)
        additions = region.get("additions", [])
        if candidate is not None:
            box = bounds(candidate["input_polygon"])
            left = [x for x in additions if bounds(x["input_polygon"])[2] <= box[0]]
            right = [x for x in additions if bounds(x["input_polygon"])[0] >= box[2]]
            words = [*left, *candidate["words"], *right]
            if compact(" ".join(x["text"] for x in words)) == compact(region["text"]):
                observations.extend(words)
                repaired += int(tokens(candidate["text"]) != tokens(" ".join(x["text"] for x in candidate["words"])))
                continue
        observations.extend(final_observations([region], steps))
    return observations, repaired


def subset(row, steps, reference=None):
    reference = reference or row["sample"]["reference"]
    text, regions = assemble(steps)
    if reference["reading_order_known"]:
        observed, repaired = regions, 0
    else:
        observed, repaired = native_final_observations(regions, steps)
    final = compare(reference, text, observed)[0]
    legacy_observed = regions if reference["reading_order_known"] else final_observations(regions, steps)
    legacy = compare(reference, text, legacy_observed)[0]
    return {"final": final, "legacy_final": legacy, "reconstructed_compact_lines": repaired, "text": text,
            "passes": len(steps), "ocr_work_seconds": sum(x["timing"]["ocr_seconds"] for x in steps)}


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def mean(items, key):
    return sum(x[key] for x in items) / len(items) if items else 0


def analyze(directory):
    manifest = check_manifest(directory)
    rows = load_samples(directory, manifest)
    if (directory / "filter_plan.json").exists():
        for row in rows:
            planned = {f"{n:04d}" for n, _, _ in schedule(row["sample"], "filters", directory)}
            if not planned <= {s["id"] for s in row["steps"]}:
                raise ValueError(f"Incomplete filters: {row['sample']['id']}")
    audit_file = directory / "reference_audit.json"
    audit = read(audit_file) if audit_file.exists() else {}
    chosen, history = greedy_views(rows)
    samples, per_step, filters, progression, duplicates = [], [], [], [], []
    for row in rows:
        s = row["sample"]
        base = [x for x in row["steps"] if x["filter"] == "unchanged"]
        original = next(x for x in base if x["index"] == 1)
        original_score = row["scores"][original["id"]]
        rasters = {}
        for step in row["steps"]:
            rasters.setdefault(step["raster_sha256"], []).append(step)
        for raster_hash, equivalent in rasters.items():
            if len(equivalent) > 1:
                duplicates.append({"sample_id": s["id"], "raster_sha256": raster_hash,
                                   "step_ids": [x["id"] for x in equivalent],
                                   "labels": [x["label"] for x in equivalent],
                                   "same_native_reading": len({json.dumps({"text": x["text"], "regions": [{k:v for k,v in r.items() if k != 'input_polygon'} for r in x['regions']]}, sort_keys=True) for x in equivalent}) == 1,
                                   "redundant_ocr_work_seconds": sum(x["timing"]["ocr_seconds"] for x in equivalent[1:])})
        union = set().union(*(row["matches"][x["id"]] for x in base))
        total = original_score["total"]
        best = max(base, key=lambda x: (row["scores"][x["id"]]["matched"], -x["index"]))
        all_ids = set().union(*(row["matches"][x["id"]] for x in row["steps"]))
        record = {"id": s["id"], "category": s["category"], "original": original_score,
                  "best_view": best["view_id"], "best_score": row["scores"][best["id"]],
                  "unfiltered_oracle": len(union)/total, "all_observed_oracle": len(all_ids)/total,
                  "all_unfiltered": subset(row, base),
                  "shortlist": subset(row, [x for x in base if x["view_id"] in chosen]),
                  "all_observed": subset(row, row["steps"])}
        # Audited subset never rewrites the source reference or its annotation quality.
        excluded = audit.get(s["id"], {}).get("excluded_from_confident_subset", [])
        if excluded:
            ref = {**s["reference"], "regions": [r for r in s["reference"]["regions"] if r["text"] not in excluded]}
            record["confident_subset"] = {
                "excluded_words": excluded,
                "original": compare(ref, original["text"], original["regions"])[0],
                "all_unfiltered": subset(row, base, ref)["final"],
                "all_observed": subset(row, row["steps"], ref)["final"],
            }
        samples.append(record)
        for step in row["steps"]:
            score = row["scores"][step["id"]]
            pair_id = f"{(step['index']-1)//5*5+1:04d}"
            others = set().union(*(row["matches"][x["id"]] for x in base if x["id"] != step["id"]))
            per_step.append({"sample_id": s["id"], "category": s["category"], "view_id": step["view_id"], "filter": step["filter"],
                             "coverage": score["coverage"], "matched": score["matched"], "total": total,
                             "extra_tokens_vs_original": len(row["matches"][step["id"]] - row["matches"][original["id"]]),
                             "unique_tokens_among_32": len(union-others) if step["filter"] == "unchanged" else 0,
                             **step["timing"]})
            if step["filter"] != "unchanged":
                filters.append({"sample_id": s["id"], "view_id": step["view_id"], "filter": step["filter"], "coverage": score["coverage"],
                                "paired_unfiltered_coverage": row["scores"][pair_id]["coverage"],
                                "coverage_delta": score["coverage"]-row["scores"][pair_id]["coverage"],
                                "extra_tokens_beyond_all_32": len(row["matches"][step["id"]]-union), "ocr_seconds": step["timing"]["ocr_seconds"]})
    for n in range(1, len(chosen)+1):
        measurements = [subset(row, [x for x in row["steps"] if x["filter"] == "unchanged" and x["view_id"] in chosen[:n]]) for row in rows]
        progression.append({"views": chosen[:n], "passes_per_image": n,
                            "mean_final_coverage": sum(x["final"]["coverage"] for x in measurements)/len(rows),
                            "complete_images": sum(x["final"]["valid"] for x in measurements),
                            "ocr_work_seconds": sum(x["ocr_work_seconds"] for x in measurements)})
    filter_summary = []
    for name in sorted({x["filter"] for x in filters}):
        items = [x for x in filters if x["filter"] == name]
        filter_summary.append({"filter": name, "comparisons": len(items), "improved": sum(x["coverage_delta"] > 0 for x in items),
                               "worse": sum(x["coverage_delta"] < 0 for x in items), "equal": sum(x["coverage_delta"] == 0 for x in items),
                               "mean_coverage_delta": mean(items, "coverage_delta"), "extra_reference_matches": sum(x["extra_tokens_beyond_all_32"] for x in items),
                               "ocr_work_seconds": sum(x["ocr_seconds"] for x in items)})
    stages = {stage: read(directory / f"{stage}_status.json") for stage in ("views", "filters") if (directory/f"{stage}_status.json").exists()}
    output = {"analysis_source_sha256": sha256(Path(__file__)), "reference_audit_sha256": sha256(audit_file) if audit_file.exists() else None,
              "samples": samples, "shortlist": chosen, "greedy_history": history, "progression": progression,
              "filter_summary": filter_summary, "stages": stages, "identical_rasters": duplicates,
              "limitations": ["Ten purposefully selected development images, eight content groups; no holdout result.",
                              "Three Anamorpher generators share the same blue payload, with orange reserved.",
                              "Source annotations are unchanged. Confident subset excludes visually uncertain words only.",
                              "Final scores include a separate native-word reconstruction audit for the production evaluator's compact-line limitation.",
                              "OCR work sums are not measured end-to-end speedups; candidate timings require a separate run."]}
    write_json(directory / "analysis.json", output)
    write_csv(directory / "per_step.csv", per_step)
    write_csv(directory / "paired_filters.csv", filters)
    write_csv(directory / "filter_summary.csv", filter_summary)
    lines = ["# Erste OCR-Versuchsrunde: zehn Bilder", "", "PP-OCRv6, CPU, vier Worker mit je zwei Threads. Ungefilterte Gesamtbildansichten zuerst, danach Filter auf drei festgelegten Ansichten. Keine Kacheln. Die Standardpipeline und der Katalog wurden nicht geändert.", "",
             "## Ergebnis pro Bild", "", "Abdeckung bezieht sich auf exakte Referenztokens nach der bestehenden Normalisierung, einschließlich Satzzeichen. TextOCR wird räumlich anhand der Wortregionen bewertet. Zusätzlich sichtbarer Text bleibt unbewertet. Die Original-Spalte bewertet die rohe Original-OCR; finale Spalten und die Kombinationstabelle bewerten den tatsächlich zusammengesetzten Text. Auch bei nur einer Ansicht kann die Zusammenführung den Text verändern.", "",
             "| Bild | Quelle | Original | Beste Einzelansicht | Final, 32 Ansichten | Final, kleine Auswahl | Final, mit Filtern |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for s in samples:
        values = [s["original"]["coverage"],s["best_score"]["coverage"],*[s[k]["final"]["coverage"] for k in ("all_unfiltered","shortlist","all_observed")]]
        lines.append(f"| {s['id']} | {s['category']} | "+" | ".join(f"{v:.1%}" for v in values)+" |")
    lines += ["", "## Laufzeit", ""]
    for name, stage in stages.items():
        lines.append(f"- {name}: {stage['state']}, {stage['elapsed_seconds']:.1f} Sekunden tatsächliche Gesamtlaufzeit.")
    lines += [f"- Gespeicherte OCR-Durchläufe: {len(per_step)}.", "", "## Kandidat für die nächste Entwicklungsrunde", "", *[f"- `{x}`" for x in chosen], "", "| Ansichten pro Bild | Mittlere finale Abdeckung | Vollständig abgedeckte Bilder | OCR-Arbeit (s) |", "|---:|---:|---:|---:|"]
    for item in progression:
        lines.append(f"| {item['passes_per_image']} | {item['mean_final_coverage']:.1%} | {item['complete_images']}/10 | {item['ocr_work_seconds']:.1f} |")
    lines += ["", "Die Auswahl nutzt Referenzen dieser Entwicklungsgruppe. Sie ist eine zu prüfende Hypothese. OCR-Arbeit summiert die Laufzeiten paralleler Aufrufe; daraus folgt keine gemessene Beschleunigung. Alle Kombinationen werden aus gespeicherten Beobachtungen neu zusammengesetzt, ohne weitere OCR.", "", "## Filter im direkten Vergleich", "", "| Filter | Verbessert | Gleich | Verschlechtert | Zusätzliche Token-Treffer gegenüber allen 32 Ansichten | OCR-Arbeit (s) |", "|---|---:|---:|---:|---:|---:|"]
    for item in filter_summary:
        lines.append(f"| {item['filter']} | {item['improved']} | {item['equal']} | {item['worse']} | {item['extra_reference_matches']} | {item['ocr_work_seconds']:.1f} |")
    redundant = sum(len(x["step_ids"])-1 for x in duplicates)
    inconsistent = sum(not x["same_native_reading"] for x in duplicates)
    lines += ["", "Zusätzliche Token-Treffer werden hier pro Filteraufruf gezählt; doppelte Treffer über Filteraufrufe dürfen nicht als verschiedene Wörter addiert werden. `analysis.json` enthält die deduplizierte Abdeckung pro Bild.", "", "## Identische Bildansichten", "", f"{redundant} von {len(per_step)} Aufrufen verarbeiten innerhalb desselben Bildes ein bereits zuvor erzeugtes, byte-identisches PNG. {inconsistent} dieser Gruppen liefern abweichende native OCR-Lesarten. Die Rohbeobachtungen bleiben gespeichert. Ein künftiger Raster-Cache könnte identische OCR-Eingaben wiederverwenden; dabei müssen Positionen für jede Transformation erneut zurückgerechnet und die bisherigen Zusammenführungsstimmen beibehalten werden. Dies wurde hier nur analysiert, nicht in der Standardpipeline aktiviert.", "", "## Bewertungsprüfung", "", "Der unveränderte Produktionsauswerter verwirft teilweise native Wortpositionen, wenn die ausgewählte OCR-Zeile Wörter ohne Leerzeichen verbindet (etwa MCLARENVALE, während native Wortboxen MCLAREN und VALE liefern). `REPORT.md` erhält diese ursprünglichen Werte. Die Tabelle hier rekonstruiert zusätzlich die ausgewählten nativen Wörter, sofern sie den ausgegebenen Zeilentext bis auf Leerzeichen exakt reproduzieren. Referenztext wird dafür nicht verwendet. Die ausgegebenen Texte selbst bleiben unverändert.", ""]
    for s in samples:
        before = s["all_unfiltered"]["legacy_final"]["coverage"]
        after = s["all_unfiltered"]["final"]["coverage"]
        if before!=after:
            lines.append(f"- {s['id']}: ursprüngliche finale Bewertung {before:.1%}, mit überprüfter Wortzuordnung {after:.1%}.")
    lines += ["", "## Referenzprüfung und Grenzen", "", "Die Rohreferenzen sind unverändert; schwer lesbare Wörter werden separat ausgewiesen. Eine visuelle Prüfung einzelner Fälle macht den gesamten Quelldatensatz nicht zu Gold.", ""]
    for s in samples:
        if s.get("confident_subset"):
            checked=s["confident_subset"]
            lines.append(f"- {s['id']}: unsicher: {', '.join(checked['excluded_words'])}. Auf der verbleibenden geprüften Teilreferenz: Original {checked['original']['coverage']:.1%}, final mit Filtern {checked['all_observed']['coverage']:.1%}.")
    lines += ["", "Zehn bewusst ausgewählte Bilder repräsentieren acht Inhaltsgruppen. Alle drei Anamorpher-Fälle haben denselben Payload-Text und testen drei Generatoren; ihre Ergebnisse erlauben keine Aussage über beliebige Payloads. Orange bleibt als eigene Inhaltsgruppe zurückgehalten. Kein Holdout wurde ausgewertet.", "", "## Dateien", "", "- `manifest.json`: feste Auswahl, Konfiguration und Hashes.", "- `split.json`: Inhaltsgruppen und Entwicklungs-/Prüfzuordnung.", "- `reference_audit.json`: visuelle Referenzprüfung und Unsicherheiten.", "- `per_step.csv`: Abdeckung und Zeiten aller Ansichten/Filter.", "- `paired_filters.csv`: direkter Vergleich zum jeweils ungefilterten Bild.", "- `analysis.json`: vollständige Auswertung, Teilreferenzen und Kombinationen.", "- `samples/<id>/steps/`: Rohtext, Boxen und Vorverarbeitung jedes OCR-Schritts.", "- `samples/<id>/images/`: tatsächlich verarbeitete Bildansichten."]
    (directory / "ERGEBNISSE.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({"images":len(samples),"steps":len(per_step),"shortlist":chosen,"filter_summary":filter_summary},indent=2))


if __name__ == "__main__":
    analyze(Path(sys.argv[1]).resolve())
