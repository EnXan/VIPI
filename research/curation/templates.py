"""Describe the screenshot templates: size, the spec fields each one reads and
the existing specs that use it, so a new spec can start from a working item."""

import ast
import inspect
import json
from pathlib import Path

from . import screen_templates
from .screen_templates import SIZES, TEMPLATES

SPECS = Path(__file__).resolve().parent / "generated"
# Read by every template through screens.py, not by the template function.
COMMON_FIELDS = (
    "text",
    "kind",
    "obfuscation",
    "template",
    "label",
    "content",
    "techniques",
    "goal",
    "evidence",
    "theme_seed",
    "dark",
    "target_only_obfuscation",
    "decoy_text",
)


def item_keys(function, seen=None):
    """Spec fields a template reads (``item["x"]``, ``item.get("x")``),
    including helpers it passes ``item`` to."""
    seen = set() if seen is None else seen
    if function.__name__ in seen:
        return set()
    seen.add(function.__name__)
    keys = set()
    for node in ast.walk(ast.parse(inspect.getsource(function))):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "item"
            and isinstance(node.slice, ast.Constant)
        ):
            keys.add(node.slice.value)
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if (
            isinstance(callee, ast.Attribute)
            and callee.attr == "get"
            and isinstance(callee.value, ast.Name)
            and callee.value.id == "item"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            keys.add(node.args[0].value)
        if (
            isinstance(callee, ast.Name)
            and any(isinstance(arg, ast.Name) and arg.id == "item" for arg in node.args)
            and inspect.isfunction(getattr(screen_templates, callee.id, None))
        ):
            keys |= item_keys(getattr(screen_templates, callee.id), seen)
    return {key for key in keys if isinstance(key, str)}


def examples(directory=SPECS):
    """``{template: [(spec file, item number), ...]}`` from the existing specs."""
    found = {}
    for path in sorted(Path(directory).glob("*.json")):
        items = json.loads(path.read_text(encoding="utf-8")).get("items", [])
        for number, item in enumerate(items, 1):
            if "template" in item:
                found.setdefault(item["template"], []).append((path.name, number))
    return found


def describe(directory=SPECS):
    used = examples(directory)
    return [
        {
            "template": name,
            "size": SIZES[name],
            "wordless": name.startswith("wordless_"),
            "fields": sorted(item_keys(function) - set(COMMON_FIELDS)),
            "examples": used.get(name, []),
        }
        for name, function in TEMPLATES.items()
    ]
