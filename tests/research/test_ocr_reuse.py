"""Earlier OCR results are reused only when the OCR would be identical."""

import json
from types import SimpleNamespace

from research.ocr_eval import benchmark, ocr_reuse

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
    configuration = {
        id(GOOGLE): "cloud-google",
        id(GOOGLE_JEV): "cloud-google-jev",
    }.get(id(options), "other")
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
                "detection": {"verdict": "flagged", "cost": {"estimated_usd": 0.002}},
                "elapsed_seconds": 5.0,
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
    assert found["a"]["detection"] is None  # other detector: detection runs again


def test_identical_detection_identity_carries_the_earlier_detection(tmp_path):
    earlier_run(tmp_path, "luna", GOOGLE, [("a", "img", "2026-11-03")])
    earlier_run(tmp_path, "jev", GOOGLE_JEV, [("a", "img", "2026-11-01")])
    found = ocr_reuse.candidates(tmp_path, GOOGLE_JEV, provenance())
    # A full match beats a newer OCR-only match.
    assert found["a"]["run_id"] == "jev"
    assert found["a"]["detection"]["verdict"] == "flagged"
    assert found["a"]["elapsed_seconds"] == 5.0
    for changed in (
        provenance(sources={"src/vipi/detection/pipeline.py": "new"}),
        provenance(sources={"src/vipi/scanner.py": "new"}),
        provenance(packages={"torch": "2.14"}),
    ):
        again = ocr_reuse.candidates(tmp_path, GOOGLE_JEV, changed)
        assert again["a"]["detection"] is None


def test_full_identity_includes_detector_settings_sources_and_packages():
    base = ocr_reuse.full_identity(GOOGLE, provenance())
    assert ocr_reuse.full_identity(GOOGLE_JEV, provenance()) != base
    assert ocr_reuse.full_identity({**GOOGLE, "threshold": 70}, provenance()) != base
    changed = provenance(sources={"src/vipi/reporting.py": "new"})
    assert ocr_reuse.full_identity(GOOGLE, changed) != base
    assert ocr_reuse.full_identity(GOOGLE, provenance(packages={"numpy": "2"})) != base
    research = provenance(sources={"research/catalog.py": "new"})
    assert ocr_reuse.full_identity(GOOGLE, research) == base
    label = provenance(packages={"vipi-scanner": "0.6.1"})
    assert ocr_reuse.full_identity(GOOGLE, label) == base


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
    whole = ocr_reuse.restore(candidate, with_detection=True)
    assert (whole.artifacts / "detection" / "old").is_dir()
    copied = whole.artifacts / "input.png"
    assert copied.stat().st_ino == (source / "input.png").stat().st_ino  # linked
    benchmark.write_json(whole.artifacts / "result.json", {"changed": True})
    assert json.loads((source / "result.json").read_text())["run_id"] == "run-a"
    benchmark.write_json(source / "result.json", {**RESULT, "run_id": "edited"})
    assert ocr_reuse.restore(candidate) is None


def test_worker_reuses_ocr_or_whole_results_and_scans_the_rest(tmp_path, monkeypatch):
    rows = []
    for key in ("reused", "whole", "scanned"):
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
        "detection": None,
        "pipeline_seconds": 4.0,
        "cost": {"estimated_usd": 0.01},
        "elapsed_seconds": 9.0,
    }
    detection = {"verdict": "flagged", "max_score": 0.9, "seconds": 0.3}
    complete = {**earlier, "run_id": "jev-run", "detection": detection}
    restores = []

    def restore(value, with_detection=False):
        restores.append(with_detection)
        return restored

    monkeypatch.setattr(benchmark, "ROOT", tmp_path)
    monkeypatch.setattr(benchmark, "OcrSession", Session)
    monkeypatch.setattr(benchmark, "scan_image", scan)
    monkeypatch.setattr(benchmark, "detect_reused", detect)
    monkeypatch.setattr(benchmark.ocr_reuse, "restore", restore)
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
    reuse = {"reused": earlier, "whole": complete}
    benchmark.worker(output, "cloud-google-jev", rows[:2], reuse)
    assert sessions == [] and scanned == [] and detected == ["jev"]
    assert restores == [False, True]
    assert json.loads((output / "session.json").read_text()) == {"model": "earlier"}
    benchmark.worker(output, "cloud-google-jev", rows[2:], reuse)
    assert len(sessions) == 1 and scanned == ["scanned.png"] and detected == ["jev"]
    reused = json.loads((output / "rows/reused.json").read_text())
    whole = json.loads((output / "rows/whole.json").read_text())
    fresh = json.loads((output / "rows/scanned.json").read_text())
    assert reused["ocr_reused_from"] == {
        "run_id": "earlier-run",
        "configuration": "cloud-google",
        "run": "abc",
        "detection": False,
    }
    assert reused["elapsed_seconds"] == 4.5  # original OCR time + this detection
    assert reused["cost"] == {"estimated_usd": 0.01}
    assert whole["ocr_reused_from"]["detection"] is True
    assert whole["detection"] == detection  # no detection call for this image
    assert whole["elapsed_seconds"] == 9.0  # the earlier image time
    assert whole["cost"] == {"estimated_usd": 0.01}
    assert "ocr_reused_from" not in fresh


def test_reuse_summary_counts_reused_rows_and_unspent_cost(tmp_path):
    rows = {
        "ocr": {
            "ocr_reused_from": {"detection": False},
            "cost": {"estimated_usd": 0.25},
            "detection": {"cost": {"estimated_usd": 0.1}},
        },
        "whole": {
            "ocr_reused_from": {"detection": True},
            "cost": {"estimated_usd": 0.5},
            "detection": {"cost": {"estimated_usd": 0.1}},
        },
        "fresh": {"cost": {"estimated_usd": 1.0}},
    }
    for key, row in rows.items():
        benchmark.write_json(tmp_path / "rows" / f"{key}.json", row)
    cloud = ocr_reuse.summary(tmp_path, local=False)
    assert cloud["images"] == 2 and cloud["with_detection"] == 1
    assert round(cloud["estimated_usd_not_spent_again"], 6) == 0.85
    assert ocr_reuse.summary(tmp_path, local=True)["estimated_usd_not_spent_again"] == 0
    text = "\n".join(ocr_reuse.report_lines(cloud, 3))
    assert "for 2 of 3 images" in text and "1 including detection" in text
    assert "$0.85" in text
    assert ocr_reuse.report_lines(ocr_reuse.summary(tmp_path / "none", False), 3) == []


def test_metric_sources_are_unchanged_by_reuse():
    """Reuse must not touch the scored report, or every baseline turns stale."""
    from research.evaluate import suite

    assert "research/ocr_eval/ocr_reuse.py" not in suite.METRIC_SOURCES
