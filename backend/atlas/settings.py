"""Runtime configuration, loaded from ATLAS_* environment variables (and .env)."""

import re
from pathlib import Path

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_", env_file=".env", extra="ignore")

    database_url: str
    actor: str
    archive_root: Path
    frontend_dir: Path | None = None

    # Optional providers: when unset, the feature is disabled (logged once at startup).
    hindsight_url: str | None = None
    litellm_url: str | None = None
    litellm_api_key: str | None = None
    # Live SEC EDGAR fetching is opt-in; without it the EDGAR adapter replays fixtures.
    sec_live: bool = False
    # SEC fair-access policy: a requester name and contact email, e.g. "Atlas Research ops@x.com".
    sec_user_agent: str | None = Field(default=None, validate_default=True)

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        # The repo lives on the Windows filesystem, so env files and exported values can
        # carry CRLF line endings; a stray "\r" must never reach a URL or a path.
        return value.strip() if isinstance(value, str) else value

    @field_validator("sec_user_agent")
    @classmethod
    def _sec_user_agent_when_live(cls, value: str | None, info: ValidationInfo) -> str | None:
        if info.data.get("sec_live") and not value:
            raise ValueError("required when ATLAS_SEC_LIVE is true (SEC fair-access policy)")
        if value and not re.search(r"\S+@\S+\.\S+", value):
            raise ValueError("must include a contact email, e.g. 'Atlas Research ops@example.com'")
        return value or None

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
