"""Ordered path exclusion rules for image selection."""

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class ExclusionRule:
    raw: str
    pattern: str
    source: str
    line: int
    include: bool
    directory_only: bool
    basename_only: bool

    def matches(self, relative_path, *, is_dir):
        parts = PurePosixPath(relative_path).parts
        for length in range(1, len(parts) + 1):
            prefix = parts[:length]
            prefix_is_dir = length < len(parts) or is_dir
            if self.directory_only and not prefix_is_dir:
                continue
            if self.basename_only:
                if fnmatchcase(prefix[-1], self.pattern):
                    return True
            elif _match_components(self.pattern.split("/"), prefix):
                return True
        return False


def _match_components(pattern, path):
    """Match slash-separated patterns; a `**` component spans directories."""
    previous = [False] * (len(path) + 1)
    previous[0] = True
    for component in pattern:
        current = [False] * (len(path) + 1)
        if component == "**":
            current[0] = previous[0]
            for index in range(1, len(path) + 1):
                current[index] = previous[index] or current[index - 1]
        else:
            for index in range(1, len(path) + 1):
                current[index] = previous[index - 1] and fnmatchcase(
                    path[index - 1], component
                )
        previous = current
    return previous[-1]


def _parse_rule(raw, *, source, line):
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None

    include = raw.startswith("!")
    pattern = raw[1:] if include else raw
    pattern = pattern.replace("\\", "/")
    root_anchored = pattern.startswith("/")
    if root_anchored:
        pattern = pattern[1:]
    directory_only = pattern.endswith("/")
    if directory_only:
        pattern = pattern[:-1]
    parts = pattern.split("/")
    if not pattern or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(
            f"Invalid exclusion rule at {source}:{line}: {raw!r}. "
            "Rules must be non-empty paths inside the scan root."
        )

    return ExclusionRule(
        raw=raw,
        pattern=pattern,
        source=str(source),
        line=line,
        include=include,
        directory_only=directory_only,
        basename_only="/" not in pattern and not root_anchored,
    )


def _parse_lines(lines, *, source):
    rules = []
    for line_number, line in enumerate(lines, 1):
        rule = _parse_rule(line, source=source, line=line_number)
        if rule is not None:
            rules.append(rule)
    return rules


class ExclusionRules:
    """File rules followed by command-line rules, with last-match precedence."""

    def __init__(self, root, cli_patterns=()):
        self.root = Path(root)
        self.rules = []
        config_path = self.root / ".vipiignore"
        if config_path.exists():
            try:
                lines = config_path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError) as error:
                raise ValueError(
                    f"Could not read exclusion file {config_path}: {error}"
                ) from error
            self.rules.extend(_parse_lines(lines, source=config_path))

        for index, pattern in enumerate(cli_patterns, 1):
            rule = _parse_rule(
                pattern, source="command line --exclude", line=index
            )
            if rule is None:
                raise ValueError("--exclude requires a non-empty rule.")
            self.rules.append(rule)

    def decision(self, path, *, is_dir=False):
        relative = Path(path).relative_to(self.root).as_posix()
        last_match = None
        for index, rule in enumerate(self.rules):
            if rule.matches(relative, is_dir=is_dir):
                last_match = (index, rule)
        return last_match

    def may_include_descendant(self, decision):
        if decision is None:
            return False
        index, _ = decision
        return any(rule.include for rule in self.rules[index + 1 :])


def repository_or_scope_root(scope):
    """Use the Git root, or the input directory when outside a repository."""
    scope = Path(scope)
    anchor = scope.parent if scope.is_symlink() or scope.is_file() else scope
    for parent in (anchor, *anchor.parents):
        if (parent / ".git").exists():
            return parent
    return anchor
