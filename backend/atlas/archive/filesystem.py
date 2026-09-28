"""Filesystem backend: one read-only file per object under the archive root."""

import contextlib
import os
import tempfile
from pathlib import Path

from atlas.archive import ArchiveError, ObjectNotFound


class FilesystemStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def __repr__(self) -> str:
        return "FilesystemStore()"

    def contains(self, key: str) -> bool:
        return (self._root / key).is_file()

    def read(self, key: str) -> bytes:
        try:
            return (self._root / key).read_bytes()
        except FileNotFoundError:
            raise ObjectNotFound(key) from None

    def create(self, key: str, data: bytes, sha256: str) -> None:
        # The root is the mounted archive volume; never create it implicitly.
        if not self._root.is_dir():
            raise ArchiveError("archive root is not available")
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write a complete temporary file, then hard-link it into place: the link
        # fails if the key exists, so a finished object is never replaced and a
        # partial one is never visible.
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{sha256}.")
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.chmod(temporary, 0o444)
            with contextlib.suppress(FileExistsError):
                os.link(temporary, path)
        finally:
            os.unlink(temporary)

    def is_ready(self) -> bool:
        return self._root.is_dir() and os.access(self._root, os.W_OK)
