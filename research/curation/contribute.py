"""Add your own images to the dataset and submit only your changes.

The published dataset holds one ``catalog.json``. Uploading a whole local copy
would overwrite whatever others merged since your download, so a submission
carries only the difference between your local dataset and the pinned
revision you downloaded, applied to the current ``main`` of the dataset
repository. An entry that someone else changed meanwhile is a conflict.
"""

import hashlib
import json
from pathlib import Path
import shutil

from research.catalog import ROOT

from . import schema
from .store import CATALOG_NAME, VOCABULARY_NAME, write_json

IMAGE_FOLDER = "images"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
DATASET_FILE = ROOT / "research/dataset.json"


def pinned_dataset():
    """``(repo_id, revision)`` that ``research.download`` fetched."""
    data = json.loads(DATASET_FILE.read_text(encoding="utf-8"))
    return data["repo_id"], data["revision"]


def remote_files(revision, repo_id=None):
    """``(catalog, vocabulary)`` of the dataset at ``revision`` (cached by
    huggingface_hub, so a known revision also works offline)."""
    from huggingface_hub import hf_hub_download

    repo_id = repo_id or pinned_dataset()[0]
    files = [
        json.loads(
            Path(
                hf_hub_download(
                    repo_id,
                    name,
                    repo_type="dataset",
                    revision=revision,
                    token=False,
                )
            ).read_text(encoding="utf-8")
        )
        for name in (CATALOG_NAME, VOCABULARY_NAME)
    ]
    return files[0], files[1]


def signed_in():
    """Whether a Hugging Face token is stored (``hf auth login``)."""
    from huggingface_hub import get_token

    return get_token() is not None


# Adding images ----------------------------------------------------------------


def new_entry(path, image, digest, *, label, content, source):
    return {
        "id": digest[:16],
        "image": image,
        "image_sha256": digest,
        "label": label,
        "techniques": [],
        "goal": [],
        "obfuscation": [],
        "evidence": [],
        "content": content,
        "payload": None,
        "cases": [],
        "ocr_reference": None,
        "source": {
            "dataset": source["dataset"],
            "repository": source.get("repository"),
            "sample_id": f"{source['dataset']}:{Path(path).stem}",
            "license": source["license"],
            "provenance": source["provenance"],
            "content_group_id": None,
        },
        "migrated_from": {},
        "curation": {
            "reviewed": False,
            "decision": "keep",
            "reason": None,
            "duplicate_of": None,
        },
    }


def add_images(paths, directory, *, label, content, source):
    """Copy images into ``directory/images`` and add one unreviewed entry each.

    Returns ``(added, skipped)``; an image whose bytes are already in the
    dataset is skipped with the id it has there."""
    directory = Path(directory)
    catalog = json.loads((directory / CATALOG_NAME).read_text(encoding="utf-8"))
    vocabulary = json.loads((directory / VOCABULARY_NAME).read_text(encoding="utf-8"))
    for key in ("dataset", "license", "provenance"):
        if not str(source.get(key) or "").strip():
            raise ValueError(f"Give the image {key} (see --help).")
    by_hash = {entry["image_sha256"]: entry["id"] for entry in catalog}
    added, skipped, planned = [], [], []
    for path in map(Path, paths):
        suffix = path.suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise ValueError(f"{path}: use a PNG, JPEG or WEBP image.")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in by_hash:
            skipped.append((str(path), by_hash[digest]))
            continue
        image = f"{IMAGE_FOLDER}/{digest[:16]}{'.jpg' if suffix == '.jpeg' else suffix}"
        entry = new_entry(
            path, image, digest, label=label, content=content, source=source
        )
        by_hash[digest] = entry["id"]
        planned.append((path, entry))
    ids = {entry["id"] for entry in catalog} | {e["id"] for _, e in planned}
    problems = [
        f"{entry['id']}: {message}"
        for _, entry in planned
        for message in schema.entry_errors(entry, vocabulary, ids)
    ]
    if problems:
        raise ValueError("; ".join(problems))
    (directory / IMAGE_FOLDER).mkdir(exist_ok=True)
    for path, entry in planned:
        shutil.copyfile(path, directory / entry["image"])
        added.append(entry)
    if added:
        write_json(directory / CATALOG_NAME, [*catalog, *added])
    return added, skipped


# Changes and submission -------------------------------------------------------


def published(catalog):
    """The entries a dataset revision publishes: kept ones, by id."""
    return {
        entry["id"]: entry
        for entry in catalog
        if entry["curation"]["decision"] != "drop"
    }


def changes(local, pinned):
    """Your changes: ids ``added``, ``changed`` and ``removed`` (dropped or
    deleted locally) relative to the downloaded revision."""
    mine, base = published(local), published(pinned)
    return {
        "added": [key for key in mine if key not in base],
        "changed": [key for key in mine if key in base and mine[key] != base[key]],
        "removed": [key for key in base if key not in mine],
    }


def merge(local, pinned, main):
    """Apply your changes to ``main``; returns ``(catalog, conflicts)``."""
    found = changes(local, pinned)
    mine, base, current = published(local), published(pinned), published(main)
    conflicts = []
    for key in found["changed"] + found["removed"]:
        if current.get(key) != base[key]:
            conflicts.append(f"{key}: changed on the dataset since your download")
    for key in found["added"]:
        if key in current and current[key] != mine[key]:
            conflicts.append(f"{key}: added on the dataset by someone else")
    merged = []
    for entry in main:
        key = entry["id"]
        if key in found["removed"]:
            continue
        merged.append(mine[key] if key in found["changed"] else entry)
    known = {entry["id"] for entry in merged}
    merged += [mine[key] for key in found["added"] if key not in known]
    return merged, conflicts


def merge_vocabulary(local, pinned, main):
    if local == pinned or local == main:
        return main, []
    if main != pinned:
        return main, [
            "vocabulary.json: changed both locally and on the dataset; "
            "download the new revision and add your values again"
        ]
    return local, []


def submission(directory, pinned, main):
    """Everything an upload sends, without sending it."""
    directory = Path(directory)
    local = json.loads((directory / CATALOG_NAME).read_text(encoding="utf-8"))
    vocabulary = json.loads((directory / VOCABULARY_NAME).read_text(encoding="utf-8"))
    errors, _ = schema.validate(local, vocabulary, directory)
    if errors:
        raise ValueError(
            f"Fix {len(errors)} validation errors first: "
            "uv run python -m research.curation validate"
        )
    catalog, conflicts = merge(local, pinned[0], main[0])
    words, vocabulary_conflicts = merge_vocabulary(vocabulary, pinned[1], main[1])
    found = changes(local, pinned[0])
    entries = published(local)
    base = published(pinned[0])
    return {
        "changes": found,
        "conflicts": conflicts + vocabulary_conflicts,
        "catalog": catalog,
        "vocabulary": words,
        "vocabulary_changed": words != main[1],
        "images": [entries[key]["image"] for key in found["added"]],
        "deleted_images": [base[key]["image"] for key in found["removed"]],
    }


def upload(directory, message, *, dry_run=False):
    """Open a pull request on the dataset with only your changes."""
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

    repo_id, revision = pinned_dataset()
    api = HfApi()
    main_revision = api.dataset_info(repo_id, revision="main").sha
    data = submission(
        directory, remote_files(revision, repo_id), remote_files(main_revision, repo_id)
    )
    data["main_revision"] = main_revision
    found = data["changes"]
    if not any(found.values()):
        raise ValueError("Nothing to submit: no changes since your download.")
    if data["conflicts"] or dry_run:
        return data
    directory = Path(directory)
    operations = [
        CommitOperationAdd(
            CATALOG_NAME,
            (json.dumps(data["catalog"], ensure_ascii=False, indent=2) + "\n").encode(),
        ),
        *[
            CommitOperationAdd(image, str(directory / image))
            for image in data["images"]
        ],
        *[CommitOperationDelete(image) for image in data["deleted_images"]],
    ]
    if data["vocabulary_changed"]:
        operations.append(
            CommitOperationAdd(
                VOCABULARY_NAME,
                (
                    json.dumps(data["vocabulary"], ensure_ascii=False, indent=2) + "\n"
                ).encode(),
            )
        )
    commit = api.create_commit(
        repo_id,
        operations,
        commit_message=message,
        repo_type="dataset",
        create_pr=True,
        parent_commit=main_revision,
    )
    data["pull_request"] = commit.pr_url
    return data
