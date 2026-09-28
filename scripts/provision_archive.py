"""Provision the Atlas archive bucket and its scoped user on MinIO (or Silo).

Creates, idempotently:
  - the bucket (default `atlas-archive`) with object lock enabled at creation, which
    implies versioning, and a default retention in GOVERNANCE mode (default 3650 days)
  - a policy scoped to that bucket that allows the archive's operations (get, put,
    head, list) and explicitly denies `s3:BypassGovernanceRetention`
  - the application user (default `atlas`) with that policy attached

The user's credentials are generated here and printed once, to stdout, for the owner
to store in Bitwarden; they are never written to disk and can't be shown again (use
`--rotate-secret` to issue new ones). A second run changes nothing and says so. It
refuses, rather than changes, an existing bucket whose lock differs from the request.

Root credentials come from the environment (MINIO_ROOT_USER, MINIO_ROOT_PASSWORD), never
from arguments. Run it from a repo checkout (the `minio` package is a dev dependency,
not part of the app image):

    read -rs MINIO_ROOT_PASSWORD; export MINIO_ROOT_USER=... MINIO_ROOT_PASSWORD
    uv run scripts/provision_archive.py --endpoint https://s3.example.com

See docs/runbooks.md, "Archive bucket provisioning".
"""

import argparse
import json
import os
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import SplitResult, urlsplit

from minio import Minio, MinioAdmin
from minio.commonconfig import ENABLED, GOVERNANCE
from minio.credentials.providers import StaticProvider
from minio.error import MinioAdminException, S3Error
from minio.objectlockconfig import DAYS, ObjectLockConfig
from urllib3.exceptions import HTTPError

ROOT_ENV = ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD")
NO_LOCK = "ObjectLockConfigurationNotFoundError"
NO_SUCH_POLICY = "XMinioAdminNoSuchPolicy"
NO_SUCH_USER = "XMinioAdminNoSuchUser"


class Refused(Exception):
    """The existing state conflicts with the request; nothing further is changed."""


def archive_policy(bucket: str) -> dict[str, Any]:
    """What the archive does (put, get, head, readiness, listing) and nothing more."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                "Resource": [f"arn:aws:s3:::{bucket}"],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            },
            {
                # Explicit, so that no other policy attached later can grant it.
                "Effect": "Deny",
                "Action": ["s3:BypassGovernanceRetention"],
                "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
            },
        ],
    }


def admin_error_code(error: MinioAdminException) -> str:
    """The admin API's error code, e.g. XMinioAdminNoSuchUser (minio-py keeps it private)."""
    body = error._body  # pyright: ignore[reportPrivateUsage]
    try:
        return str(json.loads(body).get("Code", ""))
    except (ValueError, AttributeError):
        return ""


def days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def normalized(policy: dict[str, Any]) -> list[str]:
    """A policy's statements in a canonical form; the server reorders lists."""

    def canonical(statement: dict[str, Any]) -> str:
        return json.dumps(
            {
                k: sorted(cast(list[str], v)) if isinstance(v, list) else v
                for k, v in statement.items()
            },
            sort_keys=True,
        )

    return sorted(canonical(s) for s in policy.get("Statement", []))


class Provisioner:
    def __init__(self, s3: Minio, admin: MinioAdmin, say: Callable[[str], None]) -> None:
        self._s3 = s3
        self._admin = admin
        self._say = say
        self.changes = 0

    def _changed(self, message: str) -> None:
        self.changes += 1
        self._say(message)

    def bucket(self, bucket: str, retention_days: int) -> None:
        wanted = ObjectLockConfig(GOVERNANCE, retention_days, DAYS)
        if not self._s3.bucket_exists(bucket):
            self._s3.make_bucket(bucket, object_lock=True)
            self._changed(f"bucket {bucket}: created with object lock (versioning implied)")
        try:
            current = self._s3.get_object_lock_config(bucket)
        except S3Error as error:
            if error.code == NO_LOCK:
                raise Refused(
                    f"bucket {bucket} exists without object lock, which can only be enabled"
                    " when a bucket is created; choose another name"
                ) from None
            raise
        if current.mode is None:
            self._s3.set_object_lock_config(bucket, wanted)
            self._changed(
                f"bucket {bucket}: default retention set to {GOVERNANCE} {days(retention_days)}"
            )
        elif (current.mode, current.duration, current.duration_unit) != (
            wanted.mode,
            wanted.duration,
            wanted.duration_unit,
        ):
            raise Refused(
                f"bucket {bucket} has default retention {current.mode} {current.duration}"
                f" {current.duration_unit}, not {GOVERNANCE} {days(retention_days)}; this"
                " script never changes an existing lock (change it by hand if intended)"
            )
        else:
            self._say(f"bucket {bucket}: object lock {GOVERNANCE} {days(retention_days)} (ok)")
        versioning = self._s3.get_bucket_versioning(bucket).status
        if versioning != ENABLED:
            raise Refused(f"bucket {bucket} is object-locked but versioning is {versioning}")

    def policy(self, name: str, bucket: str) -> None:
        wanted = archive_policy(bucket)
        try:
            current = json.loads(self._admin.policy_info(name))
        except MinioAdminException as error:
            if admin_error_code(error) != NO_SUCH_POLICY:
                raise
            self._admin.policy_add(name, policy=wanted)  # pyright: ignore[reportUnknownMemberType]
            self._changed(f"policy {name}: created (scoped to {bucket}, no governance bypass)")
            return
        if normalized(current) == normalized(wanted):
            self._say(f"policy {name}: up to date")
        else:
            self._admin.policy_add(name, policy=wanted)  # pyright: ignore[reportUnknownMemberType]
            self._changed(f"policy {name}: updated to the archive policy for {bucket}")

    def user(self, user: str, *, rotate_secret: bool) -> str | None:
        """Ensure the user exists; return its new secret if one was issued."""
        try:
            json.loads(self._admin.user_info(user))
        except MinioAdminException as error:
            if admin_error_code(error) != NO_SUCH_USER:
                raise
            secret = new_secret()
            self._admin.user_add(user, secret)
            self._changed(f"user {user}: created")
            return secret
        if rotate_secret:
            secret = new_secret()
            self._admin.user_add(user, secret)  # replaces the secret of an existing user
            self._changed(f"user {user}: secret rotated")
            return secret
        self._say(f"user {user}: exists (credentials are not shown again; see --rotate-secret)")
        return None

    def attachment(self, user: str, policy: str) -> None:
        info = json.loads(self._admin.user_info(user))
        attached = [p for p in str(info.get("policyName", "")).split(",") if p]
        if policy in attached:
            self._say(f"user {user}: policy {policy} attached")
        else:
            self._admin.attach_policy([policy], user=user)
            self._changed(f"user {user}: policy {policy} attached")
        others = [p for p in attached if p != policy]
        if others:
            self._say(f"user {user}: WARNING also has {', '.join(others)}; check what they grant")


def new_secret() -> str:
    return secrets.token_urlsafe(30)  # 40 characters, MinIO's maximum secret length


@dataclass(frozen=True)
class Options:
    endpoint: SplitResult
    bucket: str
    user: str
    policy: str
    retention_days: int
    rotate_secret: bool


def parse_args(argv: list[str] | None) -> Options:
    parser = argparse.ArgumentParser(
        description="Provision the object-locked Atlas archive bucket and its scoped user.",
        epilog="Root credentials are read from MINIO_ROOT_USER and MINIO_ROOT_PASSWORD.",
    )
    parser.add_argument("--endpoint", required=True, help="S3 API URL, e.g. https://s3.<domain>")
    parser.add_argument("--bucket", default="atlas-archive")
    parser.add_argument("--user", default="atlas", help="the application user (access key)")
    parser.add_argument("--policy", help="policy name (default: <bucket>-app)")
    parser.add_argument(
        "--retention-days", type=int, default=3650, help="default GOVERNANCE retention"
    )
    parser.add_argument(
        "--rotate-secret", action="store_true", help="issue a new secret for an existing user"
    )
    args = parser.parse_args(argv)
    endpoint = urlsplit(str(args.endpoint))
    if endpoint.scheme not in ("http", "https") or not endpoint.netloc or endpoint.path.strip("/"):
        parser.error("--endpoint must be a URL like https://s3.example.com")
    retention_days = int(args.retention_days)
    if retention_days < 1:
        parser.error("--retention-days must be at least 1")
    bucket = str(args.bucket)
    return Options(
        endpoint=endpoint,
        bucket=bucket,
        user=str(args.user),
        policy=str(args.policy or f"{bucket}-app"),
        retention_days=retention_days,
        rotate_secret=bool(args.rotate_secret),
    )


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    missing = [name for name in ROOT_ENV if not os.environ.get(name)]
    if missing:
        print(f"error: set the root credentials in {' and '.join(missing)}", file=sys.stderr)
        return 2
    root_user, root_password = (os.environ[name] for name in ROOT_ENV)
    host, secure = options.endpoint.netloc, options.endpoint.scheme == "https"
    s3 = Minio(host, access_key=root_user, secret_key=root_password, secure=secure)
    admin = MinioAdmin(
        endpoint=host, credentials=StaticProvider(root_user, root_password), secure=secure
    )

    provisioner = Provisioner(s3, admin, lambda message: print(message, flush=True))
    try:
        provisioner.bucket(options.bucket, options.retention_days)
        provisioner.policy(options.policy, options.bucket)
        secret = provisioner.user(options.user, rotate_secret=options.rotate_secret)
        if secret is not None:
            # Printed as soon as it exists, so that a later failure can't lose it.
            print(
                "\nStore these in the Bitwarden item `atlas` now; they are not shown again"
                " and are not saved anywhere:\n"
                f"  S3_ENDPOINT_URL={options.endpoint.geturl()}\n"
                f"  S3_BUCKET={options.bucket}\n"
                f"  S3_ACCESS_KEY_ID={options.user}\n"
                f"  S3_SECRET_ACCESS_KEY={secret}\n",
                flush=True,
            )
        provisioner.attachment(options.user, options.policy)
    except Refused as refusal:
        print(f"error: {refusal}", file=sys.stderr)
        return 1
    except (S3Error, MinioAdminException, HTTPError, ValueError) as error:
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    if provisioner.changes:
        print(f"Done: {provisioner.changes} change(s).")
    else:
        print("No changes: already provisioned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
