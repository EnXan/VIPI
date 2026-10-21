"""Caller-owned context, never inferred from inspected content."""

import json


def validate_context(value=None):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Caller context must be a JSON object.")
    fields = {"task", "expected_behavior", "allowed_actions", "constraints", "source"}
    if set(value) - fields:
        raise ValueError("Unknown caller context field.")
    result = {}
    for key, item in value.items():
        if item is None:
            continue
        if key in {"allowed_actions", "constraints"}:
            if not isinstance(item, list) or not all(isinstance(x, str) for x in item):
                raise ValueError(f"{key} must be a list of strings.")
        elif key == "source":
            if not isinstance(item, dict) or set(item) - {"origin", "authority"}:
                raise ValueError("source accepts origin and authority strings.")
            if not all(isinstance(x, str) for x in item.values()):
                raise ValueError("source values must be strings.")
        elif not isinstance(item, str):
            raise ValueError(f"{key} must be a string.")
        result[key] = item
    if len(json.dumps(result, ensure_ascii=False).encode()) > 8192:
        raise ValueError("Caller context exceeds 8 KiB; provide a concise context.")
    return result
