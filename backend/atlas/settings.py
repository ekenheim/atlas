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
    # Pacing (atlas.jobs.pacing): backfill-class jobs run only inside this daily local-time
    # window (HH:MM-HH:MM, may wrap midnight; empty: any time), in backfill_timezone. A quota
    # or outage failure pauses the Hindsight/LiteLLM job kinds for queue_pause_base_seconds,
    # doubling per consecutive pause up to queue_pause_max_seconds (at most 1 h).
    backfill_window: str = "01:00-07:00"
    backfill_timezone: str = "UTC"
    queue_pause_base_seconds: float = Field(default=60.0, gt=0, le=3600)
    queue_pause_max_seconds: float = Field(default=3600.0, gt=0, le=3600)

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
    # The deployed Hindsight version, used only when /version can't be reached (a route that
    # exposes /v1 only); runs then record it as declared rather than observed.
    hindsight_version: str | None = None
    hindsight_bank_id: str = "atlas-ai-infrastructure"
    litellm_url: str | None = None
    litellm_api_key: str | None = None
    # The research bank's versioned template, relative to the working directory (/app in the image).
    hindsight_template_path: Path = Path("configs/hindsight/bank-template.json")
    # LiteLLM aliases Atlas uses, named in config and never hard-coded (spec Part B).
    llm_extract_alias: str = Field(default="atlas-extract", min_length=1)
    llm_reflect_alias: str = Field(default="atlas-reflect", min_length=1)
    # Retention: how long one poll job waits for a retain operation to reach a terminal
    # status (keep it below job_lease_seconds), and how often it asks. A poll that times out
    # fails its attempt and is retried, up to retain_poll_attempts.
    retain_poll_timeout_seconds: float = Field(default=240.0, gt=0)
    retain_poll_interval_seconds: float = Field(default=5.0, gt=0)
    retain_poll_attempts: int = Field(default=5, ge=1)
    # Mental models: the worker enqueues each template model's daily refresh from this UTC
    # time of day on (HH:MM; empty: never scheduled). The template's own refresh_cron runs
    # at 06:00 UTC, so by default Atlas's job finds and records its refresh. A refresh job
    # polls its operation like a retain poll (keep the timeout below job_lease_seconds).
    mental_model_refresh_at: str = Field(default="06:30", pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")
    mental_model_poll_timeout_seconds: float = Field(default=240.0, gt=0)
    mental_model_poll_interval_seconds: float = Field(default=5.0, gt=0)
    # Recorded on every run: the image's commit SHA (a build arg), else the package version.
    code_version: str | None = None
    # The release version (the git tag without the v), stamped into the image by the release
    # workflow and reported by atlas_build_info; else the installed package version.
    version: str | None = None
    # Live SEC EDGAR fetching is opt-in; without it the EDGAR adapter replays fixtures.
    sec_live: bool = False
    # How far back an ingest reaches by default (spec §3: a rolling two to three years). Each
    # ingest is bounded when it is enqueued, so the nightly window rolls forward; every
    # filing in the window is extracted by an LLM, so a wider window costs tokens.
    ingest_lookback_days: int = Field(default=730, ge=1)
    # 8-Ks are selected for bottleneck relevance (docs/decisions.md): only these items are
    # ingested (comma-separated; "*" keeps every 8-K) ...
    sec_8k_items: str = "1.01,1.02,2.01,2.02,2.05,7.01,8.01"
    # ... and an 8-K whose items all fall here is a press release: only its exhibits are kept.
    sec_8k_exhibits_only_items: str = "2.02,7.01,8.01,9.01"

    def eight_k_items(self) -> tuple[str, ...] | None:
        if self.sec_8k_items.strip() == "*":
            return None
        return tuple(i.strip() for i in self.sec_8k_items.split(",") if i.strip())

    def eight_k_exhibits_only_items(self) -> tuple[str, ...]:
        return tuple(i.strip() for i in self.sec_8k_exhibits_only_items.split(",") if i.strip())

    # SEC fair-access policy: a requester name and contact email, e.g. "Atlas Research ops@x.com".
    sec_user_agent: str | None = Field(default=None, validate_default=True)
    # Fixture mode: recorded EDGAR responses, one directory per company slug
    # (e.g. tests/fixtures/edgar/lumentum). Unused when sec_live is on.
    sec_fixtures_dir: Path | None = None
    # Evidence Families: the SimHash Hamming distance within which a parse is a near
    # duplicate. A family keeps the threshold it was founded with (atlas.ledger.families).
    evidence_family_max_hamming_distance: int = Field(default=3, ge=0, le=64)

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

    @model_validator(mode="after")
    def _check_pacing(self) -> Self:
        from atlas.jobs.pacing import BackfillWindow, InvalidWindow, parse_timezone

        try:
            parse_timezone(self.backfill_timezone)
            if self.backfill_window:
                BackfillWindow.parse(self.backfill_window, self.backfill_timezone)
        except InvalidWindow as error:
            raise ValueError(f"ATLAS_BACKFILL_WINDOW / ATLAS_BACKFILL_TIMEZONE: {error}") from None
        if self.queue_pause_base_seconds > self.queue_pause_max_seconds:
            raise ValueError(
                "ATLAS_QUEUE_PAUSE_BASE_SECONDS must not exceed ATLAS_QUEUE_PAUSE_MAX_SECONDS"
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
