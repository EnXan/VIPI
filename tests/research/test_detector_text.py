"""Detector-only evaluation on retained OCR text (ADR 0074)."""

import json

import pytest

from research.evaluate import detector_text


def write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def detection_inputs(artifacts, *texts):
    write(
        artifacts / "detection" / "check" / "inputs.json",
        {
            "evidence": {"readings": [{"text": text} for text in texts]},
            "jobs": [{"text": text} for text in texts],
        },
    )


@pytest.fixture
def source_run(tmp_path):
    """A complete source run with two images, retained rows and detector inputs."""
    runs = tmp_path / "runs"
    directory = runs / "source-run"
    rows = []
    for key, label in (("a", "injection"), ("b", "benign")):
        artifacts = tmp_path / "cache" / key
        detection_inputs(artifacts, f"text {key}")
        write(
            directory / "benchmark" / "cloud-mistral" / "rows" / f"{key}.json",
            {
                "key": key,
                "status": "completed",
                "artifacts": str(artifacts),
                "result_sha256": "x",
            },
        )
        rows.append({"key": key, "label": label})
    write(
        directory / "report.json",
        {
            "inference_complete": True,
            "configurations": {"cloud-mistral": {"rows": rows}},
        },
    )
    return runs


def test_source_rows_join_retained_rows_with_labels(source_run):
    configuration, rows = detector_text.source_rows(source_run / "source-run")

    assert configuration == "cloud-mistral"
    assert [(row["key"], row["label"], row["status"]) for row in rows] == [
        ("a", "injection", "completed"),
        ("b", "benign", "completed"),
    ]


def test_incomplete_source_run_is_rejected(source_run):
    report = source_run / "source-run" / "report.json"
    write(report, {**json.loads(report.read_text()), "inference_complete": False})

    with pytest.raises(ValueError, match="not complete"):
        detector_text.source_rows(source_run / "source-run")


def test_input_texts_reads_the_newest_check(tmp_path):
    detection_inputs(tmp_path, "older")
    newer = tmp_path / "detection" / "later" / "inputs.json"
    write(
        newer,
        {
            "evidence": {"readings": [{"text": "newer"}]},
            "jobs": [{"text": "ne"}, {"text": "wer"}],
        },
    )

    assert detector_text.input_texts(tmp_path) == ["newer"]
    assert detector_text.input_texts(tmp_path / "missing") is None


def completed(key, label, verdict, same=True, errors=()):
    return {
        "key": key,
        "label": label,
        "status": "completed",
        "detection": {"verdict": verdict, "seconds": 1.0, "errors": list(errors)},
        "same_text_as_source": same,
    }


def test_summary_scores_verdicts_and_counts_changed_text():
    rows = [
        completed("a", "injection", "injection_detected"),
        completed("b", "injection", None),
        completed("c", "benign", "injection_detected", same=False),
        {"key": "d", "label": "benign", "status": "failed"},
    ]

    summary = detector_text.summarize(rows)

    assert summary["same_text_as_source"] == 2
    assert summary["text_differs"] == 1
    assert summary["failed"] == 1
    assert summary["detection"]["recall"] == 0.5
    assert summary["detection"]["false_positive_rate"] == 0.5
    assert summary["detection"]["no_result"] == 2


def test_run_detects_every_image_and_resumes(source_run, tmp_path, monkeypatch):
    calls = []

    def fake_detect(row, detector, options, provider):
        calls.append(row["key"])
        verdict = (
            "injection_detected"
            if row["label"] == "injection"
            else "no_injection_detected"
        )
        return completed(row["key"], row["label"], verdict)

    monkeypatch.setattr(detector_text, "detect_row", fake_detect)
    monkeypatch.setattr(detector_text, "prepare_provider", lambda name, path: object())
    monkeypatch.setattr(detector_text.benchmark, "provenance", lambda: {})
    output = tmp_path / "out"

    target, summary = detector_text.run(
        "source-run",
        "wolf-defender",
        runs_directory=source_run,
        output_directory=output,
    )
    detector_text.run(
        "source-run",
        "wolf-defender",
        runs_directory=source_run,
        output_directory=output,
    )

    assert target == output / "source-run--wolf-defender"
    assert calls == ["a", "b"]
    assert summary["summary"]["detection"]["recall"] == 1.0
    assert summary["summary"]["detection"]["false_positive_rate"] == 0.0
    assert (
        json.loads((target / "summary.json").read_text())["detector"] == "wolf-defender"
    )


def test_run_refuses_a_different_request_in_the_same_folder(
    source_run, tmp_path, monkeypatch
):
    monkeypatch.setattr(detector_text, "prepare_provider", lambda name, path: object())
    monkeypatch.setattr(detector_text.benchmark, "provenance", lambda: {})
    monkeypatch.setattr(
        detector_text, "detect_row", lambda *args: completed("a", "injection", None)
    )
    output = tmp_path / "out"
    detector_text.run(
        "source-run",
        "wolf-defender",
        runs_directory=source_run,
        output_directory=output,
    )

    with pytest.raises(ValueError, match="different request"):
        detector_text.run(
            "source-run",
            "wolf-defender",
            runs_directory=source_run,
            output_directory=output,
            threshold=50,
        )


def test_unknown_detector_is_rejected(source_run):
    with pytest.raises(ValueError, match="Choose one of"):
        detector_text.run("source-run", "granite", runs_directory=source_run)


def test_rows_with_detector_errors_count_as_failed_and_run_again(
    source_run, tmp_path, monkeypatch
):
    attempts = []

    def flaky(row, detector, options, provider):
        attempts.append(row["key"])
        errors = (
            ["MPS backend out of memory"] if attempts.count(row["key"]) == 1 else []
        )
        return completed(
            row["key"],
            row["label"],
            None if errors else "no_injection_detected",
            errors=errors,
        )

    monkeypatch.setattr(detector_text, "detect_row", flaky)
    monkeypatch.setattr(detector_text, "prepare_provider", lambda name, path: object())
    monkeypatch.setattr(detector_text.benchmark, "provenance", lambda: {})
    output = tmp_path / "out"

    _, first = detector_text.run(
        "source-run", "d1", runs_directory=source_run, output_directory=output
    )
    _, second = detector_text.run(
        "source-run", "d1", runs_directory=source_run, output_directory=output
    )

    assert first["summary"]["failed"] == 2
    assert second["summary"]["failed"] == 0
    assert attempts == ["a", "b", "a", "b"]
