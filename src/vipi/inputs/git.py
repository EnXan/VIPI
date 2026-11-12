"""Immutable branch-diff inputs from Git objects."""

import os
from pathlib import Path
import subprocess
from .exclusions import ExclusionRules
from .types import Selection


def git(repository, *arguments):
    result = subprocess.run(
        ["git", "--no-pager", "-c", "core.fsmonitor=false", *arguments],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        # Do not echo Git stderr: repository configuration can contain credentials.
        raise ValueError(
            "Git comparison failed. Check the reference and fetch sufficient history "
            "for a common ancestor (in Actions, use checkout with fetch-depth: 0)."
        )
    return result.stdout


def select_diff(paths, diff, *, excluded=(), exclude_patterns=()):
    selection = Selection()
    scopes = [Path(os.path.abspath(path)) for path in paths]
    repository = Path(
        os.fsdecode(git(Path.cwd(), "rev-parse", "--show-toplevel")).removesuffix("\n")
    )
    selection.repository = repository
    if any(scope != repository and repository not in scope.parents for scope in scopes):
        raise ValueError("Diff scan paths must be inside the current Git repository.")
    head = git(repository, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    base = (
        git(
            repository,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{diff}^{{commit}}",
        )
        .decode()
        .strip()
    )
    ancestor = git(repository, "merge-base", base, head).decode().strip()
    rules = base_rules(repository, diff, base, exclude_patterns)
    selection.diff = {
        "reference": diff,
        "base": base,
        "merge_base": ancestor,
        "head": head,
    }
    entries = git(
        repository,
        "diff",
        "--raw",
        "-z",
        "--no-abbrev",
        "--no-renames",
        "--no-ext-diff",
        "--no-textconv",
        "--diff-filter=AMT",
        ancestor,
        head,
        "--",
    ).split(b"\0")
    for index in range(0, len(entries) - 1, 2):
        metadata, name = entries[index : index + 2]
        _, mode, _, blob, _ = metadata.split()
        path = repository / os.fsdecode(name)
        if not any(path == scope or scope in path.parents for scope in scopes):
            continue
        decision = rules.decision(path)
        if decision is not None and not decision[1].include:
            selection.skip_excluded(path, decision[1])
        else:
            selection.add(path, blob.decode("ascii"), mode, excluded=excluded)

    selection.images.sort(key=lambda image: str(image.path))
    return selection


def base_rules(repository, reference, base, exclude_patterns):
    """Read `.vipiignore` from the base commit so the compared branch cannot change it."""
    entry = git(repository, "ls-tree", "-z", base, "--", ".vipiignore")
    source = f"{reference}:.vipiignore"
    if not entry:
        return ExclusionRules(repository, exclude_patterns, file_lines=())
    mode, kind, blob = entry.split(b"\t", 1)[0].split()
    if kind != b"blob" or mode not in {b"100644", b"100755"}:
        raise ValueError(f"Could not read exclusion file {source}: not a regular file.")
    try:
        lines = git(repository, "cat-file", "blob", blob.decode("ascii"))
        lines = lines.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise ValueError(f"Could not read exclusion file {source}: {error}") from error
    return ExclusionRules(
        repository, exclude_patterns, file_lines=lines, file_source=source
    )
