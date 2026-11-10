"""Earlier OCR results are reused only when the OCR would be identical."""

import json
from types import SimpleNamespace

from research.ocr_eval import benchmark, benchmark_report, ocr_reuse

GOOGLE = {"ocr_execution_mode": "cloud", "ocr_provider": "google"}
GOOGLE_JEV = {**GOOGLE, "detector": "jev"}
MISTRAL = {"ocr_execution_mode": "cloud", "ocr_provider": "mistral"}
LOCAL = {"ocr_execution_mode": "local", "ocr_mode": "speed"}
RESULT = {
    "model": "google-cloud-vision",
    "text": "hello",
    "regions": [],
    "variants": [],
    "input_size": [1, 1],
    "assembly_version": 1,
    "elapsed_seconds": 4.0,
}


def provenance(**changes):
    sources = {
        "src/vipi/ocr/pipeline.py": "ocr",
        "src/vipi/config.py": "config",
        "src/vipi/detection/pipeline.py": "detect",
        "src/vipi/detection/providers/http.py": "http",
        "src/vipi/scanner.py": "scanner",
        "research/catalog.py": "research",
    }
    packages = {"Pillow": "11", "numpy": "1", "torch": "2.11", "rapidocr": "3"}
    return {
        "source_hashes": {**sources, **changes.pop("sources", {})},
        "packages": {**packages, **changes.pop("packages", {})},
    }


def test_identity_ignores_the_detector_and_detection_sources():
    base = ocr_reuse.ocr_identity(GOOGLE, provenance())
    assert ocr_reuse.ocr_identity(GOOGLE_JEV, provenance()) == base
    for path in ("src/vipi/detection/pipeline.py", "src/vipi/scanner.py"):
        changed = provenance(sources={path: "changed"})
        assert ocr_reuse.ocr_identity(GOOGLE, changed) == base
    assert (
        ocr_reuse.ocr_identity(GOOGLE, provenance(packages={"torch": "2.14"})) == base
    )


def test_identity_changes_with_ocr_settings_sources_and_local_packages():
    base = ocr_reuse.ocr_identity(GOOGLE, provenance())
    assert ocr_reuse.ocr_identity(MISTRAL, provenance()) != base
    for path in ("src/vipi/ocr/pipeline.py", "src/vipi/config.py"):
        changed = provenance(sources={path: "changed"})
        assert ocr_reuse.ocr_identity(GOOGLE, changed) != base
    http = provenance(sources={"src/vipi/detection/providers/http.py": "changed"})
    assert ocr_reuse.ocr_identity(GOOGLE, http) != base
    local = ocr_reuse.ocr_identity(LOCAL, provenance())
    newer = provenance(packages={"torch": "2.14"})
    assert ocr_reuse.ocr_identity(LOCAL, newer) != local


def earlier_run(root, name, options, rows, record=provenance()):
    """Write an evaluation run with completed rows; return artifacts per key."""
    directory = root / name / "benchmark"
    configuration = "cloud-google" if options == GOOGLE else "other"
    selection = [{"key": key, "image_sha256": image} for key, image, _ in rows]
    benchmark.write_json(
        directory / "manifest.json",
        {
            "provenance": record,
            "selection": selection,
            "configurations": {configuration: options},
        },
    )
    benchmark.write_json(directory / configuration / "session.json", {"model": "m"})
    artifacts = {}
    for key, _image, finished in rows:
        folder = root / "cache" / f"{name}-{key}"
        (folder / "detection" / "old").mkdir(parents=True)
        (folder / "input.png").write_bytes(b"png")
        benchmark.write_json(folder / "result.json", {**RESULT, "run_id": folder.name})
        benchmark.write_json(
            directory / configuration / "rows" / f"{key}.json",
            {
                "key": key,
                "status": "completed",
                "artifacts": str(folder),
                "result_sha256": benchmark.digest(folder / "result.json"),
                "pipeline_seconds": 4.0,
                "cost": {"estimated_usd": 0.01},
                "finished_at": finished,
            },
        )
        artifacts[key] = folder
    return artifacts


def test_candidates_take_the_newest_matching_result_and_check_the_image(tmp_path):
    earlier_run(tmp_path, "old", GOOGLE, [("a", "img-a", "2026-11-01")])
    newest = earlier_run(tmp_path, "new", GOOGLE, [("a", "img-a", "2026-11-02")])
    earlier_run(tmp_path, "mistral", MISTRAL, [("b", "img-b", "2026-11-03")])
    changed = provenance(sources={"src/vipi/ocr/pipeline.py": "older"})
    earlier_run(tmp_path, "stale", GOOGLE, [("c", "img-c", "2026-11-03")], changed)
    found = ocr_reuse.candidates(tmp_path, GOOGLE_JEV, provenance())
    assert set(found) == {"a"}
    assert found["a"]["artifacts"] == str(newest["a"])
    assert found["a"]["run_id"] == "new"
    rows = [{"key": "a", "image_sha256": "img-a"}, {"key": "b", "image_sha256": "x"}]
    assert set(ocr_reuse.matching(rows, found)) == {"a"}
    edited = [{"key": "a", "image_sha256": "edited"}]
    assert ocr_reuse.matching(edited, found) == {}


def test_restore_copies_ocr_without_detection_and_refuses_changed_output(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    source = earlier_run(tmp_path, "run", GOOGLE, [("a", "img", "t")])["a"]
    candidate = ocr_reuse.candidates(tmp_path, GOOGLE, provenance())["a"]
    ocr = ocr_reuse.restore(candidate)
    assert ocr.artifacts.parent == tmp_path / "xdg/vipi/runs"
    assert ocr.run_id == ocr.artifacts.name != source.name
    assert not (ocr.artifacts / "detection").exists()
    assert ocr.image == b"png"
    assert (source / "detection" / "old").is_dir()  # the earlier run is untouched
    benchmark.write_json(source / "result.json", {**RESULT, "run_id": "edited"})
    assert ocr_reuse.restore(candidate) is None


def test_worker_runs_only_detection_for_reused_images(tmp_path, monkeypatch):
    rows = []
    for key in ("reused", "scanned"):
        path = tmp_path / f"research/dataset/images/{key}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key.encode())
        rows.append(
            {
                "key": key,
                "image": f"images/{key}.png",
                "image_sha256": benchmark.digest(path),
            }
        )
    artifacts = tmp_path / "copy"
    artifacts.mkdir()
    (artifacts / "result.json").write_text("{}")
    restored = SimpleNamespace(
        artifacts=artifacts, elapsed_seconds=4.0, cost={"estimated_usd": 0.01}
    )
    sessions, scanned, detected = [], [], []

    class Session:
        metadata = {"model": "fixture"}

        def __init__(self, **kwargs):
            sessions.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def scan(path, *, options, session, provider, on_event):
        scanned.append(path.name)
        fresh = tmp_path / "fresh"
        fresh.mkdir()
        (fresh / "result.json").write_text("{}")
        return SimpleNamespace(
            ocr=SimpleNamespace(artifacts=fresh, elapsed_seconds=2.0, cost={})
        )

    def detect(ocr, options, provider):
        detected.append(options.resolved_detector)
        return SimpleNamespace(ocr=ocr)

    session = tmp_path / "earlier-session.json"
    session.write_text('{"model": "earlier"}')
    earlier = {
        "run_id": "earlier-run",
        "configuration": "cloud-google",
        "artifacts": "/cache/runs/abc",
        "session": str(session),
    }
    monkeypatch.setattr(benchmark, "ROOT", tmp_path)
    monkeypatch.setattr(benchmark, "OcrSession", Session)
    monkeypatch.setattr(benchmark, "scan_image", scan)
    monkeypatch.setattr(benchmark, "detect_reused", detect)
    monkeypatch.setattr(benchmark.ocr_reuse, "restore", lambda value: restored)
    monkeypatch.setattr(benchmark, "prepare_provider", lambda name, path: name)
    monkeypatch.setattr(
        benchmark,
        "file_record",
        lambda result: {
            "verdict": "clean",
            "signals": {},
            "errors": [],
            "detection_seconds": 0.5,
            "detection_cost": None,
        },
    )
    output = tmp_path / "benchmark"
    benchmark.worker(output, "cloud-google-jev", rows[:1], {"reused": earlier})
    assert sessions == [] and scanned == [] and detected == ["jev"]
    assert json.loads((output / "session.json").read_text()) == {"model": "earlier"}
    benchmark.worker(output, "cloud-google-jev", rows[1:], {"reused": earlier})
    assert len(sessions) == 1 and scanned == ["scanned.png"]
    reused = json.loads((output / "rows/reused.json").read_text())
    fresh = json.loads((output / "rows/scanned.json").read_text())
    assert reused["ocr_reused_from"] == {
        "run_id": "earlier-run",
        "configuration": "cloud-google",
        "run": "abc",
    }
    assert reused["elapsed_seconds"] == 4.5  # original OCR time + this detection
    assert reused["cost"] == {"estimated_usd": 0.01}
    assert "ocr_reused_from" not in fresh


def test_report_counts_reused_images_and_unspent_ocr_cost():
    from tests.research.test_benchmark import scored_row

    reused = {
        **scored_row(1, 1),
        "ocr_reused_from": {"run_id": "x"},
        "ocr_reused_usd": 0.25,
    }
    summary = benchmark_report.summarize([reused, scored_row(1, 1)])
    assert summary["ocr_reused"] == {
        "images": 1,
        "estimated_usd_not_spent_again": 0.25,
    }
    line = benchmark_report.reuse_lines(summary)[0]
    assert "for 1 of 2 images" in line and "$0.25" in line
    assert (
        benchmark_report.reuse_lines(benchmark_report.summarize([scored_row(1, 1)]))
        == []
    )
