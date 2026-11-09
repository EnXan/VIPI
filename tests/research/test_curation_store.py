"""Keep label edits validated, atomic and reachable from the workbench."""

import json

import pytest

from research.curation import migrate
from research.curation.store import CurationStore
from research.workbench.web import create_app


@pytest.fixture
def draft(catalogs_root):
    catalog, words = migrate.build(catalogs_root)
    directory = catalogs_root / "draft"
    migrate.write(directory, catalog, words)
    return directory, catalogs_root / "research"


@pytest.fixture
def store(draft):
    return CurationStore(*draft)


def saved(directory):
    return json.loads((directory / "catalog.json").read_text())


def test_update_saves_valid_changes_and_rejects_invalid_ones(store, draft):
    directory, _ = draft
    entry = store.update(
        "photo", {"content": "real_world", "curation": {"reviewed": True}}
    )
    assert entry["curation"]["reviewed"] is True
    assert next(e for e in saved(directory) if e["id"] == "photo")["curation"][
        "reviewed"
    ]
    before = (directory / "catalog.json").read_text()
    with pytest.raises(ValueError, match="does not apply to label 'benign'"):
        store.update("photo", {"techniques": ["task_redirection"]})
    with pytest.raises(ValueError, match="cannot be edited"):
        store.update("photo", {"image": "other.png"})
    with pytest.raises(ValueError, match="a dropped entry needs a reason"):
        store.update("photo", {"curation": {"decision": "drop"}})
    assert (directory / "catalog.json").read_text() == before


def test_keep_clears_drop_reason(store):
    store.update("typo", {"curation": {"decision": "drop", "reason": "duplicate"}})
    entry = store.update("typo", {"curation": {"decision": "keep"}})
    assert entry["curation"]["reason"] is None


def test_listing_filters_by_status_field_source_and_text(store):
    store.update("photo", {"curation": {"reviewed": True}})
    assert [i["id"] for i in store.listing("reviewed")["items"]] == ["photo"]
    assert len(store.listing("unreviewed")["items"]) == 2
    assert [i["id"] for i in store.listing(field="label", value="benign")["items"]] == [
        "photo"
    ]
    assert len(store.listing(field="goal", value="(none)")["items"]) == 3
    assert [i["id"] for i in store.listing(source="textocr")["items"]] == ["photo"]
    assert [i["id"] for i in store.listing(query="main street")["items"]] == ["photo"]
    with pytest.raises(ValueError):
        store.listing("later")


def test_vocabulary_add_rename_merge_and_remove(store, draft):
    directory, _ = draft
    assert store.add_value("obfuscation", "lowcontrast")["similar"] == ["low_contrast"]
    assert store.add_value("obfuscation", "Glitch Art")["added"] is True
    store.update("typo", {"obfuscation": ["glitch_art", "low_contrast"]})
    renamed = store.rename_value("obfuscation", "glitch_art", "noise")
    assert renamed == {"value": "noise", "merged": False}
    assert store.entry("typo")["obfuscation"] == ["noise", "low_contrast"]
    merged = store.rename_value("obfuscation", "noise", "low_contrast")
    assert merged["merged"] is True
    assert store.entry("typo")["obfuscation"] == ["low_contrast"]
    words = json.loads((directory / "vocabulary.json").read_text())
    values = [i["value"] for i in words["fields"]["obfuscation"]["values"]]
    assert "noise" not in values and values.count("low_contrast") == 1
    with pytest.raises(ValueError, match="used by"):
        store.remove_value("obfuscation", "low_contrast")
    assert store.remove_value("obfuscation", "rotated_text") == {
        "removed": "rotated_text"
    }


def test_existing_value_cannot_be_added_twice(store):
    with pytest.raises(ValueError, match="already exists"):
        store.add_value("obfuscation", "Low-Contrast")


def test_missing_draft_is_reported(tmp_path):
    status = CurationStore(tmp_path / "none", tmp_path).status()
    assert status["available"] is False
    assert "research.curation migrate" in status["message"]


@pytest.fixture
def client(draft, tmp_path):
    directory, images = draft
    app = create_app(
        tmp_path / "runs", repository_root=images.parent, curation_dir=directory
    )
    return app.test_client()


def test_routes_list_show_update_and_serve_images(client):
    status = client.get("/api/curation").json
    assert status["available"] and status["entries"] == 3
    assert "label" in status["vocabulary"]["fields"]
    items = client.get("/api/curation/entries?status=all").json["items"]
    assert {item["id"] for item in items} == {"typo", "photo", items[2]["id"]}
    assert client.get("/api/curation/entries/photo").json["label"] == "benign"
    updated = client.post(
        "/api/curation/entries/photo", json={"curation": {"reviewed": True}}
    )
    assert updated.status_code == 200 and updated.json["curation"]["reviewed"]
    rejected = client.post(
        "/api/curation/entries/photo", json={"goal": ["persistence"]}
    )
    assert rejected.status_code == 400
    assert client.get("/api/curation/entries/photo/image").status_code == 200
    assert client.get("/api/curation/entries/photo/thumbnail").mimetype == "image/jpeg"
    assert client.get("/api/curation/entries/missing").status_code == 404


def test_vocabulary_routes(client):
    first = client.post(
        "/api/curation/vocabulary/obfuscation", json={"value": "lowcontrast"}
    )
    assert first.json["added"] is False and first.json["similar"] == ["low_contrast"]
    added = client.post(
        "/api/curation/vocabulary/obfuscation",
        json={"value": "lowcontrast", "confirm": True},
    )
    assert added.json["added"] is True
    renamed = client.post(
        "/api/curation/vocabulary/obfuscation/lowcontrast/rename",
        json={"to": "low_contrast"},
    )
    assert renamed.json["merged"] is True
    removed = client.post(
        "/api/curation/vocabulary/obfuscation/rotated_text/remove", json={}
    )
    assert removed.status_code == 200
    assert (
        client.post("/api/curation/vocabulary/nope", json={"value": "x"}).status_code
        == 400
    )


def test_cross_origin_updates_are_rejected(client):
    response = client.post(
        "/api/curation/entries/photo",
        json={"curation": {"reviewed": True}},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403


def test_missing_draft_route_reports_how_to_create_it(tmp_path):
    app = create_app(
        tmp_path / "runs", repository_root=tmp_path, curation_dir=tmp_path / "x"
    )
    client = app.test_client()
    assert client.get("/api/curation").json["available"] is False
    assert client.get("/api/curation/entries").status_code == 409


def write_batch(directory, proposals, name="batch-001.json"):
    folder = directory / "proposals"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(json.dumps({"model": "haiku", "proposals": proposals}))


def proposal(identifier, **fields):
    base = {
        "id": identifier,
        "label": "injection",
        "techniques": [],
        "goal": [],
        "obfuscation": [],
        "evidence": ["text"],
        "content": "text_image",
        "new_values": [],
        "rationale": "fixture",
        "confidence": "high",
    }
    return {**base, **fields}


def test_approve_applies_proposal_adds_used_new_values_and_marks_reviewed(store, draft):
    from research.curation.proposals import ProposalBook

    directory, _ = draft
    write_batch(
        directory,
        [
            proposal(
                "typo",
                goal=["safety_bypass"],
                new_values=[
                    {
                        "field": "goal",
                        "value": "safety_bypass",
                        "description": "Disable rules.",
                    },
                    {
                        "field": "goal",
                        "value": "unused_idea",
                        "description": "Not used.",
                    },
                ],
            )
        ],
    )
    book = ProposalBook(store)
    assert book.get("typo")["problems"] == []
    entry = book.approve("typo")
    assert entry["goal"] == ["safety_bypass"] and entry["curation"]["reviewed"]
    words = json.loads((directory / "vocabulary.json").read_text())
    goals = [item["value"] for item in words["fields"]["goal"]["values"]]
    assert "safety_bypass" in goals and "unused_idea" not in goals
    assert book.counts() == {"proposals": 1, "pending": 0, "approved": 1, "denied": 0}
    with pytest.raises(ValueError, match="already approved"):
        book.approve("typo")


def test_invalid_proposals_cannot_be_approved_and_deny_hides_them(store, draft):
    from research.curation.proposals import ProposalBook

    directory, _ = draft
    write_batch(directory, [proposal("photo", label="benign", goal=["invented"])])
    book = ProposalBook(store)
    assert "neither in the vocabulary" in book.get("photo")["problems"][0]
    with pytest.raises(ValueError):
        book.approve("photo")
    assert store.entry("photo")["curation"]["reviewed"] is False
    book.deny("photo")
    assert book.pending() == {}
    assert book.get("photo")["status"] == "denied"


def test_later_batches_override_earlier_proposals(store, draft):
    from research.curation.proposals import ProposalBook

    directory, _ = draft
    write_batch(directory, [proposal("typo", content="code")], "batch-001.json")
    write_batch(directory, [proposal("typo", content="text_image")], "batch-002.json")
    assert ProposalBook(store).get("typo")["content"] == "text_image"


def test_proposal_routes_filter_approve_and_deny(client, draft):
    directory, _ = draft
    write_batch(
        directory, [proposal("typo"), proposal("photo", label="benign", evidence=[])]
    )
    listed = client.get("/api/curation/entries?status=proposed").json["items"]
    assert {item["id"] for item in listed} == {"typo", "photo"}
    assert (
        client.get("/api/curation/entries/typo/proposal").json["proposal"]["status"]
        == "pending"
    )
    approved = client.post("/api/curation/entries/typo/proposal/approve", json={})
    assert approved.status_code == 200 and approved.json["curation"]["reviewed"]
    assert (
        client.post("/api/curation/entries/photo/proposal/deny", json={}).status_code
        == 200
    )
    assert client.get("/api/curation/entries?status=proposed").json["items"] == []
    assert client.get("/api/curation").json["proposals"]["approved"] == 1
    assert (
        client.post("/api/curation/entries/typo/proposal/maybe", json={}).status_code
        == 400
    )


def test_dropped_entries_only_appear_under_dropped_and_count_as_done(store):
    store.update("typo", {"curation": {"decision": "drop", "reason": "duplicate"}})
    for status in ("all", "unreviewed", "reviewed"):
        assert "typo" not in {i["id"] for i in store.listing(status)["items"]}
    assert [i["id"] for i in store.listing("dropped")["items"]] == ["typo"]
    assert store.status()["reviewed"] == 1


def test_similarity_groups_by_image_hash_or_text_overlap():
    from research.curation.similarity import groups

    text = frozenset({"ignore", "all", "previous", "instructions"})
    features = {
        "lonely": ((1 << 40) - 1 << 100, frozenset({"a", "b", "c"})),
        "first": (0, frozenset()),
        "near": (0b111, frozenset()),
        "same_text": (None, text),
        "same_text_2": ((1 << 60) - 1 << 150, text | {"now"}),
    }
    found = groups(features)
    assert sorted(map(sorted, found)) == [
        ["first", "near"],
        ["lonely"],
        ["same_text", "same_text_2"],
    ]
    assert len(found[-1]) == 1


def test_grouped_listing_orders_similar_entries_together(store):
    plain = store.listing()["items"]
    grouped = store.listing(group=True)["items"]
    assert sorted(i["id"] for i in grouped) == sorted(i["id"] for i in plain)
    assert all(i["group_size"] >= 1 and i["group"] >= 1 for i in grouped)
    sizes = [i["group_size"] for i in grouped]
    assert sizes == sorted(sizes, reverse=True)


def test_similar_images_with_different_text_stay_apart():
    from research.curation.similarity import similar

    one = frozenset({"how", "to", "bake", "bread"})
    other = frozenset({"ignore", "your", "previous", "rules"})
    assert not similar((0, one), (1, other))
    assert similar((0, one), (1, frozenset()))
