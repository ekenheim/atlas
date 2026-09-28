"""Archive contract suite: the same behavior from the filesystem and the S3 backend.

Each backend fixture wraps a real store (a temporary directory, or a fresh bucket on
the Compose S3 server) and exposes the stored state of a key, as seen from outside the
archive, so the suite can check that nothing is ever overwritten. Keys follow the
documented layout `<namespace>/sha256/<hex>`.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from mypy_boto3_s3 import S3Client

from atlas.archive import (
    Archive,
    ArchiveIntegrityError,
    InvalidArchiveUri,
    Namespace,
    ObjectNotFound,
    open_archive,
)
from atlas.settings import Settings
from tests.integration.conftest import (
    S3_ACCESS_KEY_ID,
    S3_ENDPOINT_URL,
    S3_SECRET_ACCESS_KEY,
    s3_settings,
)

# SHA-256 digests of the fixture payloads (independently known values).
HELLO = b"hello"
HELLO_SHA256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@dataclass
class Backend:
    archive: Archive
    # The stored state of a key as observed outside the archive (content plus a
    # write identity: inode/mtime on disk, the version list in S3).
    stored_state: Callable[[str], object]
    # Store bytes under a key directly, bypassing the archive.
    plant: Callable[[str, bytes], None]
    # Values that must never appear in an archive URI.
    secrets: list[str]


def base_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://atlas:atlas@127.0.0.1:1/atlas",
        "actor": "local-researcher",
        "archive_root": tmp_path / "archive",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def filesystem_backend(tmp_path: Path) -> Backend:
    root = tmp_path / "archive"
    root.mkdir()

    def stored_state(key: str) -> object:
        path = root / key
        if not path.exists():
            return None
        stat = path.stat()
        return (path.read_bytes(), stat.st_ino, stat.st_mtime_ns)

    def plant(key: str, data: bytes) -> None:
        path = root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    return Backend(open_archive(base_settings(tmp_path)), stored_state, plant, [str(root)])


def s3_backend(tmp_path: Path, admin: S3Client, bucket: str) -> Backend:
    def stored_state(key: str) -> object:
        listing = admin.list_object_versions(Bucket=bucket, Prefix=key)
        versions = [v.get("VersionId") for v in listing.get("Versions", [])]
        markers = [m.get("VersionId") for m in listing.get("DeleteMarkers", [])]
        if not versions:
            return None
        body = admin.get_object(Bucket=bucket, Key=key)["Body"].read()
        return (body, versions, markers)

    def plant(key: str, data: bytes) -> None:
        admin.put_object(Bucket=bucket, Key=key, Body=data)

    archive = open_archive(base_settings(tmp_path, **s3_settings(bucket)))
    secrets = [bucket, S3_ENDPOINT_URL, "127.0.0.1", S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY]
    return Backend(archive, stored_state, plant, secrets)


@pytest.fixture(params=["filesystem", "s3"])
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Backend]:
    if request.param == "filesystem":
        yield filesystem_backend(tmp_path)
    else:
        admin: S3Client = request.getfixturevalue("s3_admin")
        bucket: str = request.getfixturevalue("s3_bucket")
        yield s3_backend(tmp_path, admin, bucket)


def test_put_returns_an_internal_content_addressed_uri(backend: Backend) -> None:
    uri = backend.archive.put(Namespace.RAW, HELLO)

    assert uri == f"archive://raw/sha256/{HELLO_SHA256}"
    for secret in backend.secrets:
        assert secret not in uri


def test_raw_and_parsed_objects_live_in_separate_namespaces(backend: Backend) -> None:
    raw = backend.archive.put(Namespace.RAW, HELLO)

    parsed = f"archive://parsed/sha256/{HELLO_SHA256}"
    assert backend.archive.exists(raw)
    assert not backend.archive.exists(parsed)
    with pytest.raises(ObjectNotFound):
        backend.archive.get(parsed)

    assert backend.archive.put(Namespace.PARSED, HELLO) == parsed
    assert backend.archive.get(parsed) == HELLO
    assert backend.stored_state(f"raw/sha256/{HELLO_SHA256}") is not None
    assert backend.stored_state(f"parsed/sha256/{HELLO_SHA256}") is not None


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(bytes(range(256)) * 64, id="all-byte-values"),
        pytest.param(b"line one\r\nline two\n\x00trailing \r", id="crlf-and-nul"),
        pytest.param("Lumentum Holdings Inc. — 10-K § 1A".encode(), id="utf8"),
        pytest.param(b"", id="empty"),
    ],
)
def test_get_returns_exactly_the_bytes_that_were_put(backend: Backend, data: bytes) -> None:
    uri = backend.archive.put(Namespace.RAW, data)

    assert backend.archive.get(uri) == data


def test_empty_object_has_the_well_known_empty_digest(backend: Backend) -> None:
    assert backend.archive.put(Namespace.PARSED, b"") == f"archive://parsed/sha256/{EMPTY_SHA256}"


def test_put_is_idempotent_by_hash_and_writes_only_once(backend: Backend) -> None:
    key = f"raw/sha256/{HELLO_SHA256}"
    first = backend.archive.put(Namespace.RAW, HELLO)
    state_after_first = backend.stored_state(key)

    second = backend.archive.put(Namespace.RAW, HELLO)

    assert second == first
    assert backend.stored_state(key) == state_after_first
    assert backend.archive.get(second) == HELLO


def test_put_never_overwrites_an_existing_object(backend: Backend) -> None:
    # Something already sits under the key (e.g. a concurrent or corrupted write).
    key = f"raw/sha256/{HELLO_SHA256}"
    backend.plant(key, b"not hello")
    planted = backend.stored_state(key)

    uri = backend.archive.put(Namespace.RAW, HELLO)

    assert backend.stored_state(key) == planted
    # The archive refuses to return bytes that don't match their address.
    with pytest.raises(ArchiveIntegrityError):
        backend.archive.get(uri)


def test_missing_object_is_reported_as_not_found(backend: Backend) -> None:
    uri = f"archive://raw/sha256/{HELLO_SHA256}"

    assert not backend.archive.exists(uri)
    with pytest.raises(ObjectNotFound):
        backend.archive.get(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "s3://atlas-archive/raw/sha256/" + HELLO_SHA256,
        "file:///etc/passwd",
        "archive://raw/sha256/../../../etc/passwd",
        "archive://raw/sha256/" + HELLO_SHA256.upper(),
        "archive://raw/sha256/" + HELLO_SHA256[:-1],
        "archive://other/sha256/" + HELLO_SHA256,
        "archive://raw/md5/5d41402abc4b2a76b9719d911017c592",
        "archive://raw/sha256/" + HELLO_SHA256 + "/",
    ],
)
def test_anything_but_an_archive_uri_is_rejected(backend: Backend, uri: str) -> None:
    with pytest.raises(InvalidArchiveUri):
        backend.archive.get(uri)
    with pytest.raises(InvalidArchiveUri):
        backend.archive.exists(uri)


def test_backend_is_ready_when_its_store_is_available(backend: Backend) -> None:
    assert backend.archive.is_ready()


def test_archive_repr_exposes_no_credentials(backend: Backend) -> None:
    assert S3_SECRET_ACCESS_KEY not in repr(backend.archive)
    assert S3_SECRET_ACCESS_KEY not in str(backend.archive)
