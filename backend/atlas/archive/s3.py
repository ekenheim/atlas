"""S3 backend: one object per key in a versioned, object-locked bucket.

Immutability in deployment comes from the bucket (Governance-mode object lock with a
default retention, and an application user without bypass rights). This backend adds
write-once puts (`If-None-Match: *`) and server-verified SHA-256 checksums.
"""

import base64
from typing import TYPE_CHECKING, Self

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from atlas.archive import ArchiveError, ObjectNotFound
from atlas.settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client  # type stubs only (dev dependency)

_NOT_FOUND = {"404", "NoSuchKey", "NotFound"}
_ALREADY_EXISTS = {"412", "PreconditionFailed"}


def _code(error: ClientError) -> str:
    return error.response.get("Error", {}).get("Code", "")


class S3Store:
    def __init__(self, client: "S3Client", bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        assert settings.s3_secret_access_key is not None  # guaranteed by Settings
        # Only the S3 overload of boto3.client is typed (boto3-stubs[s3]); the rest are Unknown.
        client: S3Client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            region_name=settings.s3_region,
            config=Config(
                s3={"addressing_style": "path"},
                connect_timeout=3,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        assert settings.s3_bucket is not None  # guaranteed by Settings
        return cls(client, settings.s3_bucket)

    def __repr__(self) -> str:
        return "S3Store()"

    def contains(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if _code(error) in _NOT_FOUND:
                return False
            raise ArchiveError(f"archive lookup failed ({_code(error)})") from None
        except BotoCoreError:
            raise ArchiveError("archive is unreachable") from None
        return True

    def read(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if _code(error) in _NOT_FOUND:
                raise ObjectNotFound(key) from None
            raise ArchiveError(f"archive read failed ({_code(error)})") from None
        except BotoCoreError:
            raise ArchiveError("archive is unreachable") from None
        return response["Body"].read()

    def create(self, key: str, data: bytes, sha256: str) -> None:
        checksum = base64.b64encode(bytes.fromhex(sha256)).decode()
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ChecksumSHA256=checksum,
                IfNoneMatch="*",  # never replace an existing object, even in a race
            )
        except ClientError as error:
            if _code(error) in _ALREADY_EXISTS:
                return
            raise ArchiveError(f"archive write failed ({_code(error)})") from None
        except BotoCoreError:
            raise ArchiveError("archive is unreachable") from None

    def is_ready(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except (ClientError, BotoCoreError):
            return False
        return True
