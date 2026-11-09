"""Model label proposals that a person approves or denies.

Agents write ``proposals/batch-*.json`` next to the draft; they never edit the
catalog. Decisions are kept in ``proposals/decisions.json`` so a decided
proposal is not offered again. Approving applies the proposal through the
normal validated store update and adds any new values it introduced.
"""

import json

from .store import write_json
from .vocabulary import FIELDS, allowed, normalize

DECISIONS_NAME = "decisions.json"


class ProposalBook:
    def __init__(self, store):
        self.store = store

    @property
    def directory(self):
        return self.store.directory / "proposals"

    def batches(self):
        return sorted(self.directory.glob("batch-*.json"))

    def decisions(self):
        path = self.directory / DECISIONS_NAME
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def load(self):
        """Return the latest proposal per entry id, newest batch file last."""
        found = {}
        for path in self.batches():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise ValueError(f"{path.name} is not valid JSON: {error}") from error
            for item in data.get("proposals", []):
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    found[item["id"]] = {
                        **item,
                        "batch": path.name,
                        "model": data.get("model"),
                    }
        return found

    def problems(self, proposal, vocabulary):
        """Reasons a proposal cannot be applied as written."""
        issues = []
        offered = {
            (item.get("field"), normalize(item.get("value", "")))
            for item in proposal.get("new_values", [])
            if isinstance(item, dict)
        }
        for field in FIELDS:
            value = proposal.get(field)
            values = value if isinstance(value, list) else [value] if value else []
            for item in values:
                if not isinstance(item, str):
                    issues.append(f"{field} has a non-text value")
                elif (
                    item not in allowed(vocabulary, field)
                    and (field, item) not in offered
                ):
                    issues.append(
                        f"{field} value {item!r} is neither in the vocabulary nor proposed as new"
                    )
        return issues

    def pending(self):
        decided = self.decisions()
        return {key: value for key, value in self.load().items() if key not in decided}

    def get(self, identifier):
        _, vocabulary = self.store.load()
        proposal = self.load().get(identifier)
        if proposal is None:
            return None
        return {
            **proposal,
            "status": self.decisions().get(identifier, "pending"),
            "problems": self.problems(proposal, vocabulary),
        }

    def record(self, identifier, decision):
        decisions = {**self.decisions(), identifier: decision}
        self.directory.mkdir(parents=True, exist_ok=True)
        write_json(self.directory / DECISIONS_NAME, decisions)

    def approve(self, identifier):
        """Add proposed new values that are used, then apply and mark reviewed."""
        proposal = self.get(identifier)
        if proposal is None:
            raise KeyError(identifier)
        if proposal["status"] != "pending":
            raise ValueError(f"This proposal was already {proposal['status']}.")
        if proposal["problems"]:
            raise ValueError("; ".join(proposal["problems"]))
        changes = {field: proposal.get(field) for field in FIELDS if field in proposal}
        for field in FIELDS:
            if field in changes and isinstance(changes[field], list):
                changes[field] = list(dict.fromkeys(changes[field]))
        _, vocabulary = self.store.load()
        for item in proposal.get("new_values", []):
            field, value = item.get("field"), normalize(item.get("value", ""))
            used = changes.get(field)
            used = used if isinstance(used, list) else [used]
            if (
                field in FIELDS
                and value in used
                and value not in allowed(vocabulary, field)
            ):
                self.store.add_value(
                    field, value, item.get("description", ""), confirm=True
                )
                _, vocabulary = self.store.load()
        entry = self.store.update(
            identifier, {**changes, "curation": {"reviewed": True}}
        )
        self.record(identifier, "approved")
        return entry

    def deny(self, identifier):
        proposal = self.get(identifier)
        if proposal is None:
            raise KeyError(identifier)
        self.record(identifier, "denied")
        return {"id": identifier, "status": "denied"}

    def counts(self):
        decided = self.decisions()
        proposals = self.load()
        return {
            "proposals": len(proposals),
            "pending": sum(key not in decided for key in proposals),
            "approved": sum(decided.get(key) == "approved" for key in proposals),
            "denied": sum(decided.get(key) == "denied" for key in proposals),
        }
