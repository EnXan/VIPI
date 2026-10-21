"""Image sources and discovery results shared by file and Git inputs."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import tempfile

EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class ImageSource:
    path: Path
    blob: str | None = None
    repository: Path | None = None

    @contextmanager
    def local_file(self):
        if self.blob is None:
            yield self.path
            return
        from .git import git

        with tempfile.TemporaryDirectory(prefix="vipi-image-") as temporary:
            image = Path(temporary) / ("input" + self.path.suffix)
            image.write_bytes(git(self.repository, "cat-file", "blob", self.blob))
            yield image


@dataclass
class Selection:
    images: list[ImageSource] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    diff: dict | None = None
    repository: Path | None = None
    _seen: set[Path] = field(default_factory=set, repr=False)

    def add(self, path, blob=None, mode=None, *, excluded=()):
        if path in self._seen:
            return
        self._seen.add(path)
        if path.suffix.lower() not in EXTENSIONS:
            self.skipped.append({"path": str(path), "reason": "unsupported_type"})
        elif mode is not None and mode not in {b"100644", b"100755"}:
            self.errors.append(
                {"path": str(path), "error": "Image is not a regular Git file."}
            )
        elif blob is None and path.is_symlink():
            self.errors.append(
                {"path": str(path), "error": "Image symlinks are not supported."}
            )
        elif any(path == root or root in path.parents for root in excluded):
            self.skipped.append({"path": str(path), "reason": "scanner_cache"})
        else:
            self.images.append(ImageSource(path, blob, self.repository))
