import json

import pytest
from PIL import Image

from ocr_pipeline.catalog import Catalog


def test_catalog_filter_search_pagination_and_stable_ids(dataset_repository):
    catalog = Catalog(dataset_repository)
    result = catalog.listing("vpi_bench", limit=1)
    assert result["total"] == 2 and result["catalog_total"] == 3
    assert len(result["items"]) == 1 and len(result["matching_ids"]) == 2
    assert catalog.listing(query="missing")["items"][0]["name"] == "1.png"
    identifier = result["items"][0]["id"]
    assert catalog.for_path(catalog.path(identifier))["text"] == "Required"
    index = dataset_repository / "datasets/catalog/ocr/ocr_metadata.json"
    before = index.read_bytes()
    index.write_text(json.dumps(list(reversed(json.loads(before)))))
    assert set(Catalog(dataset_repository).items) == set(catalog.items)
    with pytest.raises(ValueError):
        catalog.get("../../etc/passwd")
    with pytest.raises(ValueError):
        catalog.listing("unknown")


def test_catalog_cannot_serve_indexed_paths_outside_datasets(dataset_repository):
    index = dataset_repository / "datasets/catalog/ocr/ocr_metadata.json"
    records = json.loads(index.read_text())
    records[0]["image"] = "datasets/../../outside.txt"
    index.write_text(json.dumps(records))
    catalog = Catalog(dataset_repository)
    identifier = next(iter(catalog.items))
    with pytest.raises(ValueError, match="unavailable"):
        catalog.path(identifier)


def test_reference_word_regions_follow_exif_orientation(dataset_repository):
    directory = dataset_repository / "datasets/catalog/ocr"
    image = dataset_repository / "datasets/external/examples/oriented.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (100, 60)).save(image, exif=exif)
    path = image.relative_to(dataset_repository).as_posix()
    (directory / "ocr_metadata.json").write_text(
        json.dumps([{"image": path, "text": "hello", "category": "textocr"}])
    )
    (directory / "ocr_selection_report.json").write_text(
        json.dumps(
            {
                "selected_references": [
                    {
                        "image": path,
                        "reading_order_known": False,
                        "regions": [{"text": "hello", "bbox_xywh": [10, 20, 30, 10]}],
                    }
                ]
            }
        )
    )
    catalog = Catalog(dataset_repository)
    target = catalog.reference(next(iter(catalog.items)))
    assert target["regions"][0]["input_polygon"] == [
        [40, 10],
        [40, 40],
        [30, 40],
        [30, 10],
    ]
    assert not target["reading_order_known"]
