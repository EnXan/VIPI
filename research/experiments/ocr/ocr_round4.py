"""Round 4: validate the 13-pass OCR profile on a fresh source-stratified batch."""

import argparse
import copy
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
DEFAULT = ROOT / "runs/ocr-screening/2026-10-19-round-04"
PREVIOUS = [ROOT / f"runs/ocr-screening/2026-10-19-round-0{i}" for i in (1, 2, 3)]
SEED = 2026101904
STAGES = ("candidate", "control")
EXTRA_PASSES = [
    {"view_id": "original-unchanged-1x", "filter": "inverted"},
    {"view_id": "opencv-nearest-0.125x", "filter": "grayscale"},
]
CANDIDATE_PASSES = [
    {"view_id": "original-unchanged-1x", "filter": "unchanged"},
    {"view_id": "pillow-bicubic-2x", "filter": "unchanged"},
    {"view_id": "pillow-nearest-0.5x", "filter": "unchanged"},
    {"view_id": "opencv-bicubic-0.5x", "filter": "unchanged"},
    {"view_id": "opencv-nearest-0.25x", "filter": "unchanged"},
    {"view_id": "pillow-nearest-0.25x", "filter": "unchanged"},
    {"view_id": "opencv-linear-exact-0.25x", "filter": "unchanged"},
    {"view_id": "opencv-bicubic-0.25x", "filter": "unchanged"},
    {"view_id": "rotate-90", "filter": "unchanged"},
    {"view_id": "rotate-180", "filter": "unchanged"},
    *EXTRA_PASSES,
    {"view_id": "pillow-nearest-0.125x", "filter": "unchanged"},
]


def select_ids():
    catalog = Catalog(ROOT)
    previous = [
        sample
        for directory in PREVIOUS
        for sample in screening.read(directory / "manifest.json")["samples"]
    ]
    old_ids = {sample["id"] for sample in previous}
    old_groups = {
        sample["content_group_id"]
        for sample in previous
        if sample["category"] != "anamorpher"
    }
    rng = random.Random(SEED)
    strata = [
        ("textocr", False),
        ("textocr", True),
        ("cyberseceval3_visual_prompt_injection", False),
        ("cyberseceval3_visual_prompt_injection", False),
        ("mm_safetybench", False),
        ("mm_safetybench", False),
        ("typographic_visual_prompt_injection", True),
        ("vpi_bench", False),
        ("vpi_bench", False),
    ]
    selected = []
    for category, filtered in strata:
        pool = [
            item
            for item in catalog.items.values()
            if item["category"] == category
            and ("ocr_obfuscation" in item["image"]) == filtered
            and item["id"] not in old_ids
            and item["details"]["content_group_id"] not in old_groups
            and screening.split_for(item["details"]["content_group_id"])
            == "development"
            and (
                category != "textocr"
                or 5 <= len(item["details"].get("regions", [])) <= 30
            )
        ]
        if not pool:
            raise ValueError(f"No unseen development samples for {category=}, {filtered=}.")
        chosen = rng.choice(sorted(pool, key=lambda item: item["id"]))
        selected.append(chosen["id"])
        old_groups.add(chosen["details"]["content_group_id"])

    records = screening.read(
        ROOT / "research/datasets/data/catalog/ocr/anamorpher_manifest.json"
    )["records"]
    active = {item["image"]: item for item in catalog.items.values()}
    anamorpher = [
        active[record["image"]]
        for record in records
        if record["image"] in active
        and active[record["image"]]["id"] not in old_ids
        and record["configuration"]["text_id"] == "blue"
        and record["source_dimensions"] == [3200, 3200]
    ]
    if not anamorpher:
        raise ValueError("No unused blue 3200px Anamorpher variant is available.")
    selected.append(rng.choice(sorted(anamorpher, key=lambda item: item["id"]))["id"])
    return selected


def prepare(directory):
    ids = select_ids()
    screening.prepare(directory, ids, workers=4)
    manifest = screening.read(directory / "manifest.json")
    candidate_source = screening.read(PREVIOUS[2] / "posthoc_eighth.json")
    if candidate_source["next_profile"]["passes"] != CANDIDATE_PASSES:
        raise ValueError("Candidate profile differs from the frozen Round 3 supplement.")
    base_views = [
        view.id
        for view in screening.views_for_size(1024, 768)
        if view.crop is None
    ]
    manifest["profiles"] = {
        "candidate": {
            "passes": copy.deepcopy(CANDIDATE_PASSES),
            "two_times_max_pixels": 8_000_000,
        },
        "control": {
            "passes": [
                {"view_id": view, "filter": "unchanged"} for view in base_views
            ]
            + copy.deepcopy(EXTRA_PASSES),
        },
    }
    manifest["separate_stage_directories"] = True
    manifest["environment"] = {"KMP_USE_SHM": "0"}
    manifest["driver_sha256"] = sha256(Path(__file__))
    manifest["selection_basis"] = {
        "round3_profile_sha256": sha256(PREVIOUS[2] / "posthoc_eighth.json"),
        "round1_manifest_sha256": sha256(PREVIOUS[0] / "manifest.json"),
        "round2_manifest_sha256": sha256(PREVIOUS[1] / "manifest.json"),
        "round3_manifest_sha256": sha256(PREVIOUS[2] / "manifest.json"),
    }
    manifest["design"].update(
        {
            "seed": SEED,
            "assembly_version": ASSEMBLY_VERSION,
            "selection": (
                "ten new image IDs across all six source categories: two TextOCR "
                "(one reviewed obfuscation variant), two CyberSecEval3, two "
                "MM-SafetyBench, one Dagger7164 obfuscation variant, two VPI-Bench, "
                "one new 3200px blue Anamorpher variant"
            ),
            "selection_method": (
                "seeded choice inside fixed source/input strata before inference; "
                "new base content groups only; Anamorpher generator variant is "
                "from the blue development payload and is not an independent payload"
            ),
            "profiles": (
                "candidate: frozen 13-pass Round 3 supplement profile with 2x capped "
                "at 8 MP; control: all 32 whole-image views plus the same two targeted filters"
            ),
            "execution_order": (
                "paired per image; candidate first for even index, control first "
                "for odd index; fresh process per profile"
            ),
            "timing": (
                "complete fresh per-image child elapsed time including initialization, "
                "transforms, OCR and saving; peak RSS is per child process"
            ),
            "reference_review": (
                "all ten references visually checked before inference; source text "
                "unchanged; exclusions separately frozen"
            ),
            "holdout": "orange Anamorpher payload and all hashed base holdout groups untouched",
        }
    )
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
    driver_copy = snapshot / "research/experiments/ocr/ocr_round4.py"
    shutil.copyfile(Path(__file__), driver_copy)
    frozen = directory / "frozen_runtime"
    shutil.copytree(snapshot, frozen)
    for name in (
        "src/vipi/__init__.py",
        "src/vipi/ocr/__init__.py",
        "src/vipi/storage/__init__.py",
        "research/__init__.py",
        "research/evaluation/__init__.py",
        "research/experiments/__init__.py",
        "research/experiments/ocr/__init__.py",
    ):
        (frozen / name).write_text('"""Frozen experiment package."""\n')
    data_link = frozen / "research/datasets/data"
    data_link.parent.mkdir(parents=True, exist_ok=True)
    data_link.symlink_to(ROOT / "research/datasets/data", target_is_directory=True)
    for name in ("models", "runs"):
        (frozen / name).symlink_to(ROOT / name, target_is_directory=True)

    canvas = Image.new("RGB", (1400, 2800), "#eeeeee")
    draw = ImageDraw.Draw(canvas)
    for index, sample in enumerate(manifest["samples"]):
        x, y = index % 2 * 700, index // 2 * 560
        label = f"{sample['id']}  {sample['category']}  {sample['dimensions']}"
        with Image.open(ROOT / sample["image"]) as original:
            tile = ImageOps.contain(original.convert("RGB"), (650, 390))
        canvas.paste(tile, (x + (700 - tile.width) // 2, y + 30))
        draw.text((x + 10, y + 5), label, fill="black")
        reference = sample["reference"]["text"].replace("\n", " / ")
        draw.text((x + 10, y + 430), reference[:100], fill="black")
        draw.text((x + 10, y + 458), f"scope: {sample['reference']['scope']}", fill="black")
    canvas.save(directory / "selection-contact-sheet.jpg")
    write_json(directory / "reference_exclusions.json", {})
    print(f"Prepared {len(ids)} images in {directory}; visually review before OCR.", flush=True)


def result(reference, steps):
    text, regions = assemble(steps)
    observations = regions if reference["reading_order_known"] else final_observations(regions, steps)
    score, expected, matched = compare(reference, text, observations)
    pool = set().union(*(compare(reference, step["text"], step["regions"])[2] for step in steps))
    return {
        "text": text,
        "score": score,
        "pool_positions": sorted(pool),
        "final_positions": sorted(matched),
        "expected": expected,
    }


def run(directory):
    manifest = screening.check_manifest(directory)
    if sha256(Path(__file__)) != manifest["driver_sha256"]:
        raise ValueError("Driver source changed after preparation.")
    review_path = directory / "reference_audit.json"
    if not review_path.is_file():
        raise ValueError("Review all ten references and write reference_audit.json first.")
    review = screening.read(review_path)
    exclusions_path = directory / "reference_exclusions.json"
    if not exclusions_path.is_file():
        raise ValueError("Freeze reference_exclusions.json before inference.")
    exclusions = screening.read(exclusions_path)
    if set(review) != {sample["id"] for sample in manifest["samples"]}:
        raise ValueError("Review every selected reference before running.")
    if not set(exclusions) <= set(review):
        raise ValueError("Reference exclusions must name reviewed samples only.")
    review_hash, exclusions_hash = sha256(review_path), sha256(exclusions_path)
    measurements_path = directory / "measurements.json"
    saved = (
        screening.read(measurements_path)
        if measurements_path.exists()
        else {
            "measurements": [],
            "review_sha256": review_hash,
            "exclusions_sha256": exclusions_hash,
        }
    )
    if (saved["review_sha256"], saved["exclusions_sha256"]) != (review_hash, exclusions_hash):
        raise ValueError("Reference review changed after first inference.")
    write_json(measurements_path, saved)
    for index, sample in enumerate(manifest["samples"]):
        order = STAGES if index % 2 == 0 else tuple(reversed(STAGES))
        for stage in order:
            complete = [
                item
                for item in saved["measurements"]
                if item["sample_id"] == sample["id"]
                and item["stage"] == stage
                and item["exit_code"] == 0
            ]
            if complete:
                continue
            steps_path = directory / "samples" / sample["id"] / stage / "steps"
            if steps_path.exists() and list(steps_path.glob("*.json")):
                raise ValueError("Partial profile found; do not call it a fresh timing run.")
            print(f"IMAGE {index + 1}/10 {sample['id']} {stage}", flush=True)
            command = [
                sys.executable,
                str(ROOT / "research/experiments/ocr/ocr_screening.py"),
                "_image",
                str(directory),
                "--id",
                sample["id"],
                "--stage",
                stage,
            ]
            started = time.perf_counter()
            child = subprocess.Popen(
                command,
                cwd=ROOT,
                env={**os.environ, **manifest["environment"]},
            )
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
            saved["measurements"].append(
                {
                    "sample_id": sample["id"],
                    "stage": stage,
                    "exit_code": child.returncode,
                    "elapsed_seconds": time.perf_counter() - started,
                    "user_cpu_seconds": usage.ru_utime,
                    "system_cpu_seconds": usage.ru_stime,
                    "peak_resident_bytes": usage.ru_maxrss
                    * (1 if sys.platform == "darwin" else 1024),
                }
            )
            write_json(measurements_path, saved)
            if child.returncode:
                raise RuntimeError("OCR child failed; results and measurements were retained.")
    report(directory)


def report(directory):
    manifest = screening.check_manifest(directory)
    measurements = screening.read(directory / "measurements.json")
    review_path = directory / "reference_audit.json"
    exclusions_path = directory / "reference_exclusions.json"
    if measurements["review_sha256"] != sha256(review_path) or measurements["exclusions_sha256"] != sha256(exclusions_path):
        raise ValueError("Reference review changed.")
    review = screening.read(review_path)
    exclusions = screening.read(exclusions_path)
    rows = []
    for sample in manifest["samples"]:
        steps = {}
        for stage in STAGES:
            folder = directory / "samples" / sample["id"] / stage / "steps"
            steps[stage] = [screening.read(path) for path in sorted(folder.glob("*.json"))]
            expected = {
                f"{number:04d}"
                for number, _, _ in screening.schedule(sample, stage, directory)
            }
            if {step["id"] for step in steps[stage]} != expected:
                raise ValueError(f"Incomplete {stage} observations for {sample['id']}.")
            timing = [
                item
                for item in measurements["measurements"]
                if item["sample_id"] == sample["id"]
                and item["stage"] == stage
                and item["exit_code"] == 0
            ]
            if len(timing) != 1:
                raise ValueError("Missing or duplicate complete process measurement.")
        control_by_id = {step["id"]: step for step in steps["control"]}
        if any(
            step["raster_sha256"] != control_by_id[step["id"]]["raster_sha256"]
            for step in steps["candidate"]
        ):
            raise ValueError("Candidate/control shared rasters differ.")
        scopes = {}
        for scope in ("source", "reviewed_subset"):
            reference = copy.deepcopy(sample["reference"])
            if scope == "reviewed_subset" and sample["id"] in exclusions:
                if reference["reading_order_known"]:
                    raise ValueError("Exact region exclusions are not supported for this reference.")
                ignored = set(exclusions[sample["id"]])
                reference["regions"] = [
                    region for region in reference["regions"] if region["text"] not in ignored
                ]
            scored = {stage: result(reference, values) for stage, values in steps.items()}
            lost = set(scored["control"]["pool_positions"]) - set(scored["candidate"]["pool_positions"])
            scopes[scope] = {
                **scored,
                "lost_pool_tokens": [scored["control"]["expected"][i] for i in sorted(lost)],
            }
        times = {
            stage: next(
                item
                for item in measurements["measurements"]
                if item["sample_id"] == sample["id"] and item["stage"] == stage
            )
            for stage in STAGES
        }
        rows.append(
            {
                "id": sample["id"],
                "category": sample["category"],
                "content_group_id": sample["content_group_id"],
                "reference_review": review[sample["id"]],
                "scopes": scopes,
                "passes": {stage: len(steps[stage]) for stage in STAGES},
                "measurements": times,
            }
        )
    summary = {
        stage: {
            "elapsed_seconds": sum(
                item["elapsed_seconds"]
                for item in measurements["measurements"]
                if item["stage"] == stage
            ),
            "peak_resident_bytes": max(
                item["peak_resident_bytes"]
                for item in measurements["measurements"]
                if item["stage"] == stage
            ),
            "passes": sum(row["passes"][stage] for row in rows),
        }
        for stage in STAGES
    }
    write_json(
        directory / "analysis.json",
        {
            "assembly_version": ASSEMBLY_VERSION,
            "manifest_sha256": sha256(directory / "manifest.json"),
            "report_source_sha256": sha256(Path(__file__)),
            "samples": rows,
            "summary": summary,
            "limitations": [
                "Ten-image, purposefully source-stratified development batch; not a population estimate.",
                "The Anamorpher sample shares the blue payload with prior development runs and is not independent payload evidence.",
                "The orange Anamorpher payload and base holdout content groups remain untouched.",
                "Source references are silver/partial or synthetic target-only references, not full-image Gold transcripts.",
                "CPU timing includes fresh model initialization, transformations, OCR and file saving; final assembly is separate.",
            ],
        },
    )
    lines = [
        "# OCR Runde 4",
        "",
        "Zehn neue Entwicklungsbilder decken alle sechs Quellen ab. Die fünf Basisquellen verwenden neue Inhaltsgruppen; der Anamorpher-Fall ist eine neue Variante des bereits verwendeten blauen Payloads und zählt nicht als unabhängige Payload-Replikation. Orange und gehashte Basis-Holdouts wurden nicht verwendet.",
        "",
        "| Profil | OCR-Aufrufe | gemessene Laufzeit | maximaler Prozess-RSS |",
        "|---|---:|---:|---:|",
    ]
    for stage in STAGES:
        values = summary[stage]
        lines.append(
            f"| {stage} | {values['passes']} | {values['elapsed_seconds']:.1f} s | "
            f"{values['peak_resident_bytes'] / 1024**3:.2f} GiB |"
        )
    for scope in ("source", "reviewed_subset"):
        lines += [
            "",
            f"## Abdeckung: {scope}",
            "",
            "| Bild | Quelle | Kandidat | Kontrolle | verlorene Pool-Tokens |",
            "|---|---|---:|---:|---|",
        ]
        for row in rows:
            scores = [row["scopes"][scope][stage]["score"] for stage in STAGES]
            lost = row["scopes"][scope]["lost_pool_tokens"]
            lines.append(
                f"| {row['id']} | {row['category']} | "
                f"{scores[0]['matched']}/{scores[0]['total']} ({scores[0]['coverage']:.1%}) | "
                f"{scores[1]['matched']}/{scores[1]['total']} ({scores[1]['coverage']:.1%}) | "
                f"{', '.join(lost)} |"
            )
    category_counts = {}
    for row in rows:
        category_counts[row["category"]] = category_counts.get(row["category"], 0) + 1
    lines += [
        "",
        "## Stichprobe und Aussagegrenzen",
        "",
        "Quellenverteilung: " + ", ".join(f"{key}={value}" for key, value in sorted(category_counts.items())) + ".",
        "Der Kandidat entspricht dem eingefrorenen 13-Pass-Profil aus dem Round-3-Nachtrag. Die Kontrolle führt alle 32 unskalierten Gesamtbildansichten und dieselben zwei gezielten Filter aus. Bei 2×-Ansichten gilt für den Kandidaten die 8-MP-Grenze; es gibt keine Kacheln.",
        "Laufzeiten sind Summen tatsächlich gemessener frischer Kindprozesse mit alternierender Profilreihenfolge; sie enthalten Modellstart, Transformation, OCR und Speicherung. RSS ist der Spitzenwert eines OCR-Prozesses. Die zehn Fälle sind eine kleine Entwicklungsstichprobe, kein Holdout und keine Schätzung über alle 1.676 Bilder. Abdeckung bewertet nur die belegte Referenz, nicht unreferenzierten Hintergrund- oder UI-Text.",
    ]
    (directory / "ERGEBNISSE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(directory / "ERGEBNISSE.md", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "report"))
    parser.add_argument("directory", type=Path, nargs="?", default=DEFAULT)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepare(directory)
    elif args.command == "run":
        run(directory)
    else:
        report(directory)


if __name__ == "__main__":
    main()
