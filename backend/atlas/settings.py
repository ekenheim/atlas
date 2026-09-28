"""Runtime configuration, loaded from ATLAS_* environment variables (and .env)."""

from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_", env_file=".env", extra="ignore")

    database_url: str
    actor: str
    archive_root: Path
    frontend_dir: Path | None = None

    # Archive backend: the filesystem (under archive_root, the dev default) or S3.
    # The S3 settings are required only when archive_backend is "s3".
    archive_backend: Literal["filesystem", "s3"] = "filesystem"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_region: str = "us-east-1"

    # Optional providers: when unset, the feature is disabled (logged once at startup).
    hindsight_url: str | None = None
    litellm_url: str | None = None
    litellm_api_key: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        # The repo lives on the Windows filesystem, so env files and exported values can
        # carry CRLF line endings; a stray "\r" must never reach a URL or a path.
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _require_backend_settings(self) -> Self:
        if self.archive_backend == "s3":
            required = {
                "ATLAS_S3_ENDPOINT_URL": self.s3_endpoint_url,
                "ATLAS_S3_BUCKET": self.s3_bucket,
                "ATLAS_S3_ACCESS_KEY_ID": self.s3_access_key_id,
                "ATLAS_S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(
                    f"ATLAS_ARCHIVE_BACKEND=s3 also requires {', '.join(missing)} (not set)"
                )
        return self

    def disabled_providers(self) -> list[tuple[str, str]]:
        """(provider, missing setting) for each optional provider that is not configured."""
        missing: list[tuple[str, str]] = []
        if not self.hindsight_url:
            missing.append(("hindsight", "ATLAS_HINDSIGHT_URL"))
        if not self.litellm_url:
            missing.append(("litellm", "ATLAS_LITELLM_URL"))
        elif not self.litellm_api_key:
            missing.append(("litellm", "ATLAS_LITELLM_API_KEY"))
        return missing
