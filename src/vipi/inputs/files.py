"""Recursive local image discovery."""

import os
from pathlib import Path
from .types import EXTENSIONS, Selection

EXCLUDED_DIRECTORIES = {".git", "__pycache__", "node_modules"}


def select_images(paths, *, diff=None, excluded=()):
    if diff is not None:
        from .git import select_diff

        return select_diff(paths, diff, excluded=excluded)
    selection = Selection()
    scopes = [Path(os.path.abspath(path)) for path in paths]
    scopes = [scope.parent.resolve() / scope.name for scope in scopes]
    excluded = [Path(path).resolve() for path in excluded]

    def excluded_path(path):
        return any(path == root or root in path.parents for root in excluded)

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
                        retained.append(name)
                subdirectories[:] = retained
                for name in sorted(files):
                    selection.add(root / name, excluded=excluded)
        else:
            selection.errors.append(
                {
                    "path": str(scope),
                    "error": "Input does not exist or is not a regular file/directory.",
                }
            )

    selection.images.sort(key=lambda image: str(image.path))
    return selection
