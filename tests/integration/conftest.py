"""Integration tests run against the Compose services; network is limited to localhost."""

import os
import uuid
from collections.abc import Iterator

import boto3
import pytest
from botocore.config import Config
from mypy_boto3_s3 import S3Client
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

LOCAL_HOSTS = ["127.0.0.1", "localhost", "::1"]
ADMIN_DATABASE_URL = os.environ.get(
    "ATLAS_TEST_DATABASE_URL", "postgresql+psycopg://atlas:atlas@127.0.0.1:55432/atlas"
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration/" in item.nodeid:
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.enable_socket)
            item.add_marker(pytest.mark.allow_hosts(LOCAL_HOSTS))


@pytest.fixture
def empty_database_url() -> Iterator[str]:
    """A freshly created, empty database, dropped after the test."""
    name = f"atlas_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(ADMIN_DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


# --- S3: the Compose Silo server ---

S3_ENDPOINT_URL = os.environ.get("ATLAS_TEST_S3_ENDPOINT_URL", "http://127.0.0.1:59000")
# The Compose dev server's root credentials (compose.yaml); not a real secret.
S3_ACCESS_KEY_ID = os.environ.get("ATLAS_TEST_S3_ACCESS_KEY_ID", "atlas-dev")
S3_SECRET_ACCESS_KEY = os.environ.get("ATLAS_TEST_S3_SECRET_ACCESS_KEY", "atlas-dev-secret")


def s3_settings(bucket: str) -> dict[str, object]:
    """Settings values that point the archive at the Compose S3 server."""
    return {
        "archive_backend": "s3",
        "s3_endpoint_url": S3_ENDPOINT_URL,
        "s3_bucket": bucket,
        "s3_access_key_id": S3_ACCESS_KEY_ID,
        "s3_secret_access_key": S3_SECRET_ACCESS_KEY,
    }


def unique_bucket_name(purpose: str) -> str:
    return f"atlas-test-{purpose}-{uuid.uuid4().hex[:12]}"


def s3_admin_client() -> S3Client:
    """A root client for the Compose S3 server, used to arrange and observe buckets."""
    # Only the S3 overload of boto3.client is typed (boto3-stubs[s3]); the rest are Unknown.
    return boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 1}),
    )


@pytest.fixture
def s3_admin() -> S3Client:
    return s3_admin_client()


def delete_bucket_with_versions(
    client: S3Client, bucket: str, *, bypass_governance: bool = False
) -> None:
    for page in client.get_paginator("list_object_versions").paginate(Bucket=bucket):
        for entry in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]:
            client.delete_object(
                Bucket=bucket,
                Key=entry.get("Key", ""),
                VersionId=entry.get("VersionId", ""),
                BypassGovernanceRetention=bypass_governance,
            )
    client.delete_bucket(Bucket=bucket)


@pytest.fixture
def s3_bucket(s3_admin: S3Client) -> Iterator[str]:
    """A fresh versioned (not locked) bucket, removed after the test."""
    name = unique_bucket_name("archive")
    s3_admin.create_bucket(Bucket=name)
    s3_admin.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
    try:
        yield name
    finally:
        delete_bucket_with_versions(s3_admin, name)
