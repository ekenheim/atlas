"""Object-lock semantics of the archive bucket, against the Compose S3 server (Silo).

The cluster bucket is object-locked in Governance mode, and so is the bucket here. A
lock protects versions, not keys: an overwrite creates a new version and a plain delete
adds a delete marker, while permanently deleting a locked version is refused without
the bypass header. Error codes differ between servers (Silo and MinIO answer 400
InvalidRequest, others 403 AccessDenied), so these tests assert behavior only.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from mypy_boto3_s3 import S3Client

from atlas.archive import Archive, ArchiveIntegrityError, Namespace, open_archive
from atlas.settings import Settings
from tests.integration.conftest import (
    delete_bucket_with_versions,
    s3_admin_client,
    s3_settings,
    unique_bucket_name,
)


@pytest.fixture(scope="module")
def locked_bucket() -> Iterator[str]:
    """One Governance-locked bucket per module run, with one-day default retention."""
    admin = s3_admin_client()
    name = unique_bucket_name("locked")
    admin.create_bucket(Bucket=name, ObjectLockEnabledForBucket=True)
    admin.put_object_lock_configuration(
        Bucket=name,
        ObjectLockConfiguration={
            "ObjectLockEnabled": "Enabled",
            "Rule": {"DefaultRetention": {"Mode": "GOVERNANCE", "Days": 1}},
        },
    )
    try:
        yield name
    finally:
        # Governance retention yields to the root user's bypass; if cleanup fails the
        # bucket simply expires with its one-day retention.
        try:
            delete_bucket_with_versions(admin, name, bypass_governance=True)
        except ClientError:
            pass


@pytest.fixture
def archive(tmp_path: Path, locked_bucket: str) -> Archive:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+psycopg://atlas:atlas@127.0.0.1:1/atlas",
            "actor": "local-researcher",
            "archive_root": tmp_path,
            **s3_settings(locked_bucket),
        }
    )
    return open_archive(settings)


def archived(archive: Archive) -> tuple[str, bytes, str]:
    """Archive a unique payload; return its URI, its bytes and its object key."""
    data = f"Form 10-K, fixture {uuid.uuid4()}".encode()
    uri = archive.put(Namespace.RAW, data)
    return uri, data, uri.removeprefix("archive://")


def versions(admin: S3Client, bucket: str, key: str) -> list[str]:
    listing = admin.list_object_versions(Bucket=bucket, Prefix=key)
    return [v.get("VersionId", "") for v in listing.get("Versions", [])]


def version_bytes(admin: S3Client, bucket: str, key: str, version_id: str) -> bytes:
    return admin.get_object(Bucket=bucket, Key=key, VersionId=version_id)["Body"].read()


def test_archived_objects_get_the_bucket_default_governance_retention(
    archive: Archive, s3_admin: S3Client, locked_bucket: str
) -> None:
    _, _, key = archived(archive)

    head = s3_admin.head_object(Bucket=locked_bucket, Key=key)

    assert head.get("ObjectLockMode") == "GOVERNANCE"
    assert "ObjectLockRetainUntilDate" in head


def test_an_overwrite_creates_a_new_version_and_the_original_survives(
    archive: Archive, s3_admin: S3Client, locked_bucket: str
) -> None:
    uri, data, key = archived(archive)
    [original] = versions(s3_admin, locked_bucket, key)

    s3_admin.put_object(Bucket=locked_bucket, Key=key, Body=b"tampered")

    after = versions(s3_admin, locked_bucket, key)
    assert len(after) == 2
    assert original in after
    assert version_bytes(s3_admin, locked_bucket, key, original) == data
    # The archive never serves bytes that don't match their content address.
    with pytest.raises(ArchiveIntegrityError):
        archive.get(uri)


def test_a_plain_delete_adds_a_delete_marker_and_keeps_the_version(
    archive: Archive, s3_admin: S3Client, locked_bucket: str
) -> None:
    uri, data, key = archived(archive)
    [original] = versions(s3_admin, locked_bucket, key)

    response = s3_admin.delete_object(Bucket=locked_bucket, Key=key)

    assert response.get("DeleteMarker") is True
    listing = s3_admin.list_object_versions(Bucket=locked_bucket, Prefix=key)
    assert len(listing.get("DeleteMarkers", [])) == 1
    assert versions(s3_admin, locked_bucket, key) == [original]
    assert version_bytes(s3_admin, locked_bucket, key, original) == data
    assert not archive.exists(uri)


def test_a_permanent_version_delete_is_refused_without_bypass(
    archive: Archive, s3_admin: S3Client, locked_bucket: str
) -> None:
    uri, data, key = archived(archive)
    [original] = versions(s3_admin, locked_bucket, key)

    with pytest.raises(ClientError) as refused:
        s3_admin.delete_object(Bucket=locked_bucket, Key=key, VersionId=original)

    status = refused.value.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
    assert 400 <= status < 500
    assert versions(s3_admin, locked_bucket, key) == [original]
    assert archive.get(uri) == data
