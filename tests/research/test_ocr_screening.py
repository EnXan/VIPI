"""Experiment checks: honest subset assembly, leakage protection and resume."""

import importlib.util
import json
from pathlib import Path
import sys

from PIL import Image
import pytest

from vipi.ocr.transforms import views_for_size

spec = importlib.util.spec_from_file_location(
    "ocr_screening", Path(__file__).parents[2] / "research/experiments/ocr/ocr_screening.py"
)
screening = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = screening
spec.loader.exec_module(screening)

audit_spec = importlib.util.spec_from_file_location(
    "analyze_ocr_screening",
    Path(__file__).parents[2] / "research/experiments/ocr/analyze_ocr_screening.py",
)
audit = importlib.util.module_from_spec(audit_spec)
audit_spec.loader.exec_module(audit)


def test_anamorpher_payload_variants_never_cross_split():
    assert screening.split_for("anamorpher_payload_blue") == "development"
    assert screening.split_for("anamorpher_payload_orange") == "holdout"
    assert screening.split_for("source:group") == screening.split_for("source:group")


def test_subset_assembly_does_not_claim_oracle_union_as_final_text():
    def step(identifier, text, confidence):
        box = [[0, 0], [100, 0], [100, 20], [0, 20]]
        return {
            "id": identifier,
            "view_id": identifier,
            "text": text,
            "regions": [
                {
                    "text": text,
                    "polygon": box,
                    "input_polygon": box,
                    "confidence": confidence,
                    "level": "line",
                    "line_id": "0",
                }
            ],
            "timing": {"ocr_seconds": 1},
        }

    row = {
        "sample": {"reference": {"text": "BLUE 42", "reading_order_known": True}},
        "steps": [step("a", "BLUE", 0.99), step("b", "42", 0.7)],
        "matches": {"a": {0}, "b": {1}},
    }
    result = screening.selected_summary(row, {"a", "b"})
    assert result["oracle_tokens_across_steps"] == 2
    assert result["final"]["matched"] == 1
    assert not result["final"]["valid"]
    assert screening.selected_summary(row, {"b"})["text"] == "42"


def test_resume_reuses_saved_steps_without_reinitializing_ocr(tmp_path, monkeypatch):
    image = tmp_path / "input.png"
    Image.new("RGB", (16, 12), "white").save(image)
    sample = {"id": "test", "image": str(image), "dimensions": [16, 12]}
    manifest = {
        "samples": [sample],
        "model": "ppocr-v6",
        "workers": 1,
        "backend": "cpu",
    }
    monkeypatch.setattr(screening, "check_manifest", lambda _: manifest)
    small_views = views_for_size(16, 12)[:2]
    monkeypatch.setattr(screening, "views_for_size", lambda *_: small_views)
    calls = []

    class Engine:
        def recognize(self, raster):
            calls.append(raster.size)
            # A previous successful pass must already exist before the next one.
            if len(calls) == 2:
                assert (tmp_path / "samples/test/steps/0001.json").is_file()
            return {"text": "", "regions": []}

    def factory(*args, **kwargs):
        return Engine()

    monkeypatch.setattr("vipi.ocr.engine_pool.create_engine", factory)
    assert screening.run_image(tmp_path, "test", "views") == 0
    assert len(calls) == 2
    assert screening.run_image(tmp_path, "test", "views") == 0
    assert len(calls) == 2
    status = json.loads((tmp_path / "samples/test/views_status.json").read_text())
    assert status["reused"] == 2 and status["state"] == "completed"


def test_incomplete_views_cannot_be_reported_as_finished(tmp_path):
    sample = {"id": "missing", "dimensions": [16, 12]}
    with pytest.raises(ValueError, match="Incomplete base views"):
        screening.load_samples(tmp_path, {"samples": [sample]})


def test_profile_caps_large_upscaling_without_hiding_original_or_downscales(tmp_path):
    profile = {
        "profiles": {
            "candidate": {
                "view_ids": [
                    "original-unchanged-1x",
                    "pillow-bicubic-2x",
                    "opencv-nearest-0.25x",
                ],
                "filters": ["unchanged"],
                "two_times_max_pixels": 8_000_000,
            }
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(profile))
    large = screening.schedule({"dimensions": [3200, 3200]}, "candidate", tmp_path)
    small = screening.schedule({"dimensions": [1024, 768]}, "candidate", tmp_path)
    assert {v.id for _, v, _ in large} == {
        "original-unchanged-1x",
        "opencv-nearest-0.25x",
    }
    assert {v.id for _, v, _ in small} == {
        "original-unchanged-1x",
        "opencv-nearest-0.25x",
        "pillow-bicubic-2x",
    }
    assert all(name == "unchanged" and v.crop is None for _, v, name in large + small)


@pytest.mark.parametrize("changed_setting", ["profile", "environment"])
def test_resume_rejects_changed_frozen_profile(tmp_path, monkeypatch, changed_setting):
    monkeypatch.setattr(screening, "source_hashes", lambda: {})
    manifest = {
        "source_hashes": {},
        "models": {},
        "samples": [],
        "profiles": {"candidate": {"two_times_max_pixels": 8_000_000}},
        "environment": {"KMP_USE_SHM": "0"},
    }
    manifest["protocol_sha256"] = screening.protocol_fingerprint(manifest)
    file = tmp_path / "manifest.json"
    file.write_text(json.dumps(manifest))
    screening.check_manifest(tmp_path)
    if changed_setting == "profile":
        manifest["profiles"]["candidate"]["two_times_max_pixels"] = 80_000_000
    else:
        manifest["environment"]["KMP_USE_SHM"] = "1"
    file.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="protocol changed"):
        screening.check_manifest(tmp_path)


def test_audit_keeps_native_words_in_a_compact_line_without_inventing_readings():
    from research.evaluation.metrics import final_observations
    from vipi.ocr.merge import assemble

    def word(text, x):
        box = [[x, 0], [x + 40, 0], [x + 40, 20], [x, 20]]
        return {
            "text": text,
            "polygon": box,
            "input_polygon": box,
            "confidence": 0.9,
            "line_id": "0",
            "level": "word",
        }

    step = {
        "id": "0001",
        "view_id": "original",
        "text": "MCLARENVALE",
        "regions": [word("MCLAREN", 0), word("VALE", 50)],
    }
    _, regions = assemble([step])
    assert [x["text"] for x in final_observations(regions, [step])] == [
        "MCLAREN",
        "VALE",
    ]
    observations, repaired = audit.native_final_observations(regions, [step])
    assert [x["text"] for x in observations] == ["MCLAREN", "VALE"]
    assert repaired == 1

    regions[0]["text"] = "MCLAREN OTHER"
    observations, _ = audit.native_final_observations(regions, [step])
    assert "VALE" not in [x["text"] for x in observations]
