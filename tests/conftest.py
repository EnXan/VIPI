import json

import pytest
from PIL import Image


@pytest.fixture
def dataset_repository(tmp_path):
    directory = tmp_path / "datasets/catalog/ocr"
    directory.mkdir(parents=True)
    image_root = tmp_path / "datasets/external/examples"
    image_root.mkdir(parents=True)
    records = []
    for i, text in enumerate(["Required", "Missing target", "Failure target"]):
        path = image_root / f"{i}.png"
        Image.new("RGB", (16, 12), "white").save(path)
        records.append(
            {
                "image": path.relative_to(tmp_path).as_posix(),
                "text": text,
                "category": "vpi_bench" if i < 2 else "mm_safetybench",
            }
        )
    (directory / "ocr_metadata.json").write_text(json.dumps(records))
    return tmp_path
