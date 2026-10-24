import json

from research.experiments.ocr import ocr_candidate_screen as screen


def test_candidate_registry_excludes_tesseract():
    assert "tesseract" not in screen.MODEL_ORDER
    assert screen.MODEL_ORDER == (
        "ppocr-v6-medium",
        "ppocr-v6-small",
        "ppocr-v6-tiny",
        "surya-ocr-2",
        "lightonocr-3-0.8b",
        "lightonocr-3-1b",
        "lightonocr-3-4b",
        "florence-2-base-ft",
        "florence-2-large-ft",
    )


def test_candidate_manifest_records_generational_model_dependencies(monkeypatch):
    installed_version = screen.importlib.metadata.version
    candidate_versions = {
        "torch": "2.6.0",
        "torchvision": "0.21.0",
        "transformers": "5.8.1",
        "huggingface-hub": "1.32.0",
        "timm": "1.0.20",
        "einops": "0.8.1",
    }

    def version(package):
        if package in candidate_versions:
            return candidate_versions[package]
        return installed_version(package)

    monkeypatch.setattr(screen.importlib.metadata, "version", version)
    versions = screen.candidate_library_versions()

    assert all(
        versions[name]
        for name in ("torch", "torchvision", "transformers", "timm", "einops")
    )


def test_surya_requires_its_ocr_runtime():
    try:
        screen.make_engine("surya-ocr-2", None, 1)
    except RuntimeError as error:
        assert "documented surya-ocr inference runtime" in str(error)
    else:
        raise AssertionError("Surya must not use the generic Transformers adapter.")


def test_unordered_textocr_can_be_scored_without_inventing_reading_order():
    result, expected, matched = screen.candidate_compare(
        {
            "reading_order_known": False,
            "text": "one two",
            "regions": [{"text": "one"}, {"text": "two"}],
        },
        "two one",
        [],
    )

    assert expected == ["one", "two"]
    assert matched == {0, 1}
    assert result["comparison_mode"] == "unordered_token_multiset"


def test_copy_reviewed_audit_reuses_only_matching_sample_subset(tmp_path, monkeypatch):
    old_run = tmp_path / "old"
    new_run = tmp_path / "new"
    old_run.mkdir()
    new_run.mkdir()
    first = {"id": "first", "image": "first.png", "text": "one"}
    second = {"id": "second", "image": "second.png", "text": "two"}
    new_sample = {"id": "new", "image": "new.png", "text": "three"}
    (old_run / "manifest.json").write_text(json.dumps({"samples": [first, second]}))
    (old_run / "reference_audit.json").write_text(
        json.dumps(
            {
                "first": {"status": "reviewed", "notes": "same"},
                "second": {"status": "reviewed", "notes": "same"},
            }
        )
    )
    (new_run / "manifest.json").write_text(json.dumps({"samples": [first, new_sample]}))
    (new_run / "reference_audit.json").write_text(
        json.dumps(
            {
                "first": {"status": "pending", "notes": ""},
                "new": {"status": "pending", "notes": ""},
            }
        )
    )
    monkeypatch.setattr(screen, "OLD_AUDIT_RUN", old_run)

    reused = screen.copy_reviewed_audit(new_run)
    audit = json.loads((new_run / "reference_audit.json").read_text())

    assert reused == 1
    assert audit["first"] == {"status": "reviewed", "notes": "same"}
    assert audit["new"] == {"status": "pending", "notes": ""}


def test_lighton_grounding_parser_converts_boxes_and_joins_text():
    result = screen.parse_lighton_grounding(
        "![title](100,200,900,400) Hello world\n![text](0,500,500,700) Read this",
        (1000, 800),
    )

    assert result["text"] == "Hello world\nRead this"
    assert result["regions"] == [
        {
            "text": "Hello world",
            "polygon": [[100, 160], [900, 160], [900, 320], [100, 320]],
            "label": "title",
        },
        {
            "text": "Read this",
            "polygon": [[0, 400], [500, 400], [500, 560], [0, 560]],
            "label": "text",
        },
    ]


def test_lighton_grounding_parser_keeps_text_when_no_boxes_exist():
    assert screen.parse_lighton_grounding("plain OCR text", (200, 100)) == {
        "text": "plain OCR text",
        "regions": [],
    }
