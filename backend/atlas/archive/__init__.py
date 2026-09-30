"""Archive: immutable, content-addressed objects behind one small interface.

`put` stores bytes and returns an internal application URI keyed by their SHA-256:
`archive://<namespace>/sha256/<hex>`. Raw fetched bytes, parsed text and Research
Snapshots (canonical JSON, atlas.snapshots) live in separate namespaces. A put is
idempotent by hash and never overwrites; `get` returns exactly the stored bytes and
refuses any whose hash no longer matches their URI.

URIs carry no backend location or credentials, so they are safe to store and expose.
Two backends store objects under the same key, `<namespace>/sha256/<hex>`: a local
directory (`ATLAS_ARCHIVE_ROOT`) or an S3 bucket (MinIO in the cluster, Silo in dev/CI),
whose object lock and versioning are what make the archive immutable in deployment.
"""

import hashlib
import re
from enum import StrEnum
from typing import Protocol

from atlas.settings import Settings

__all__ = [
    "Archive",
    "ArchiveError",
    "ArchiveIntegrityError",
    "InvalidArchiveUri",
    "Namespace",
    "ObjectNotFound",
    "open_archive",
]


class Namespace(StrEnum):
    RAW = "raw"
    PARSED = "parsed"
    SNAPSHOTS = "snapshots"


class ArchiveError(Exception):
    """Base class for archive failures."""


class InvalidArchiveUri(ArchiveError, ValueError):
    """The value is not an archive URI."""


class ObjectNotFound(ArchiveError, LookupError):
    """No object is stored under the URI."""


class ArchiveIntegrityError(ArchiveError):
    """The stored bytes no longer hash to their URI."""


class ObjectStore(Protocol):
    """A backend: a flat keyspace of write-once objects."""

    def contains(self, key: str) -> bool: ...

    def read(self, key: str) -> bytes:
        """The object's bytes; raises ObjectNotFound."""
        ...

    def create(self, key: str, data: bytes, sha256: str) -> None:
        """Store the object unless the key already exists; never overwrite."""
        ...

    def is_ready(self) -> bool: ...


_URI = re.compile(r"archive://(?P<namespace>raw|parsed|snapshots)/sha256/(?P<digest>[0-9a-f]{64})")


def _key(uri: str) -> tuple[str, str]:
    """The object key and expected digest for an archive URI."""
    match = _URI.fullmatch(uri)
    if match is None:
        raise InvalidArchiveUri("not an archive URI")
    return f"{match['namespace']}/sha256/{match['digest']}", match["digest"]


class Archive:
    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def __repr__(self) -> str:
        return f"Archive({self._store!r})"

    def put(self, namespace: Namespace, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        uri = f"archive://{namespace}/sha256/{digest}"
        key, _ = _key(uri)
        if not self._store.contains(key):
            self._store.create(key, data, digest)
        return uri

    def get(self, uri: str) -> bytes:
        key, digest = _key(uri)
        data = self._store.read(key)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ArchiveIntegrityError(f"stored bytes do not match {uri}")
        return data

    def exists(self, uri: str) -> bool:
        key, _ = _key(uri)
        return self._store.contains(key)

    def is_ready(self) -> bool:
        """Whether the backend can be written to right now (for readiness)."""
        return self._store.is_ready()


def open_archive(settings: Settings) -> Archive:
    """The archive for the configured backend. Opening it touches no network."""
    if settings.archive_backend == "s3":
        from atlas.archive.s3 import S3Store

        return Archive(S3Store.from_settings(settings))
    from atlas.archive.filesystem import FilesystemStore

    return Archive(FilesystemStore(settings.archive_root))
