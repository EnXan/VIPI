"""Edit the combined catalog draft and its vocabulary with atomic saves.

Every change is validated before it is written; a rejected change leaves the
files untouched. Entries and vocabulary are replaced, never mutated in place.
"""

import copy
import json
import os
from pathlib import Path
import tempfile
import threading

from . import schema, similarity
from .vocabulary import FIELDS, allowed, near_duplicates, normalize

DEFAULT_DIRECTORY = Path("research/dataset")
CATALOG_NAME = "catalog.json"
VOCABULARY_NAME = "vocabulary.json"
CURATION_KEYS = ("reviewed", "decision", "reason", "duplicate_of")
SOURCE_KEYS = ("dataset", "repository", "sample_id", "license", "provenance")
TEXT_KEYS = ("payload", "ocr_reference", "source", "cases")
# A reference typed on the Label page transcribes the main visible text.
NEW_REFERENCE = {
    "scope": "primary_visible_payload",
    "quality": "reviewed_payload",
    "reading_order_known": True,
    "regions": None,
}
STATUSES = ("all", "unreviewed", "reviewed", "dropped")


class DraftMissing(ValueError):
    pass


def write_json(path, value):
    """Atomically replace a JSON file, keeping non-ASCII text readable."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class CurationStore:
    def __init__(self, directory, images_root=None):
        self.directory = Path(directory)
        # image paths are relative to the dataset folder unless told otherwise
        self.images_root = Path(images_root or directory).resolve()
        self.lock = threading.Lock()
        self.catalog = None
        self.vocabulary = None
        self.hashes = {}
        self.loaded_stamp = None

    @property
    def catalog_path(self):
        return self.directory / CATALOG_NAME

    @property
    def vocabulary_path(self):
        return self.directory / VOCABULARY_NAME

    def load(self):
        """Return the cached draft, reloading it when a file changed on disk
        (for example after ``python -m research.curation generate``)."""
        stamp = self.stamp()
        if self.catalog is not None and stamp != self.loaded_stamp:
            self.catalog = None
        if self.catalog is None:
            if not self.catalog_path.is_file() or not self.vocabulary_path.is_file():
                raise DraftMissing(
                    f"No dataset found in {self.directory}. Run: uv run python -m "
                    "research.download"
                )
            self.catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            self.vocabulary = json.loads(
                self.vocabulary_path.read_text(encoding="utf-8")
            )
            self.loaded_stamp = stamp
        return self.catalog, self.vocabulary

    def stamp(self):
        try:
            return tuple(
                path.stat().st_mtime_ns
                for path in (self.catalog_path, self.vocabulary_path)
            )
        except OSError:
            return None

    def save(self, catalog=None, vocabulary=None):
        if catalog is not None:
            write_json(self.catalog_path, catalog)
            self.catalog = catalog
        if vocabulary is not None:
            write_json(self.vocabulary_path, vocabulary)
            self.vocabulary = vocabulary
        self.loaded_stamp = self.stamp()

    def status(self):
        try:
            catalog, _ = self.load()
        except DraftMissing as error:
            return {"available": False, "message": str(error)}
        return {
            "available": True,
            "entries": len(catalog),
            "reviewed": sum(
                e["curation"]["reviewed"] or e["curation"]["decision"] == "drop"
                for e in catalog
            ),
            "dropped": sum(e["curation"]["decision"] == "drop" for e in catalog),
        }

    # Entries -----------------------------------------------------------------

    def index(self, identifier):
        catalog, _ = self.load()
        for position, entry in enumerate(catalog):
            if entry["id"] == identifier:
                return position
        raise KeyError(identifier)

    def entry(self, identifier):
        catalog, _ = self.load()
        return catalog[self.index(identifier)]

    def matches(self, entry, status, field, value, source, query):
        curation = entry["curation"]
        if (curation["decision"] == "drop") != (status == "dropped"):
            return False
        if status == "unreviewed" and curation["reviewed"]:
            return False
        if status == "reviewed" and not curation["reviewed"]:
            return False
        if status == "dropped" and curation["decision"] != "drop":
            return False
        if field:
            current = entry.get(field)
            values = current if isinstance(current, list) else [current]
            if value == "(none)":
                if any(values):
                    return False
            elif value not in values:
                return False
        if source and entry["source"].get("dataset") != source:
            return False
        if query:
            text = " ".join(
                str(part or "")
                for part in (
                    entry["id"],
                    entry["image"],
                    entry["payload"],
                    (entry["ocr_reference"] or {}).get("text"),
                )
            )
            if query.casefold() not in text.casefold():
                return False
        return True

    def image_hash(self, entry):
        """Cached difference hash of an entry's image, None if unreadable."""
        key = entry["image_sha256"]
        if key not in self.hashes:
            try:
                self.hashes[key] = similarity.image_hash(self.image_path(entry["id"]))
            except (OSError, ValueError):
                self.hashes[key] = None
        return self.hashes[key]

    def grouped(self, entries, items):
        """Reorder items so similar entries follow each other, with group info."""
        features = {
            entry["id"]: (self.image_hash(entry), similarity.words(entry))
            for entry in entries
        }
        by_id = {item["id"]: item for item in items}
        return [
            {**by_id[identifier], "group": number, "group_size": len(members)}
            for number, members in enumerate(similarity.groups(features), 1)
            for identifier in members
        ]

    def listing(
        self,
        status="all",
        field="",
        value="",
        source="",
        query="",
        group=False,
        only=None,
    ):
        """List entries matching the filters.

        With ``group``, similar entries are listed together (see similarity.py).
        ``only`` limits the list to these ids (for example your changes).
        """
        if status not in STATUSES:
            raise ValueError(f"Choose status {', '.join(STATUSES)}.")
        if field and field not in FIELDS:
            raise ValueError("Unknown field filter.")
        catalog, _ = self.load()
        entries = [
            entry
            for entry in catalog
            if self.matches(entry, status, field, value, source, query)
            and (only is None or entry["id"] in only)
        ]
        items = [
            {
                "id": entry["id"],
                "image": entry["image"],
                "label": entry["label"],
                "reviewed": entry["curation"]["reviewed"],
                "decision": entry["curation"]["decision"],
            }
            for entry in entries
        ]
        if group:
            items = self.grouped(entries, items)
        sources = sorted({e["source"].get("dataset") or "" for e in catalog} - {""})
        return {
            "total": len(catalog),
            "matching": len(items),
            "items": items,
            "sources": sources,
        }

    def image_path(self, identifier):
        path = (self.images_root / self.entry(identifier)["image"]).resolve()
        if not path.is_relative_to(self.images_root) or not path.is_file():
            raise ValueError("Image is unavailable.")
        return path

    def update(self, identifier, changes):
        """Apply field/curation changes to one entry and save if it stays valid."""
        if not isinstance(changes, dict) or not changes:
            raise ValueError("Send the fields to change.")
        unknown = set(changes) - set(FIELDS) - set(TEXT_KEYS) - {"curation"}
        if unknown:
            raise ValueError(f"Fields cannot be edited: {sorted(unknown)}")
        with self.lock:
            catalog, vocabulary = self.load()
            position = self.index(identifier)
            entry = copy.deepcopy(catalog[position])
            for field in FIELDS:
                if field in changes:
                    entry[field] = changes[field]
            entry = edit_texts(entry, changes)
            curation = changes.get("curation", {})
            if not isinstance(curation, dict) or set(curation) - set(CURATION_KEYS):
                raise ValueError(f"Curation accepts {list(CURATION_KEYS)}.")
            entry["curation"] = {**entry["curation"], **curation}
            if entry["curation"]["decision"] == "keep":
                entry["curation"] = {
                    **entry["curation"],
                    "reason": None,
                    "duplicate_of": None,
                }
            ids = {e["id"] for e in catalog}
            errors = schema.entry_errors(entry, vocabulary, ids)
            if errors:
                raise ValueError("; ".join(errors))
            self.save(catalog=[*catalog[:position], entry, *catalog[position + 1 :]])
            return entry

    def changed_ids(self, pinned):
        """Ids added, changed or dropped since the downloaded revision."""
        from .contribute import changes

        catalog, _ = self.load()
        found = changes(catalog, pinned)
        return {key for keys in found.values() for key in keys}

    # Vocabulary --------------------------------------------------------------

    def field_spec(self, vocabulary, field):
        if field not in FIELDS:
            raise ValueError("Unknown field.")
        return vocabulary["fields"][field]

    def usage(self, field, value):
        catalog, _ = self.load()
        return sum(
            value in (e[field] if isinstance(e[field], list) else [e[field]])
            for e in catalog
        )

    def with_values(self, vocabulary, field, values):
        fields = {
            **vocabulary["fields"],
            field: {**vocabulary["fields"][field], "values": values},
        }
        return {**vocabulary, "fields": fields}

    def add_value(self, field, value, description="", confirm=False):
        with self.lock:
            _, vocabulary = self.load()
            spec = self.field_spec(vocabulary, field)
            name = normalize(value or "")
            if not name:
                raise ValueError("Enter a value.")
            if name in allowed(vocabulary, field):
                raise ValueError(f"{name} already exists.")
            similar = near_duplicates(vocabulary, field, name)
            if similar and not confirm:
                return {"added": False, "value": name, "similar": similar}
            values = [
                *spec["values"],
                {"value": name, "description": description.strip()},
            ]
            self.save(vocabulary=self.with_values(vocabulary, field, values))
            return {"added": True, "value": name, "similar": similar}

    def rename_value(self, field, value, new_value):
        """Rename or merge ``value`` into ``new_value`` across every entry."""
        with self.lock:
            catalog, vocabulary = self.load()
            spec = self.field_spec(vocabulary, field)
            target = normalize(new_value or "")
            if value not in allowed(vocabulary, field) or not target:
                raise ValueError("Choose an existing value and a new name.")
            if target == value:
                raise ValueError("The new name is the same.")
            merged = target in allowed(vocabulary, field)
            values = [
                {**item, "value": target} if item["value"] == value else item
                for item in spec["values"]
                if not (merged and item["value"] == value)
            ]

            def renamed(entry):
                current = entry[field]
                if isinstance(current, list):
                    replaced = [target if item == value else item for item in current]
                    return {**entry, field: list(dict.fromkeys(replaced))}
                return {**entry, field: target if current == value else current}

            catalog = [renamed(entry) for entry in catalog]
            self.save(
                catalog=catalog, vocabulary=self.with_values(vocabulary, field, values)
            )
            return {"value": target, "merged": merged}

    def remove_value(self, field, value):
        with self.lock:
            _, vocabulary = self.load()
            spec = self.field_spec(vocabulary, field)
            if value not in allowed(vocabulary, field):
                raise ValueError("Unknown value.")
            used = self.usage(field, value)
            if used:
                raise ValueError(
                    f"{value} is used by {used} entries; rename or merge it instead."
                )
            values = [item for item in spec["values"] if item["value"] != value]
            self.save(vocabulary=self.with_values(vocabulary, field, values))
            return {"removed": value}


def optional_text(value, name):
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    return (value or "").strip() or None


def edit_texts(entry, changes):
    """Return ``entry`` with edited payload, OCR reference text, source or
    caller-context cases."""
    entry = dict(entry)
    if "payload" in changes:
        entry["payload"] = optional_text(changes["payload"], "payload")
    if "ocr_reference" in changes:
        edit = changes["ocr_reference"]
        if not isinstance(edit, dict) or set(edit) != {"text"}:
            raise ValueError('Send the OCR reference as {"text": ...}.')
        text = optional_text(edit["text"], "OCR reference")
        reference = entry["ocr_reference"]
        if reference and reference.get("regions") and text != reference["text"]:
            raise ValueError(
                "This reference has word regions; change its text and regions "
                "together in catalog.json."
            )
        if text is None:
            entry["ocr_reference"] = None
        elif reference:
            entry["ocr_reference"] = {**reference, "text": text}
        else:
            entry["ocr_reference"] = {"text": text, **NEW_REFERENCE}
    if "source" in changes:
        edit = changes["source"]
        if not isinstance(edit, dict) or set(edit) - set(SOURCE_KEYS):
            raise ValueError(f"Source accepts {list(SOURCE_KEYS)}.")
        entry["source"] = {
            **entry["source"],
            **{key: optional_text(value, key) for key, value in edit.items()},
        }
    if "cases" in changes:
        cases = changes["cases"]
        if not isinstance(cases, list) or not all(
            isinstance(case, dict) and set(case) <= {"expected", "context"}
            for case in cases
        ):
            raise ValueError("Cases are a list of {expected, context}.")
        entry["cases"] = [
            {
                "expected": case.get("expected"),
                **(
                    {"context": optional_text(case["context"], "context")}
                    if case.get("context")
                    else {}
                ),
            }
            for case in cases
        ]
    return entry
