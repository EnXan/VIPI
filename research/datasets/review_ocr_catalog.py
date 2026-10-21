#!/usr/bin/env python3
"""Locally review OCR transcripts in the VIPI metadata catalog."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unicodedata
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

from typography_metadata import standardize_record


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = PROJECT_ROOT / "research/datasets/data/catalog"
SOURCES_DIR = CATALOG_DIR / "sources"
METADATA_PATH = CATALOG_DIR / "metadata.jsonl"
SCHEMA_PATH = CATALOG_DIR / "schema/metadata.schema.json"
UI_PATH = Path(__file__).with_name("ocr_review.html")
REQUIRED_FIELDS = {
    "schema_version", "sample_id", "asset", "source", "group", "visual",
    "ocr", "security", "eligibility", "rights", "source_specific",
}
REVIEW_NOTE = "manually visually verified in review_ocr_catalog.py"
WRITE_LOCK = threading.Lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="Local server port (default: 8765)")
    parser.add_argument(
        "--mark-reviewed-dataset",
        help="Mark one all-target_text_only OCR dataset shard as manually reviewed gold.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check catalog sources and report review counts without starting the UI.",
    )
    return parser.parse_args()


def read_shards() -> dict[Path, list[dict[str, Any]]]:
    shards: dict[Path, list[dict[str, Any]]] = {}
    for path in sorted(SOURCES_DIR.glob("*.jsonl")):
        records: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc
                missing = REQUIRED_FIELDS - record.keys()
                if missing:
                    raise ValueError(f"{path}:{line_number} missing fields: {sorted(missing)}")
                records.append(record)
        shards[path] = records
    if not shards:
        raise ValueError(f"No JSONL source shards found in {SOURCES_DIR}")
    return shards


def iter_records(shards: dict[Path, list[dict[str, Any]]]) -> Iterator[dict[str, Any]]:
    seen: set[str] = set()
    for path in sorted(shards):
        for record in shards[path]:
            sample_id = str(record["sample_id"])
            if sample_id in seen:
                raise ValueError(f"Duplicate sample_id across source shards: {sample_id}")
            seen.add(sample_id)
            yield standardize_record(record)


def fingerprint(record: dict[str, Any]) -> str:
    encoded = json.dumps(
        standardize_record(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def atomic_jsonl(records: Iterator[dict[str, Any]], target: Path) -> Path:
    """Write JSONL to a sibling staging file; return it for a later atomic replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for record in records:
                json.dump(record, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        staged.unlink(missing_ok=True)
        raise
    return staged


def commit_shards(shards: dict[Path, list[dict[str, Any]]], changed_paths: set[Path]) -> None:
    """Stage updated shard(s) and rebuilt catalog before replacing their files."""
    staged: dict[Path, Path] = {}
    catalog_stage: Path | None = None
    try:
        for source_path in sorted(changed_paths):
            staged[source_path] = atomic_jsonl(iter(shards[source_path]), source_path)
        catalog_stage = atomic_jsonl(iter_records(shards), METADATA_PATH)
        for source_path, temporary_path in staged.items():
            temporary_path.replace(source_path)
        catalog_stage.replace(METADATA_PATH)
    finally:
        for temporary_path in staged.values():
            temporary_path.unlink(missing_ok=True)
        if catalog_stage:
            catalog_stage.unlink(missing_ok=True)


def update_record(sample_id: str, expected_revision: str, text: str, approve: bool) -> dict[str, Any]:
    if not text.strip():
        raise ValueError("OCR-Text darf nicht leer sein.")
    lock_name = hashlib.sha256(str(PROJECT_ROOT).encode("utf-8")).hexdigest()[:20]
    lock_path = Path(tempfile.gettempdir()) / f"vipi-ocr-review-{lock_name}.lock"
    with WRITE_LOCK, lock_path.open("a") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        shards = read_shards()
        found_record: dict[str, Any] | None = None
        found_path: Path | None = None
        for source_path, records in shards.items():
            for index, record in enumerate(records):
                if record["sample_id"] == sample_id:
                    found_record, found_path = record, source_path
                    if fingerprint(record) != expected_revision:
                        raise RuntimeError("Dieser Eintrag wurde zwischenzeitlich geändert. Bitte neu laden.")
                    updated = json.loads(json.dumps(record, ensure_ascii=False))
                    old_text = updated["ocr"]["transcript_verbatim"]
                    updated["ocr"]["transcript_verbatim"] = text
                    updated["ocr"]["transcript_normalized"] = " ".join(
                        unicodedata.normalize("NFC", text).split()
                    )
                    annotation = updated["ocr"]["annotation"]
                    if approve:
                        annotation["verified"] = True
                        annotation["quality"] = "gold"
                        if REVIEW_NOTE not in annotation["provenance"]:
                            annotation["provenance"] += f"; {REVIEW_NOTE}"
                    elif text != old_text:
                        # A changed transcript needs a fresh visual approval.
                        annotation["verified"] = False
                        annotation["quality"] = "silver"
                    records[index] = updated
                    break
            if found_record is not None:
                break
        if found_record is None or found_path is None:
            raise KeyError(f"Unknown sample_id: {sample_id}")

        # Rebuild order and validation match research/datasets/build_metadata_catalog.py;
        # source shards remain canonical.
        try:
            commit_shards(shards, {found_path})
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return {"record": standardize_record(updated), "revision": fingerprint(updated)}


def update_metadata(sample_id: str, expected_revision: str, candidate: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist editable metadata while protecting identity/review state."""
    lock_name = hashlib.sha256(str(PROJECT_ROOT).encode("utf-8")).hexdigest()[:20]
    lock_path = Path(tempfile.gettempdir()) / f"vipi-ocr-review-{lock_name}.lock"
    with WRITE_LOCK, lock_path.open("a") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            shards = read_shards()
            found_record: dict[str, Any] | None = None
            found_path: Path | None = None
            found_index = -1
            for source_path, records in shards.items():
                for index, record in enumerate(records):
                    if record["sample_id"] == sample_id:
                        found_record, found_path, found_index = record, source_path, index
                        break
                if found_record is not None:
                    break
            if found_record is None or found_path is None:
                raise KeyError(f"Unknown sample_id: {sample_id}")
            if fingerprint(found_record) != expected_revision:
                raise RuntimeError("Dieser Eintrag wurde zwischenzeitlich geändert. Bitte neu laden.")
            if not isinstance(candidate, dict):
                raise ValueError("Metadaten müssen ein JSON-Objekt sein.")

            current = standardize_record(found_record)
            protected = {
                "schema_version": current["schema_version"],
                "sample_id": current["sample_id"],
                "asset": current["asset"],
                "source": {key: current["source"][key] for key in ("dataset_id", "upstream_id", "repository", "revision")},
                "group": {key: current["group"][key] for key in ("content_group_id", "content_basis", "parent_sample_id")},
                "ocr": {
                    "transcript_verbatim": current["ocr"]["transcript_verbatim"],
                    "transcript_normalized": current["ocr"]["transcript_normalized"],
                    "annotation": current["ocr"]["annotation"],
                },
            }
            for section, values in protected.items():
                if section in {"schema_version", "sample_id", "asset"}:
                    if candidate.get(section) != values:
                        raise ValueError(f"{section} ist schreibgeschützt.")
                elif not isinstance(candidate.get(section), dict) or any(
                    candidate[section].get(key) != value for key, value in values.items()
                ):
                    raise ValueError(f"Bestimmte Felder in {section} sind schreibgeschützt.")

            candidate["schema_version"] = current["schema_version"]
            try:
                import jsonschema
                schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
                errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(candidate), key=lambda error: list(map(str, error.absolute_path)))
            except ImportError as exc:
                raise RuntimeError(
                    "Schema-Prüfung nicht verfügbar: jsonschema fehlt in diesem Python. "
                    "Bitte `uv sync` ausführen und den Review-Server mit "
                    "`.venv/bin/python research/datasets/review_ocr_catalog.py` starten."
                ) from exc
            if errors:
                first = errors[0]
                path = ".".join(str(part) for part in first.absolute_path) or "Metadaten"
                raise ValueError(f"Ungültiger Wert bei {path}: {first.message}")

            updated = json.loads(json.dumps(candidate, ensure_ascii=False))
            # Keep source-only fields in the original shard; standardize_record
            # intentionally omits them from the shared metadata.jsonl catalog.
            updated["source"]["license_spdx"] = found_record["source"].get("license_spdx")
            updated["group"]["variant"] = found_record["group"].get("variant")
            updated["security"]["contains_injection_instruction"] = found_record["security"].get(
                "contains_injection_instruction"
            )
            updated["security"]["contains_harmful_instruction"] = found_record["security"].get(
                "contains_harmful_instruction"
            )
            updated["eligibility"]["training"] = found_record["eligibility"].get("training")
            updated["rights"] = json.loads(json.dumps(found_record["rights"], ensure_ascii=False))
            # Keep archival source annotations in their shard without exposing
            # their heterogeneous fields in the shared catalog/editor.
            updated["source_specific"] = json.loads(json.dumps(found_record.get("source_specific", {}), ensure_ascii=False))
            for legacy_key in ("scene_type", "generation_type", "challenge_tags"):
                if legacy_key in found_record["visual"]:
                    updated["visual"].setdefault(legacy_key, found_record["visual"][legacy_key])
            shards[found_path][found_index] = updated
            commit_shards(shards, {found_path})
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    normalized = standardize_record(updated)
    return {"record": normalized, "revision": fingerprint(updated)}


def mark_dataset_reviewed(dataset_id: str) -> tuple[int, int]:
    """Approve all records in one OCR dataset, only for target-text references."""
    lock_name = hashlib.sha256(str(PROJECT_ROOT).encode("utf-8")).hexdigest()[:20]
    lock_path = Path(tempfile.gettempdir()) / f"vipi-ocr-review-{lock_name}.lock"
    with WRITE_LOCK, lock_path.open("a") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            shards = read_shards()
            matches: list[tuple[Path, int, dict[str, Any]]] = []
            for source_path, records in shards.items():
                for index, record in enumerate(records):
                    if record["source"]["dataset_id"] == dataset_id:
                        matches.append((source_path, index, record))
            if not matches:
                raise ValueError(f"No source records found for dataset_id={dataset_id!r}")
            source_paths = {path for path, _, _ in matches}
            if len(source_paths) != 1:
                raise ValueError(f"Expected one source shard for {dataset_id!r}; found {len(source_paths)}")
            wrong_scope = sorted({record["ocr"]["scope"] for _, _, record in matches} - {"target_text_only"})
            if wrong_scope:
                raise ValueError(
                    f"Refusing bulk review: {dataset_id!r} contains non-target scopes {wrong_scope}"
                )
            if any(record["eligibility"]["ocr_eval"] is not True for _, _, record in matches):
                raise ValueError(f"Refusing bulk review: {dataset_id!r} contains non-OCR-eval records")
            if any(not record["ocr"]["transcript_verbatim"].strip() for _, _, record in matches):
                raise ValueError(f"Refusing bulk review: {dataset_id!r} contains empty transcripts")

            already_reviewed = 0
            for source_path, index, record in matches:
                updated = json.loads(json.dumps(record, ensure_ascii=False))
                annotation = updated["ocr"]["annotation"]
                already_reviewed += bool(annotation["verified"])
                annotation["verified"] = True
                annotation["quality"] = "gold"
                if REVIEW_NOTE not in annotation["provenance"]:
                    annotation["provenance"] += f"; {REVIEW_NOTE}"
                shards[source_path][index] = updated
            commit_shards(shards, source_paths)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return len(matches), already_reviewed


def all_records() -> list[dict[str, Any]]:
    return list(iter_records(read_shards()))


def reveal_image(sample_id: str) -> str:
    record = next((r for r in all_records() if r["sample_id"] == sample_id), None)
    if record is None:
        raise KeyError(f"Unknown sample_id: {sample_id}")
    image_path = (PROJECT_ROOT / record["asset"]["path"]).resolve()
    image_path.relative_to(PROJECT_ROOT.resolve())
    if not image_path.is_file():
        raise FileNotFoundError("Bilddatei fehlt.")
    if sys.platform == "darwin":
        command = ["open", "-R", str(image_path)]
    elif os.name == "nt":
        command = ["explorer", f"/select,{image_path}"]
    else:
        command = ["xdg-open", str(image_path.parent)]
    subprocess.Popen(command)
    return record["asset"]["path"]


class Handler(BaseHTTPRequestHandler):
    server_version = "VIPIOCRReview/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: Any) -> None:
        pass

    def respond(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def respond_json(self, status: int, value: Any) -> None:
        self.respond(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        request = urlparse(self.path)
        if request.path == "/":
            try:
                self.respond(200, UI_PATH.read_bytes(), "text/html; charset=utf-8")
            except OSError as exc:
                self.respond_json(500, {"error": str(exc)})
            return
        if request.path == "/api/queue":
            try:
                params = parse_qs(request.query)
                dataset_id = params.get("dataset", [""])[0]
                status_filter = params.get("status", ["pending"])[0]
                records = [r for r in all_records() if r.get("eligibility", {}).get("ocr_eval") is True]
                if dataset_id:
                    records = [r for r in records if r["source"]["dataset_id"] == dataset_id]
                if status_filter == "pending":
                    records = [r for r in records if not r["ocr"]["annotation"]["verified"]]
                elif status_filter == "approved":
                    records = [r for r in records if r["ocr"]["annotation"]["verified"]]
                datasets = Counter(r["source"]["dataset_id"] for r in all_records() if r.get("eligibility", {}).get("ocr_eval") is True)
                unverified = sum(not r["ocr"]["annotation"]["verified"] for r in all_records() if r.get("eligibility", {}).get("ocr_eval") is True)
                verified = sum(r["ocr"]["annotation"]["verified"] for r in all_records() if r.get("eligibility", {}).get("ocr_eval") is True)
                self.respond_json(200, {
                    "items": [{
                        "sample_id": r["sample_id"], "dataset_id": r["source"]["dataset_id"],
                        "verified": r["ocr"]["annotation"]["verified"],
                        "transcript": r["ocr"]["transcript_verbatim"],
                    } for r in records],
                    "datasets": [{"id": key, "count": value} for key, value in sorted(datasets.items())],
                    "pending": unverified, "approved": verified,
                })
            except Exception as exc:
                self.respond_json(500, {"error": str(exc)})
            return
        if request.path == "/api/record":
            sample_id = parse_qs(request.query).get("id", [""])[0]
            try:
                record = next(r for r in all_records() if r["sample_id"] == sample_id)
            except StopIteration:
                self.respond_json(404, {"error": "Eintrag nicht gefunden."})
                return
            except Exception as exc:
                self.respond_json(500, {"error": str(exc)})
                return
            self.respond_json(200, {"record": record, "revision": fingerprint(record)})
            return
        if request.path == "/api/schema":
            try:
                self.respond(200, SCHEMA_PATH.read_bytes(), "application/schema+json; charset=utf-8")
            except OSError as exc:
                self.respond_json(500, {"error": str(exc)})
            return
        if request.path == "/image":
            sample_id = parse_qs(request.query).get("id", [""])[0]
            try:
                record = next(r for r in all_records() if r["sample_id"] == sample_id)
                image_path = (PROJECT_ROOT / record["asset"]["path"]).resolve()
                image_path.relative_to(PROJECT_ROOT.resolve())
                if not image_path.is_file():
                    raise FileNotFoundError("Bilddatei fehlt.")
                content_type = record["asset"].get("media_type", "application/octet-stream")
                self.respond(200, image_path.read_bytes(), content_type)
            except (StopIteration, ValueError, FileNotFoundError):
                self.respond_json(404, {"error": "Bild nicht gefunden."})
            except Exception as exc:
                self.respond_json(500, {"error": str(exc)})
            return
        self.respond_json(404, {"error": "Nicht gefunden."})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        request_path = urlparse(self.path).path
        if request_path not in {"/api/save", "/api/save-metadata", "/api/reveal-image"}:
            self.respond_json(404, {"error": "Nicht gefunden."})
            return
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(("http://127.0.0.1:", "http://localhost:")):
            self.respond_json(403, {"error": "Nur lokale Anfragen sind erlaubt."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Ungültige Anfragegröße.")
            body = json.loads(self.rfile.read(length))
            if request_path == "/api/reveal-image":
                path = reveal_image(str(body["sample_id"]))
                result = {"path": path}
            elif request_path == "/api/save":
                result = update_record(
                    str(body["sample_id"]), str(body["revision"]), str(body["text"]), bool(body["approve"])
                )
            else:
                result = update_metadata(
                    str(body["sample_id"]), str(body["revision"]), body["metadata"]
                )
            self.respond_json(200, result)
        except KeyError as exc:
            self.respond_json(404 if str(exc).startswith("'Unknown") else 400, {"error": str(exc)})
        except RuntimeError as exc:
            self.respond_json(409, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            self.respond_json(400, {"error": str(exc)})
        except FileNotFoundError as exc:
            self.respond_json(404, {"error": str(exc)})
        except OSError as exc:
            self.respond_json(500, {"error": str(exc)})
        except Exception as exc:
            self.respond_json(500, {"error": str(exc)})


def main() -> int:
    args = parse_args()
    if args.mark_reviewed_dataset:
        total, previously_reviewed = mark_dataset_reviewed(args.mark_reviewed_dataset)
        print(
            f"Marked {total} {args.mark_reviewed_dataset} target_text_only records as gold; "
            f"{previously_reviewed} were already verified. The OCR scope was preserved."
        )
        return 0
    if args.check:
        records = [r for r in all_records() if r.get("eligibility", {}).get("ocr_eval") is True]
        pending = sum(not r["ocr"]["annotation"]["verified"] for r in records)
        print(f"OCR records: {len(records)}; pending manual review: {pending}")
        for dataset_id, count in sorted(Counter(r["source"]["dataset_id"] for r in records).items()):
            print(f"  {dataset_id}: {count}")
        return 0
    if not UI_PATH.is_file():
        raise SystemExit(f"Review UI is missing: {UI_PATH}")
    if not 0 < args.port < 65536:
        raise SystemExit("Port must be between 1 and 65535.")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"OCR review UI: http://127.0.0.1:{args.port} (only accessible on this computer)")
    print("Press Ctrl+C to stop. Saves update the source shard and metadata.jsonl immediately.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nReview server stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
