"""The one dataset catalog: listing, paths, OCR references and verdicts."""

import json

import pytest

from research.catalog import Catalog


@pytest.fixture
def catalog(draft_dir):
    return Catalog(draft_dir)


def test_missing_dataset_says_how_to_get_it(tmp_path):
    with pytest.raises(ValueError, match="research.download"):
        Catalog(tmp_path)


def test_duplicate_ids_are_rejected(draft_dir):
    path = draft_dir / "catalog.json"
    entries = json.loads(path.read_text())
    path.write_text(json.dumps([*entries, entries[0]]))
    with pytest.raises(ValueError, match="Duplicate entry"):
        Catalog(draft_dir)


def test_search_filters_by_label_content_source_and_text(catalog):
    assert {entry["id"] for entry in catalog.search(label="benign")} == {"photo"}
    assert [entry["id"] for entry in catalog.search(content="text_image")] == ["typo"]
    assert len(catalog.search(source="sting")) == 1
    assert [entry["id"] for entry in catalog.search("main street")] == ["photo"]
    assert catalog.search(label="injection", content="real_world") == []
    with pytest.raises(ValueError, match="Filter by"):
        catalog.search(category="textocr")
    assert catalog.counts("label") == {"injection": 1, "benign": 1, "jailbreak": 1}


def test_paths_stay_inside_the_dataset(catalog, draft_dir):
    assert catalog.path("photo").is_file()
    catalog.items["photo"]["image"] = "../outside.png"
    with pytest.raises(ValueError, match="unavailable"):
        catalog.path("photo")
    with pytest.raises(ValueError, match="not in the dataset"):
        catalog.get("missing")


def test_reference_maps_regions_and_marks_payload_fragments(catalog):
    photo = catalog.reference("photo")
    assert photo["text"] == "Main Street"
    assert photo["regions"] == [
        {"text": "Main", "input_polygon": [[0, 0], [4, 0], [4, 4], [0, 4]]}
    ]
    assert photo["regions_are_independent"] is False
    sting = catalog.reference(catalog.search(source="sting")[0]["id"])
    assert sting["scope"] == "primary_visible_payload"
    assert sting["regions_are_independent"] is True


def test_entries_without_reference_text_have_no_reference(catalog):
    catalog.items["photo"]["ocr_reference"] = None
    assert catalog.reference("photo") is None
