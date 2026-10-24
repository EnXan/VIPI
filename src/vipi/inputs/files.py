"""Recursive local image discovery."""

import os
from pathlib import Path
from .types import EXTENSIONS, Selection
from .exclusions import ExclusionRules, repository_or_scope_root

EXCLUDED_DIRECTORIES = {".git", "__pycache__", "node_modules"}


def select_images(paths, *, diff=None, excluded=(), exclude_patterns=()):
    scopes = [Path(os.path.abspath(path)) for path in paths]
    scopes = [scope.parent.resolve() / scope.name for scope in scopes]
    if diff is not None:
        from .git import select_diff

        roots = {repository_or_scope_root(scope) for scope in scopes}
        if exclude_patterns or any((root / ".vipiignore").exists() for root in roots):
            raise ValueError(
                "User exclusions are not supported for Git diff scans yet."
            )
        return select_diff(paths, diff, excluded=excluded)
    selection = Selection()
    excluded = [Path(path).resolve() for path in excluded]
    rules_by_root = {}

    def excluded_path(path):
        return any(path == root or root in path.parents for root in excluded)

    def rules_for(scope):
        root = repository_or_scope_root(scope)
        if root not in rules_by_root:
            rules_by_root[root] = ExclusionRules(root, exclude_patterns)
        return rules_by_root[root]

    def record_exclusion(path, rule, *, is_dir=False):
        selection.skipped.append(
            {
                "path": str(path),
                "reason": "excluded_by_user",
                "rule": rule.raw,
                "source": rule.source,
                **({"directory": True} if is_dir else {}),
            }
        )
        if rule.source == "command line --exclude":
            selection.skipped[-1]["argument"] = rule.line
        else:
            selection.skipped[-1]["line"] = rule.line

    for scope in scopes:
        if scope.is_symlink():
            selection.errors.append(
                {"path": str(scope), "error": "Symlink inputs are not supported."}
            )
        elif scope.is_file():
            if scope.suffix.lower() not in EXTENSIONS:
                selection.errors.append(
                    {
                        "path": str(scope),
                        "error": "Use a static PNG, JPEG or WebP image.",
                    }
                )
            elif excluded_path(scope):
                selection.add(scope, excluded=excluded)
            else:
                rules = rules_for(scope)
                decision = rules.decision(scope)
                if decision is not None and not decision[1].include:
                    record_exclusion(scope, decision[1])
                else:
                    selection.add(scope, excluded=excluded)
        elif scope.is_dir():
            if excluded_path(scope):
                selection.skipped.append(
                    {"path": str(scope), "reason": "scanner_cache"}
                )
                continue

            def walk_error(error):
                selection.errors.append(
                    {
                        "path": str(error.filename),
                        "error": "Directory cannot be read.",
                    }
                )

            for directory, subdirectories, files in os.walk(
                scope, onerror=walk_error, followlinks=False
            ):
                rules = rules_for(scope)
                root = Path(directory)
                retained = []
                for name in sorted(subdirectories):
                    child = root / name
                    if (
                        name in EXCLUDED_DIRECTORIES
                        or name.startswith(".venv")
                        or child.is_symlink()
                        or excluded_path(child)
                    ):
                        selection.skipped.append(
                            {"path": str(child), "reason": "excluded_directory"}
                        )
                    else:
                        decision = rules.decision(child, is_dir=True)
                        if decision is None or decision[1].include:
                            retained.append(name)
                        elif rules.may_include_descendant(decision):
                            retained.append(name)
                        else:
                            record_exclusion(child, decision[1], is_dir=True)
                subdirectories[:] = retained
                for name in sorted(files):
                    path = root / name
                    if path.suffix.lower() not in EXTENSIONS or path.is_symlink():
                        selection.add(path, excluded=excluded)
                        continue
                    if excluded_path(path):
                        selection.add(path, excluded=excluded)
                        continue
                    decision = rules.decision(path)
                    if decision is not None and not decision[1].include:
                        record_exclusion(path, decision[1])
                    else:
                        selection.add(path, excluded=excluded)
        else:
            selection.errors.append(
                {
                    "path": str(scope),
                    "error": "Input does not exist or is not a regular file/directory.",
                }
            )

    selection.images.sort(key=lambda image: str(image.path))
    return selection
