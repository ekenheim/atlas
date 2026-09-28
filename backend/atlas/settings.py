"""Runtime configuration, loaded from ATLAS_* environment variables (and .env)."""

import re
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_", env_file=".env", extra="ignore")

    database_url: str
    actor: str = Field(min_length=1)  # recorded on every audit event
    archive_root: Path
    frontend_dir: Path | None = None

    # Job queue: how often an idle continuous worker polls, and how long a claim is held
    # before another worker may reclaim it (a crashed worker's job is retried after this).
    worker_poll_seconds: float = Field(default=5.0, gt=0)
    job_lease_seconds: float = Field(default=300.0, gt=0)

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
    hindsight_api_key: str | None = None  # bearer token; the local spike runs without one
    hindsight_bank_id: str = "atlas-ai-infrastructure"
    litellm_url: str | None = None
    litellm_api_key: str | None = None
    # The research bank's versioned template, relative to the working directory (/app in the image).
    hindsight_template_path: Path = Path("configs/hindsight/bank-template.json")
    # LiteLLM aliases Atlas uses, named in config and never hard-coded (spec Part B).
    llm_extract_alias: str = Field(default="atlas-extract", min_length=1)
    llm_reflect_alias: str = Field(default="atlas-reflect", min_length=1)
    # Recorded on every run: the image's commit SHA (a build arg), else the package version.
    code_version: str | None = None
    # Live SEC EDGAR fetching is opt-in; without it the EDGAR adapter replays fixtures.
    sec_live: bool = False
    # SEC fair-access policy: a requester name and contact email, e.g. "Atlas Research ops@x.com".
    sec_user_agent: str | None = Field(default=None, validate_default=True)
    # Fixture mode: recorded EDGAR responses, one directory per company slug
    # (e.g. tests/fixtures/edgar/lumentum). Unused when sec_live is on.
    sec_fixtures_dir: Path | None = None

    # The versioned company universe and themes (company membership is config, not code).
    themes_config: Path = Path("configs/themes/ai-infrastructure.yaml")

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

    @field_validator("sec_user_agent")
    @classmethod
    def _sec_user_agent_when_live(cls, value: str | None, info: ValidationInfo) -> str | None:
        if info.data.get("sec_live") and not value:
            raise ValueError("required when ATLAS_SEC_LIVE is true (SEC fair-access policy)")
        if value and not re.search(r"\S+@\S+\.\S+", value):
            raise ValueError("must include a contact email, e.g. 'Atlas Research ops@example.com'")
        return value or None

    def llm_aliases(self) -> list[str]:
        """The LiteLLM aliases whose routed deployments each run records."""
        return list(dict.fromkeys([self.llm_extract_alias, self.llm_reflect_alias]))

    def disabled_providers(self) -> list[tuple[str, str]]:
        """(provider, missing setting) for each optional provider that is not configured."""
        missing: list[tuple[str, str]] = []
        if not self.hindsight_url:
            missing.append(("hindsight", "ATLAS_HINDSIGHT_URL"))
        if not self.litellm_url:
            missing.append(("litellm", "ATLAS_LITELLM_URL"))
        elif not self.litellm_api_key:
            missing.append(("litellm", "ATLAS_LITELLM_API_KEY"))
        if not self.sec_live:
            missing.append(("sec", "ATLAS_SEC_LIVE"))
        return missing
