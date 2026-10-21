import json
from pathlib import Path
import subprocess

from PIL import Image
import pytest

from vipi.detection.verdict import summarize, validate_thresholds
from vipi.__main__ import main
from vipi.scanner import scan, scan_image
from vipi.results import ScanResult, OcrResult, DetectionResult
from vipi.inputs import select_images
from vipi.inputs.git import git


def image(path, color="white"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path)
    return path


def commit(repository, message):
    subprocess.run(["git", "add", "--all"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=VIPI test",
            "-c",
            "user.email=vipi@example.test",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            message,
        ],
        cwd=repository,
        check=True,
    )


@pytest.fixture
def repository(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    image(root / "unchanged.png")
    image(root / "modified.png")
    image(root / "deleted.png")
    image(root / "renamed.png")
    (root / "notes.txt").write_text("base")
    commit(root, "base")
    subprocess.run(["git", "checkout", "-qb", "feature"], cwd=root, check=True)
    image(root / "images/new with\nnewline.png", "red")
    image(root / "modified.png", "blue")
    (root / "deleted.png").unlink()
    (root / "renamed.png").rename(root / "moved.png")
    (root / "notes.txt").write_text("branch")
    (root / "link.png").symlink_to(root / "unchanged.png")
    commit(root, "feature")
    subprocess.run(["git", "checkout", "-q", "main"], cwd=root, check=True)
    image(root / "main-only.png")
    commit(root, "main advances independently")
    subprocess.run(["git", "checkout", "-q", "feature"], cwd=root, check=True)
    monkeypatch.chdir(root)
    return root


def test_diff_uses_branch_changes_and_committed_bytes(repository):
    committed = (repository / "modified.png").read_bytes()
    image(repository / "modified.png", "green")
    image(repository / "untracked.png")
    selection = select_images([Path(".")], diff="main")
    assert {
        source.path.relative_to(repository).as_posix() for source in selection.images
    } == {
        "modified.png",
        "images/new with\nnewline.png",
        "moved.png",
    }
    source = next(
        source for source in selection.images if source.path.name == "modified.png"
    )
    assert git(repository, "cat-file", "blob", source.blob) == committed
    assert selection.errors == [
        {
            "path": str(repository / "link.png"),
            "error": "Image is not a regular Git file.",
        }
    ]
    assert selection.diff["head"] != selection.diff["merge_base"]
    assert any(item["path"].endswith("notes.txt") for item in selection.skipped)


def test_diff_limits_scopes_and_accepts_committed_file_missing_from_worktree(
    repository,
):
    (repository / "images/new with\nnewline.png").unlink()
    selection = select_images([Path("images")], diff="main")
    assert [source.path.name for source in selection.images] == [
        "new with\nnewline.png"
    ]
    assert not selection.errors


def test_diff_invalid_reference_and_outside_scope_fail(repository):
    with pytest.raises(ValueError, match="Git comparison failed"):
        select_images([Path(".")], diff="nonexistent")
    with pytest.raises(ValueError, match="inside"):
        select_images([repository.parent], diff="main")


def test_discovery_is_recursive_deduplicated_and_does_not_follow_symlinks(tmp_path):
    first = image(tmp_path / "a.PNG")
    second = image(tmp_path / "nested/b.webp")
    image(tmp_path / ".venv/ignored.png")
    image(tmp_path / "cache/ignored.png")
    (tmp_path / "readme.txt").write_text("ignored")
    (tmp_path / "linked.png").symlink_to(first)
    selection = select_images([tmp_path, first], excluded=[tmp_path / "cache"])
    assert [source.path for source in selection.images] == [first, second]
    assert len(selection.errors) == 1
    assert len(selection.skipped) == 3


def test_explicit_image_under_directory_alias_is_accepted(tmp_path):
    real = image(tmp_path / "real/image.png")
    (tmp_path / "alias").symlink_to(real.parent, target_is_directory=True)
    selection = select_images([tmp_path / "alias/image.png"])
    assert [source.path for source in selection.images] == [real]
    assert not selection.errors


@pytest.mark.parametrize(
    "threshold,score,verdict",
    [
        (0, 0, "flagged"),
        (0.8, 0.8, "flagged"),
        (0.8, 0.799, "not_flagged"),
        (1, 1, "flagged"),
        (1, 0.999, "not_flagged"),
    ],
)
def test_single_threshold_boundaries(threshold, score, verdict):
    limits = validate_thresholds(
        {"version": "test", "signals": {"jev": {"threshold": threshold}}}
    )
    result = summarize(
        [{"signal": "jev", "status": "completed", "probability": score}],
        ["jev"],
        limits,
    )
    assert result["verdict"] == verdict
    incomplete = summarize([{"signal": "jev", "status": "error"}], ["jev"], limits)
    assert incomplete["verdict"] == "unclear"


@pytest.fixture
def scanner_runtime(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("vipi.ocr.models.validate_model", lambda *args, **kwargs: None)
    # Keep real image decoding, orchestration, persistence, assembly and detection;
    # replace inference and limit views so tests do not require model weights.
    from vipi.ocr.transforms import views_for_size

    monkeypatch.setattr(
        "vipi.ocr.pipeline.production_passes_for_size",
        lambda *args: [(views_for_size(*args)[0], "unchanged")],
    )

    class Engine:
        def recognize(self, raster):
            return {
                "text": "Read this label",
                "regions": [
                    {
                        "text": "Read this label",
                        "polygon": [[0, 0], [25, 0], [25, 15], [0, 15]],
                        "confidence": 0.99,
                    }
                ],
            }

    engines = []

    def create_engine(*args, **kwargs):
        engines.append(kwargs)
        return Engine()

    monkeypatch.setattr("vipi.ocr.engine_pool.create_engine", create_engine)

    class Provider:
        key = "fixture-secret-not-for-reports"
        model = "fixture-detector"
        identity = "fixture-v1"

        def __init__(self):
            self.score = 0.8
            self.failure = False
            self.calls = []

        def check(self, payload, image=None):
            self.calls.append(payload)
            if self.failure:
                raise ValueError("Fixture provider failure")
            return {"status": "completed", "probability": self.score}

    provider = Provider()
    monkeypatch.setattr(
        "vipi.detection.providers.create_provider", lambda *args: provider
    )
    return provider, engines


def test_scan_runs_shared_pipeline_sequentially_and_emits_json(
    tmp_path, scanner_runtime
):
    provider, engines = scanner_runtime
    image(tmp_path / "images/a.png")
    image(tmp_path / "images/b.png")
    output = tmp_path / "report.json"
    assert main(["scan", "images", "--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["summary"]["detections"] == report["summary"]["completed"] == 2
    assert report["threshold"] == 80
    assert report["ocr"]["model"] == "ppocr-v6"
    assert report["ocr"]["mode"] == "quality"
    assert report["ocr_mode"] == "quality"
    assert report["ocr_model"] == "ppocr-v6"
    assert report["ocr"]["ocr_profile"] == "reduced-transforms-v1"
    assert report["ocr"]["workers"] == 1 and report["ocr"]["backend"] == "cpu"
    assert report["files"][0]["ocr_profile"] == "reduced-transforms-v1"
    assert report["files"][0]["ocr_passes"] == 1
    assert len(engines) == 1  # One model session is reused across both images.
    assert len(provider.calls) == 2
    assert "fixture-secret" not in output.read_text()
    assert all(Path(item["artifacts"]).is_dir() for item in report["files"])


@pytest.mark.parametrize(
    ("options", "mode", "model"),
    [
        (["--ocr-mode", "fast"], "fast", "ppocr-v6-tiny"),
        (["--ocr-mode", "balanced"], "balanced", "ppocr-v6-small"),
        (
            ["--ocr-mode", "fast", "--ocr-model", "ppocr-v6-medium"],
            "fast",
            "ppocr-v6",
        ),
    ],
)
def test_scan_selects_ocr_mode_and_explicit_model_override(
    tmp_path, scanner_runtime, options, mode, model
):
    image(tmp_path / "label.png")
    output = tmp_path / "report.json"

    assert main(["scan", "label.png", *options, "--output", str(output)]) == 1

    report = json.loads(output.read_text())
    assert report["ocr_mode"] == mode
    assert report["ocr_model"] == model
    assert report["ocr"]["mode"] == mode
    assert report["ocr"]["model"] == model


def test_verbose_scan_prints_extracted_text(tmp_path, scanner_runtime, capsys):
    image(tmp_path / "label.png")

    assert main(["scan", "label.png", "--verbose"]) == 1

    output = capsys.readouterr().out
    assert "VIPI" in output
    assert "Extracted text from " in output
    assert "/label.png:" in output
    assert "Read this label" in output
    assert "Detection found" in output
    assert "1/1 images completed" in output


def test_threshold_override_and_incomplete_scan_take_precedence(
    tmp_path, scanner_runtime
):
    provider, _ = scanner_runtime
    image(tmp_path / "valid.png")
    assert main(["scan", "valid.png", "--threshold", "90"]) == 0
    (tmp_path / "invalid.png").write_text("not a raster")
    report = scan([tmp_path / "valid.png", tmp_path / "invalid.png"])
    assert report["exit_code"] == 2
    assert report["summary"]["detections"] == 1
    assert report["summary"]["failed"] == 1
    provider.failure = True
    report = scan([tmp_path / "valid.png"])
    assert report["exit_code"] == 2
    assert report["files"][0]["errors"] == ["Fixture provider failure"]


def test_empty_diff_needs_no_models_or_secrets(repository, monkeypatch):
    def unexpected(*args):
        pytest.fail("An empty diff must not prepare any models or providers")

    monkeypatch.setattr("vipi.detection.providers.create_provider", unexpected)
    report = scan([Path(".")], diff="HEAD")
    assert report["exit_code"] == 0
    assert report["summary"]["selected"] == 0


def test_diff_scan_processes_commit_even_when_worktree_image_is_invalid(
    repository, scanner_runtime, monkeypatch
):
    monkeypatch.chdir(repository)
    path = repository / "modified.png"
    path.write_text("uncommitted broken image")
    report = scan([path], diff="main")
    assert report["exit_code"] == 1
    with Image.open(Path(report["files"][0]["artifacts"]) / "input.png") as raster:
        assert raster.getpixel((0, 0)) == (0, 0, 255)


def test_missing_credentials_still_write_an_error_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    monkeypatch.setenv("JEV_API_KEY", "")
    image(tmp_path / "input.png")
    assert main(["scan", "input.png", "--output", "report.json"]) == 2
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["exit_code"] == 2
    assert report["summary"]["not_scanned"] == 1


def test_no_text_is_not_a_clean_scan(tmp_path, scanner_runtime, monkeypatch):
    class EmptyEngine:
        def recognize(self, raster):
            return {"text": "", "regions": []}

    monkeypatch.setattr(
        "vipi.ocr.engine_pool.create_engine", lambda *args, **kwargs: EmptyEngine()
    )
    report = scan([image(tmp_path / "blank.png")])
    assert report["exit_code"] == 2
    assert report["files"][0]["verdict"] == "unclear"
    assert report["files"][0]["errors"]


def test_missing_credentials_fail_before_ocr(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    monkeypatch.setenv("JEV_API_KEY", "")
    path = image(tmp_path / "input.png")
    report = scan([path])
    assert report["exit_code"] == 2
    assert report["summary"]["not_scanned"] == 1
    assert "TYPESAFE_API_KEY" in report["errors"][0]["error"]
    assert report["ocr"] is None


def test_output_cannot_overwrite_source(tmp_path, scanner_runtime):
    path = image(tmp_path / "input.png")
    before = path.read_bytes()
    assert main(["scan", str(path), "--output", str(path)]) == 2
    assert path.read_bytes() == before


@pytest.mark.parametrize("value", ["-1", "101", "nan", "inf", "bad"])
def test_invalid_threshold_is_rejected(value):
    with pytest.raises(SystemExit) as error:
        main(["scan", "image.png", "--threshold", value])
    assert error.value.code == 2


def test_setup_only_prepares_default_ocr_and_selected_local_detector(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(
        "vipi.ocr.models.prepare_models",
        lambda path, model, **kwargs: calls.append((path, model)),
    )
    monkeypatch.setattr(
        "vipi.detection.providers.prompt_guard.prepare_model",
        lambda path, **kwargs: calls.append((path, kwargs)),
    )
    assert main(["setup"]) == 0
    assert len(calls) == 1 and calls[0][1] is None
    assert "Models ready" in capsys.readouterr().out
    assert main(["setup", "--ocr-mode", "fast"]) == 0
    assert calls[-1][1] == "ppocr-v6-tiny"
    assert main(["setup", "--ocr-model", "ppocr-v6-small"]) == 0
    assert calls[-1][1] == "ppocr-v6-small"
    assert main(["setup", "--detector", "prompt-guard"]) == 0
    assert calls[-1][1]["revision"] == "a8ded8e697ce7c355e395a0df51f94adb4a2fd27"


def test_direct_scan_accepts_bytes_and_does_not_reload_ocr_json(
    tmp_path, scanner_runtime, monkeypatch
):
    provider, _ = scanner_runtime

    def unexpected(*args):
        pytest.fail("The scanner must pass its OCR result directly to detection")

    monkeypatch.setattr("vipi.detection.pipeline.load_evidence", unexpected)
    events = []
    result = scan_image(
        image(tmp_path / "label.png").read_bytes(),
        provider=provider,
        on_event=events.append,
    )
    assert isinstance(result, ScanResult)
    assert isinstance(result.ocr, OcrResult)
    assert isinstance(result.detection, DetectionResult)
    assert result.detection.verdict == "flagged"
    assert any(event["type"] == "run_completed" for event in events)
    assert any(event["type"] == "detection_completed" for event in events)
