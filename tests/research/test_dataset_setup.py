import csv
import zipfile

import pytest

from research.datasets import load_hugging_face_dataset, setup


def test_active_sources_uses_only_the_current_ocr_selection(tmp_path):
    catalog = tmp_path / "research/datasets/data/catalog"
    (catalog / "ocr").mkdir(parents=True)
    with (catalog / "ocr/ocr_datasets.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["dataset_id", "available_ocr_images"]
        )
        writer.writeheader()
        writer.writerow({"dataset_id": "core", "available_ocr_images": 10})
    with (catalog / "datasets.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["dataset_id", "name", "local_path", "source_url"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "dataset_id": "core",
                "name": "Core",
                "local_path": "research/datasets/data/external/core",
                "source_url": "https://example.test/core",
            }
        )
        writer.writerow(
            {
                "dataset_id": "archive",
                "name": "Archive",
                "local_path": "research/datasets/data/external/archive",
                "source_url": "https://example.test/archive",
            }
        )

    assert [row["dataset_id"] for row in setup.active_sources(tmp_path)] == ["core"]


def test_setup_skips_present_sources_without_downloads(tmp_path, monkeypatch):
    catalog = tmp_path / "research/datasets/data/catalog"
    (catalog / "ocr").mkdir(parents=True)
    dataset_ids = list(setup.REQUIRED_FILES)
    with (catalog / "ocr/ocr_datasets.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["dataset_id"])
        writer.writeheader()
        writer.writerows({"dataset_id": item} for item in dataset_ids)
    with (catalog / "datasets.csv").open("w", newline="") as handle:
        fields = [
            "dataset_id",
            "name",
            "local_path",
            "size_human",
            "source_url",
            "source_type",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for dataset_id in dataset_ids:
            root = tmp_path / "research/datasets/data/external" / dataset_id
            for relative in setup.REQUIRED_FILES[dataset_id]:
                path = root / relative
                if path.suffix:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("data")
                else:
                    path.mkdir(parents=True, exist_ok=True)
                    (path / ".ready").touch()
            writer.writerow(
                {
                    "dataset_id": dataset_id,
                    "name": dataset_id,
                    "local_path": root.relative_to(tmp_path).as_posix(),
                    "size_human": "1 MiB",
                    "source_url": "https://example.test/source",
                    "source_type": "git_repository",
                }
            )
    monkeypatch.setattr(
        setup,
        "install_source",
        lambda *_args, **_kwargs: pytest.fail("unexpected download"),
    )

    result = setup.setup(tmp_path)

    assert result == [f"ready: {dataset_id}" for dataset_id in sorted(dataset_ids)]


def test_hugging_face_id_requires_a_dataset_repository_url():
    assert (
        setup.hugging_face_id("https://huggingface.co/datasets/facebook/example/")
        == "facebook/example"
    )
    with pytest.raises(ValueError, match="Not a Hugging Face dataset URL"):
        setup.hugging_face_id("https://huggingface.co/models/owner/example")


def test_safe_extract_rejects_paths_outside_destination(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../outside.txt", "unsafe")

    with pytest.raises(ValueError, match="Unsafe path"):
        setup.safe_extract(archive, tmp_path / "output")
    assert not (tmp_path / "outside.txt").exists()


def test_hugging_face_loader_uses_research_external_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(load_hugging_face_dataset, "PROJECT_ROOT", tmp_path)

    assert load_hugging_face_dataset.default_output_dir("owner/dataset") == (
        tmp_path / "research/datasets/data/external/owner/dataset"
    )
