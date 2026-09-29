"""The archive provisioning script, run against the Compose S3 server (Silo) as root.

Each module run provisions its own bucket, user and policy with a one-day retention.
The user and policy are removed afterwards; the locked bucket is emptied with the root
user's Governance bypass where possible, and otherwise expires with its retention.
"""

import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from minio import MinioAdmin
from minio.credentials.providers import StaticProvider
from minio.error import MinioAdminException
from mypy_boto3_s3 import S3Client

from atlas.archive import Namespace, open_archive
from atlas.settings import Settings
from tests.harness import make_settings
from tests.integration.conftest import (
    S3_ACCESS_KEY_ID,
    S3_ENDPOINT_URL,
    S3_SECRET_ACCESS_KEY,
    delete_bucket_with_versions,
    s3_admin_client,
    unique_bucket_name,
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "provision_archive.py"
ROOT_ENV = {"MINIO_ROOT_USER": S3_ACCESS_KEY_ID, "MINIO_ROOT_PASSWORD": S3_SECRET_ACCESS_KEY}


def provision(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--endpoint", S3_ENDPOINT_URL, *args],
        env={"PATH": os.environ["PATH"], **(ROOT_ENV if env is None else env)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def printed(name: str, output: str) -> str:
    match = re.search(rf"^\s*{name}=(\S+)$", output, re.MULTILINE)
    assert match is not None, f"{name} not printed"
    return match[1]


@dataclass(frozen=True)
class Provisioned:
    bucket: str
    user: str
    policy: str
    access_key_id: str
    secret_access_key: str
    first_run: subprocess.CompletedProcess[str]

    def args(self) -> list[str]:
        return ["--bucket", self.bucket, "--user", self.user, "--policy", self.policy]


def admin() -> MinioAdmin:
    endpoint = S3_ENDPOINT_URL.removeprefix("http://")
    credentials = StaticProvider(S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY)
    return MinioAdmin(endpoint=endpoint, credentials=credentials, secure=False)


@pytest.fixture(scope="module")
def provisioned() -> Iterator[Provisioned]:
    suffix = uuid.uuid4().hex[:12]
    bucket = unique_bucket_name("provisioned")
    user, policy = f"atlas-test-{suffix}", f"atlas-test-{suffix}-archive"
    run = provision("--bucket", bucket, "--user", user, "--policy", policy, "--retention-days", "1")
    try:
        assert run.returncode == 0, run.stdout + run.stderr
        yield Provisioned(
            bucket=bucket,
            user=user,
            policy=policy,
            access_key_id=printed("S3_ACCESS_KEY_ID", run.stdout),
            secret_access_key=printed("S3_SECRET_ACCESS_KEY", run.stdout),
            first_run=run,
        )
    finally:
        remove(bucket, user, policy)


def remove(bucket: str, user: str, policy: str) -> None:
    """Remove the test user and policy, and the bucket if its lock allows it."""
    root = admin()
    for cleanup in (
        lambda: root.detach_policy([policy], user=user),
        lambda: root.user_remove(user),
        lambda: root.policy_remove(policy),
    ):
        try:
            cleanup()
        except MinioAdminException:
            pass
    try:
        delete_bucket_with_versions(s3_admin_client(), bucket, bypass_governance=True)
    except ClientError:
        pass  # the one-day retention expires it


def scoped_client(p: Provisioned) -> S3Client:
    # Only the S3 overload of boto3.client is typed (boto3-stubs[s3]); the rest are Unknown.
    return boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=p.access_key_id,
        aws_secret_access_key=p.secret_access_key,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 1}),
    )


def scoped_archive_settings(p: Provisioned, tmp_path: Path) -> Settings:
    return make_settings(
        tmp_path,
        archive_backend="s3",
        s3_endpoint_url=S3_ENDPOINT_URL,
        s3_bucket=p.bucket,
        s3_access_key_id=p.access_key_id,
        s3_secret_access_key=p.secret_access_key,
    )


def test_the_bucket_is_object_locked_with_the_configured_governance_retention(
    provisioned: Provisioned, s3_admin: S3Client
) -> None:
    lock = s3_admin.get_object_lock_configuration(Bucket=provisioned.bucket)[
        "ObjectLockConfiguration"
    ]

    assert lock.get("ObjectLockEnabled") == "Enabled"
    assert lock.get("Rule", {}).get("DefaultRetention") == {"Mode": "GOVERNANCE", "Days": 1}
    versioning = s3_admin.get_bucket_versioning(Bucket=provisioned.bucket)
    assert versioning.get("Status") == "Enabled"


def test_the_printed_credentials_belong_to_the_scoped_user(provisioned: Provisioned) -> None:
    assert provisioned.access_key_id == provisioned.user
    assert len(provisioned.secret_access_key) >= 32
    assert printed("S3_BUCKET", provisioned.first_run.stdout) == provisioned.bucket


def test_the_scoped_user_can_put_and_get_through_the_archive(
    provisioned: Provisioned, tmp_path: Path, s3_admin: S3Client
) -> None:
    archive = open_archive(scoped_archive_settings(provisioned, tmp_path))
    data = f"Form 10-K, fixture {uuid.uuid4()}".encode()

    uri = archive.put(Namespace.RAW, data)

    assert archive.is_ready()
    assert archive.exists(uri)
    assert archive.get(uri) == data
    assert archive.put(Namespace.RAW, data) == uri
    head = s3_admin.head_object(Bucket=provisioned.bucket, Key=uri.removeprefix("archive://"))
    assert head.get("ObjectLockMode") == "GOVERNANCE"


def test_the_scoped_user_cannot_permanently_delete_a_locked_version_even_with_bypass(
    provisioned: Provisioned, tmp_path: Path, s3_admin: S3Client
) -> None:
    archive = open_archive(scoped_archive_settings(provisioned, tmp_path))
    data = f"Form 8-K, fixture {uuid.uuid4()}".encode()
    uri = archive.put(Namespace.RAW, data)
    key = uri.removeprefix("archive://")
    [version] = [
        v.get("VersionId", "")
        for v in s3_admin.list_object_versions(Bucket=provisioned.bucket, Prefix=key).get(
            "Versions", []
        )
    ]

    with pytest.raises(ClientError):
        scoped_client(provisioned).delete_object(
            Bucket=provisioned.bucket, Key=key, VersionId=version, BypassGovernanceRetention=True
        )

    after = s3_admin.list_object_versions(Bucket=provisioned.bucket, Prefix=key)
    assert [v.get("VersionId") for v in after.get("Versions", [])] == [version]
    assert archive.get(uri) == data


def test_the_scoped_user_cannot_touch_other_buckets(
    provisioned: Provisioned, s3_admin: S3Client, s3_bucket: str
) -> None:
    with pytest.raises(ClientError):
        scoped_client(provisioned).put_object(Bucket=s3_bucket, Key="x", Body=b"x")


def test_a_second_run_changes_nothing_and_says_so(provisioned: Provisioned) -> None:
    again = provision(*provisioned.args(), "--retention-days", "1")

    assert again.returncode == 0, again.stdout + again.stderr
    assert "No changes" in again.stdout
    assert provisioned.secret_access_key not in again.stdout + again.stderr
    assert "S3_SECRET_ACCESS_KEY" not in again.stdout
    # The first run's credentials still work: the secret was not rotated.
    scoped_client(provisioned).head_bucket(Bucket=provisioned.bucket)


def test_a_run_that_would_change_the_retention_of_an_existing_bucket_is_refused(
    provisioned: Provisioned, s3_admin: S3Client
) -> None:
    refused = provision(*provisioned.args(), "--retention-days", "2")

    assert refused.returncode == 1
    assert "retention" in refused.stderr
    lock = s3_admin.get_object_lock_configuration(Bucket=provisioned.bucket)
    assert lock["ObjectLockConfiguration"].get("Rule", {}).get("DefaultRetention") == {
        "Mode": "GOVERNANCE",
        "Days": 1,
    }


def test_an_existing_bucket_without_object_lock_is_refused(s3_bucket: str) -> None:
    suffix = uuid.uuid4().hex[:12]
    user, policy = f"atlas-test-{suffix}", f"atlas-test-{suffix}-archive"

    refused = provision("--bucket", s3_bucket, "--user", user, "--policy", policy)

    assert refused.returncode == 1
    assert "object lock" in refused.stderr
    assert "S3_SECRET_ACCESS_KEY" not in refused.stdout
    with pytest.raises(MinioAdminException):
        admin().user_info(user)  # nothing was created


def test_rotating_the_secret_issues_new_credentials_and_revokes_the_old() -> None:
    suffix = uuid.uuid4().hex[:12]
    bucket = unique_bucket_name("rotated")
    user, policy = f"atlas-test-{suffix}", f"atlas-test-{suffix}-archive"
    args = ["--bucket", bucket, "--user", user, "--policy", policy, "--retention-days", "1"]
    try:
        first = provision(*args)
        assert first.returncode == 0, first.stdout + first.stderr
        old_secret = printed("S3_SECRET_ACCESS_KEY", first.stdout)

        rotated = provision(*args, "--rotate-secret")

        assert rotated.returncode == 0, rotated.stdout + rotated.stderr
        new_secret = printed("S3_SECRET_ACCESS_KEY", rotated.stdout)
        assert new_secret != old_secret
        new = Provisioned(bucket, user, policy, user, new_secret, rotated)
        old = Provisioned(bucket, user, policy, user, old_secret, first)
        scoped_client(new).head_bucket(Bucket=bucket)
        with pytest.raises(ClientError):
            scoped_client(old).head_bucket(Bucket=bucket)
    finally:
        remove(bucket, user, policy)


def test_missing_root_credentials_fail_fast() -> None:
    result = provision("--bucket", unique_bucket_name("unused"), env={})

    assert result.returncode == 2
    assert "MINIO_ROOT_USER" in result.stderr
    assert "MINIO_ROOT_PASSWORD" in result.stderr
    assert "Traceback" not in result.stderr
