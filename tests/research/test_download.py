import json

import pytest

from research import download


@pytest.mark.parametrize(
    ("arguments", "suites"),
    [
        ([], ["detection_eval", "ocr_eval"]),
        (["detection_eval"], ["detection_eval"]),
        (["ocr_eval"], ["ocr_eval"]),
    ],
)
def test_download_uses_pinned_revision_and_only_suite_data(
    tmp_path, monkeypatch, arguments, suites
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

    download.main(arguments)

    filenames = {"detection_eval": "cases.json", "ocr_eval": "catalog.json"}
    assert calls == [
        {
            "repo_id": "owner/evaluation",
            "repo_type": "dataset",
            "revision": revision,
            "allow_patterns": [
                pattern
                for suite in suites
                for pattern in [f"{suite}/{filenames[suite]}", f"{suite}/images/*"]
            ],
            "local_dir": tmp_path,
            "token": False,
        }
    ]
