import json

from research import download


def test_download_fetches_the_pinned_dataset_into_research_dataset(
    tmp_path, monkeypatch
):
    revision = "0123456789abcdef0123456789abcdef01234567"
    (tmp_path / "dataset.json").write_text(
        json.dumps({"repo_id": "owner/evaluation", "revision": revision})
    )
    monkeypatch.setattr(download, "__file__", str(tmp_path / "download.py"))
    calls = []
    monkeypatch.setattr(
        download, "snapshot_download", lambda **options: calls.append(options)
    )

    download.main([])

    assert calls == [
        {
            "repo_id": "owner/evaluation",
            "repo_type": "dataset",
            "revision": revision,
            "allow_patterns": ["catalog.json", "vocabulary.json", "images/*"],
            "local_dir": tmp_path / "dataset",
            "token": False,
        }
    ]
