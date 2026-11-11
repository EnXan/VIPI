"""Contribute images: add them, edit their texts and submit only your changes."""

import copy
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from research.curation import contribute
from research.curation.__main__ import main
from research.curation.store import CurationStore
from flask import Flask

from research.workbench import curation_routes

SOURCE = {
    "dataset": "my_screenshots",
    "license": "CC-BY-4.0",
    "provenance": "Screenshots of my test web app",
}


def catalog(directory):
    return json.loads((directory / "catalog.json").read_text())


def png(path, color):
    Image.new("RGB", (8, 8), color).save(path)
    return path


def test_add_copies_images_and_creates_unreviewed_entries(draft_dir, tmp_path):
    first = png(tmp_path / "login.png", "purple")
    second = png(tmp_path / "copy.png", "purple")  # same bytes as the first
    added, skipped = contribute.add_images(
        [first, second], draft_dir, label="benign", content="web_page", source=SOURCE
    )
    assert len(added) == 1 and skipped == [(str(second), added[0]["id"])]
    entry = catalog(draft_dir)[-1]
    assert entry["image"] == f"images/{entry['id']}.png"
    assert (draft_dir / entry["image"]).read_bytes() == first.read_bytes()
    assert entry["curation"]["reviewed"] is False
    assert entry["source"]["sample_id"] == "my_screenshots:login"
    assert entry["ocr_reference"] is None and entry["cases"] == []


def test_add_rejects_unknown_values_missing_source_and_other_files(draft_dir, tmp_path):
    image = png(tmp_path / "a.png", "navy")
    before = catalog(draft_dir)
    with pytest.raises(ValueError, match="content has values outside"):
        contribute.add_images(
            [image], draft_dir, label="benign", content="poem", source=SOURCE
        )
    with pytest.raises(ValueError, match="license"):
        contribute.add_images(
            [image],
            draft_dir,
            label="benign",
            content="web_page",
            source={**SOURCE, "license": " "},
        )
    (tmp_path / "notes.txt").write_text("x")
    with pytest.raises(ValueError, match="PNG, JPEG or WEBP"):
        contribute.add_images(
            [tmp_path / "notes.txt"],
            draft_dir,
            label="benign",
            content="web_page",
            source=SOURCE,
        )
    assert catalog(draft_dir) == before


def test_add_command_reports_added_and_skipped(draft_dir, tmp_path, capsys):
    image = png(tmp_path / "shot.png", "teal")
    arguments = [
        "add", str(image), "--label", "injection", "--content", "web_page",
        "--source", "mine", "--license", "CC0-1.0", "--provenance", "made by me",
        "--dir", str(draft_dir),
    ]  # fmt: skip
    assert main(arguments) == 0
    assert main(arguments) == 0
    output = capsys.readouterr().out
    assert "added 1 entries" in output and "already in the dataset" in output


def edited(entries, key, **changes):
    return [{**entry, **changes} if entry["id"] == key else entry for entry in entries]


def dropped(entries, key):
    return [
        {**entry, "curation": {**entry["curation"], "decision": "drop", "reason": "x"}}
        if entry["id"] == key
        else entry
        for entry in entries
    ]


def test_changes_list_added_changed_and_dropped_entries(draft_catalog):
    pinned = draft_catalog[0]
    new = {**pinned[0], "id": "new", "image_sha256": "n"}
    local = dropped(edited(pinned, "photo", payload="changed"), "typo") + [new]
    assert contribute.changes(local, pinned) == {
        "added": ["new"],
        "changed": ["photo"],
        "removed": ["typo"],
    }


def test_merge_applies_your_changes_to_main_and_reports_conflicts(draft_catalog):
    pinned = draft_catalog[0]
    other = {**pinned[0], "id": "theirs", "image_sha256": "t"}
    main_catalog = [*pinned, other]  # someone else merged an entry
    new = {**pinned[0], "id": "mine", "image_sha256": "m"}
    local = dropped(edited(pinned, "photo", payload="changed"), "typo") + [new]
    merged, conflicts = contribute.merge(local, pinned, main_catalog)
    assert conflicts == []
    ids = [entry["id"] for entry in merged]
    assert "theirs" in ids and "mine" in ids and "typo" not in ids
    assert next(e for e in merged if e["id"] == "photo")["payload"] == "changed"

    main_catalog = edited(main_catalog, "photo", payload="their edit")
    _, conflicts = contribute.merge(local, pinned, main_catalog)
    assert conflicts == ["photo: changed on the dataset since your download"]


def test_vocabulary_changes_merge_unless_both_sides_changed():
    base, mine, theirs = {"v": 1}, {"v": 2}, {"v": 3}
    assert contribute.merge_vocabulary(mine, base, base) == (mine, [])
    assert contribute.merge_vocabulary(base, base, theirs) == (theirs, [])
    assert contribute.merge_vocabulary(mine, base, theirs)[1]


def test_upload_sends_only_changes_onto_main(draft_dir, draft_catalog, monkeypatch):
    pinned = (copy.deepcopy(draft_catalog[0]), draft_catalog[1])
    image = png(draft_dir.parent / "new.png", "olive")
    added, _ = contribute.add_images(
        [image], draft_dir, label="benign", content="web_page", source=SOURCE
    )
    calls = []

    class Api:
        def dataset_info(self, repo_id, revision):
            return SimpleNamespace(sha="main-sha")

        def create_commit(self, repo_id, operations, **options):
            calls.append((operations, options))
            return SimpleNamespace(pr_url="https://hf.co/pr/9")

    monkeypatch.setattr(contribute, "pinned_dataset", lambda: ("o/d", "pin-sha"))
    monkeypatch.setattr(contribute, "remote_files", lambda revision, repo_id: pinned)
    monkeypatch.setattr("huggingface_hub.HfApi", Api)
    planned = contribute.upload(draft_dir, "Add one", dry_run=True)
    assert planned["changes"]["added"] == [added[0]["id"]] and calls == []
    data = contribute.upload(draft_dir, "Add one")
    operations, options = calls[0]
    paths = sorted(operation.path_in_repo for operation in operations)
    assert paths == ["catalog.json", added[0]["image"]]
    assert options["create_pr"] is True and options["parent_commit"] == "main-sha"
    assert data["pull_request"] == "https://hf.co/pr/9"


def test_upload_refuses_invalid_data_and_empty_submissions(
    draft_dir, draft_catalog, monkeypatch
):
    pinned = (copy.deepcopy(draft_catalog[0]), draft_catalog[1])
    monkeypatch.setattr(contribute, "pinned_dataset", lambda: ("o/d", "pin-sha"))
    monkeypatch.setattr(contribute, "remote_files", lambda revision, repo_id: pinned)
    monkeypatch.setattr(
        "huggingface_hub.HfApi",
        lambda: SimpleNamespace(
            dataset_info=lambda repo, revision: SimpleNamespace(sha="m")
        ),
    )
    with pytest.raises(ValueError, match="Nothing to submit"):
        contribute.upload(draft_dir, "x")
    (draft_dir / "ocr_eval/images/photo.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="validation errors"):
        contribute.upload(draft_dir, "x")


@pytest.fixture
def store(draft_dir):
    return CurationStore(draft_dir)


def test_label_page_edits_payload_reference_source_and_context(store, draft_dir):
    entry = store.update(
        "typo",
        {
            "payload": "  New payload  ",
            "source": {"license": "CC0-1.0", "repository": ""},
            "cases": [
                {"expected": "injection"},
                {"expected": "benign", "context": "A phishing training set."},
            ],
        },
    )
    assert entry["payload"] == "New payload"
    assert entry["source"]["license"] == "CC0-1.0"
    assert entry["source"]["repository"] is None
    assert entry["cases"][1] == {
        "expected": "benign",
        "context": "A phishing training set.",
    }
    assert catalog(draft_dir)[0]["payload"] == "New payload"


def test_reference_text_is_created_kept_with_regions_and_cleared(store):
    store.update("typo", {"ocr_reference": {"text": ""}})
    assert store.entry("typo")["ocr_reference"] is None
    created = store.update("typo", {"ocr_reference": {"text": "Hello"}})
    assert created["ocr_reference"]["scope"] == "primary_visible_payload"
    assert created["ocr_reference"]["quality"] == "reviewed_payload"
    with pytest.raises(ValueError, match="word regions"):
        store.update("photo", {"ocr_reference": {"text": "Other"}})
    with pytest.raises(ValueError, match="case expected"):
        store.update("typo", {"cases": [{"expected": "maybe"}]})
    with pytest.raises(ValueError, match="Source accepts"):
        store.update("typo", {"source": {"owner": "me"}})


def test_routes_list_your_changes_and_the_balance(draft_dir, draft_catalog):
    pinned = copy.deepcopy(draft_catalog[0])
    store = CurationStore(draft_dir)
    app = Flask(__name__)
    curation_routes.register_routes(app, store, pinned_catalog=lambda: pinned)
    client = app.test_client()
    assert client.get("/api/curation/entries?changed=1").json["items"] == []
    store.update("photo", {"payload": "edited"})
    changed = client.get("/api/curation/entries?changed=1").json
    assert [item["id"] for item in changed["items"]] == ["photo"]
    balance = client.get("/api/curation/balance").json
    assert balance["target_benign_percent"] == 50.0 and balance["contents"]


def test_changes_filter_explains_a_missing_download(draft_dir):
    def offline():
        raise OSError("no network")

    app = Flask(__name__)
    curation_routes.register_routes(
        app, CurationStore(draft_dir), pinned_catalog=offline
    )
    response = app.test_client().get("/api/curation/entries?changed=1")
    assert response.status_code == 503
    assert "network connection" in response.json["error"]


def page_client(directory):
    app = Flask(__name__)
    curation_routes.register_routes(app, CurationStore(directory))
    return app.test_client()


def image_form(tmp_path, color, **fields):
    data = {
        "label": "benign",
        "content": "web_page",
        "dataset": "my_screenshots",
        "license": "CC-BY-4.0",
        "provenance": "Screenshots of my test web app",
        **fields,
    }
    path = png(tmp_path / f"{color}.png", color)
    data["images"] = [(path.open("rb"), "login page.png")]
    return data


def test_dataset_page_adds_uploaded_images(draft_dir, tmp_path):
    client = page_client(draft_dir)
    response = client.post("/api/curation/images", data=image_form(tmp_path, "coral"))
    assert response.status_code == 200
    (identifier,) = response.json["added"]
    entry = client.get(f"/api/curation/entries/{identifier}").json
    assert entry["source"]["sample_id"] == "my_screenshots:login_page"
    assert entry["curation"]["reviewed"] is False
    again = client.post("/api/curation/images", data=image_form(tmp_path, "coral"))
    assert again.json == {
        "added": [],
        "skipped": [{"file": "login_page.png", "id": identifier}],
    }


def test_dataset_page_rejects_missing_images_and_source(draft_dir, tmp_path):
    client = page_client(draft_dir)
    before = catalog(draft_dir)
    assert client.post("/api/curation/images", data={}).status_code == 400
    response = client.post(
        "/api/curation/images", data=image_form(tmp_path, "khaki", license="")
    )
    assert response.status_code == 400 and "license" in response.json["error"]
    assert catalog(draft_dir) == before


def test_contribution_errors_do_not_expose_internal_details(
    draft_dir, tmp_path, monkeypatch, caplog
):
    detail = "/private/dataset/secret: provider-token"

    def fail(*args, **kwargs):
        raise ValueError(detail)

    monkeypatch.setattr(contribute, "add_images", fail)
    monkeypatch.setattr(contribute, "upload", fail)
    client = page_client(draft_dir)
    responses = [
        client.post("/api/curation/images", data=image_form(tmp_path, "coral")),
        client.get("/api/curation/submission"),
    ]
    for response in responses:
        assert response.status_code == 400
        assert detail not in response.get_data(as_text=True)
    assert detail in caplog.text


def submission_data(**extra):
    return {
        "changes": {"added": ["a"], "changed": [], "removed": []},
        "conflicts": [],
        "catalog": [],
        "vocabulary": {},
        "vocabulary_changed": False,
        "main_revision": "main-sha",
        **extra,
    }


def test_submission_is_previewed_then_confirmed(draft_dir, monkeypatch):
    calls = []

    def upload(directory, message, *, dry_run=False):
        calls.append((message, dry_run))
        return submission_data(
            **({} if dry_run else {"pull_request": "https://hf.co/pr/3"})
        )

    monkeypatch.setattr(contribute, "upload", upload)
    monkeypatch.setattr(contribute, "signed_in", lambda: True)
    client = page_client(draft_dir)
    preview = client.get("/api/curation/submission").json
    assert preview["counts"] == {"added": 1, "changed": 0, "removed": 0}
    assert "catalog" not in preview and calls == [("", True)]
    assert client.post("/api/curation/submission", json={}).status_code == 400
    done = client.post(
        "/api/curation/submission",
        json={"confirm": True, "message": "Add a login page"},
    ).json
    assert done["pull_request"] == "https://hf.co/pr/3"
    assert calls[-1] == ("Add a login page", False)


def test_submission_explains_login_and_unreachable_dataset(draft_dir, monkeypatch):
    class EntryNotFoundError(OSError):
        pass

    def offline(directory, message, *, dry_run=False):
        raise EntryNotFoundError("404 catalog.json")

    monkeypatch.setattr(contribute, "upload", offline)
    monkeypatch.setattr(contribute, "signed_in", lambda: False)
    client = page_client(draft_dir)
    response = client.get("/api/curation/submission")
    assert (
        response.status_code == 503
        and "no catalog.json on main" in response.json["error"]
    )
    response = client.post("/api/curation/submission", json={"confirm": True})
    assert response.status_code == 401 and "hf auth login" in response.json["error"]
