"""Runtime configuration, loaded from ATLAS_* environment variables (and .env)."""

import re
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, JsonValue, SecretStr, ValidationInfo, field_validator, model_validator
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
    # Pacing (atlas.jobs.pacing): backfill-class jobs run only inside this local-time window,
    # one or more daily ranges (HH:MM-HH:MM, comma-separated, may wrap midnight; empty, the
    # default: any time), in backfill_timezone. A quota or outage failure pauses the
    # Hindsight/LiteLLM job kinds for queue_pause_base_seconds, doubling per consecutive
    # pause up to queue_pause_max_seconds (at most 1 h).
    backfill_window: str = ""
    backfill_timezone: str = "UTC"
    queue_pause_base_seconds: float = Field(default=60.0, gt=0, le=3600)
    queue_pause_max_seconds: float = Field(default=3600.0, gt=0, le=3600)
    # Budgets (atlas.jobs.budget), whether or not a window is set: per rolling window of
    # budget_window_hours, the Hindsight (Codex) kinds may submit codex_budget_operations
    # retain/reprocess operations and the role (MiniMax) kinds may spend
    # minimax_budget_tokens recorded LLM tokens. Backfill jobs stop short of the last
    # budget_interactive_reserve share of each budget, which is kept for interactive work.
    budget_window_hours: float = Field(default=5.0, gt=0, le=24)
    codex_budget_operations: int = Field(default=40, ge=1)
    minimax_budget_tokens: int = Field(default=400_000, ge=1)
    budget_interactive_reserve: float = Field(default=0.3, ge=0, lt=1)

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
    # Research roles (atlas.roles): the model their chat completions ask LiteLLM for, the
    # extra body fields merged into each request (MiniMax-M3 with thinking off, as for
    # Hindsight; a JSON object in the env), the HTTP timeout, and each run's token ceiling
    # (input + output, spec §7.4), backstopped by the `atlas` key's maxBudget.
    llm_role_model: str = Field(default="MiniMax-M3", min_length=1)
    llm_role_extra_body: dict[str, JsonValue] = Field(
        default_factory=lambda: {"thinking": {"type": "disabled"}}
    )
    llm_role_timeout_seconds: float = Field(default=180.0, gt=0)
    run_token_budget: int = Field(default=200_000, gt=0)
    # The Investigator (atlas.claims): at most this many passages per extraction, sent this
    # many to a call.
    investigator_max_passages: int = Field(default=24, gt=0)
    investigator_passages_per_call: int = Field(default=6, gt=0)
    # The Reviewer (atlas.relationships): Assertions reviewed per call.
    reviewer_assertions_per_call: int = Field(default=5, gt=0, le=25)

    # Discovery (atlas.discovery): SearXNG's base URL (optional; without it the `discover`
    # job fails), the engines every search names (comma-separated; the instance's defaults
    # are partly broken, so they're always named), its HTTP timeout, and how many queries
    # the Scout may have searched per discovery (at most 10, spec §7.4).
    searxng_url: str | None = None
    searxng_engines: str = Field(default="bing,brave", pattern=r"^\s*[\w-]+(\s*,\s*[\w-]+)*\s*$")
    searxng_timeout_seconds: float = Field(default=30.0, gt=0)
    # The language every search asks for (SearXNG's `language`), so results never follow
    # the instance's locale: an ISO 639-1 code, optionally with a region ("en", "en-US").
    searxng_language: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    # How an investigation ranks a discovery's leads (atlas.discovery.ranking).
    lead_ranking_config: Path = Path("configs/discovery/lead-ranking.yaml")
    discovery_max_queries: int = Field(default=10, ge=1, le=10)
    # Investigations (atlas.investigations): the default per-run lead and document budgets
    # (spec §7.4: at most 10 new leads and 25 fetched documents); a request may lower them.
    # The token ceiling is run_token_budget.
    investigation_max_leads: int = Field(default=10, ge=1, le=10)
    investigation_max_documents: int = Field(default=25, ge=1, le=25)
    # Retention: how long one poll job waits for a retain operation to reach a terminal
    # status (keep it below job_lease_seconds), and how often it asks. A poll that times out
    # fails its attempt and is retried, up to retain_poll_attempts.
    retain_poll_timeout_seconds: float = Field(default=240.0, gt=0)
    retain_poll_interval_seconds: float = Field(default=5.0, gt=0)
    retain_poll_attempts: int = Field(default=5, ge=1)
    # Retention triage (atlas.retention.triage): `on` reads each new Source Version section
    # by section (deterministic rules, then the Triage role through LiteLLM) and retains only
    # the sections worth retaining; `off` retains every section; `auto` (the default) is `on`
    # when LiteLLM is configured. The role reads each section in windows of
    # triage_excerpt_chars characters, at most triage_windows_per_section of them (spread
    # over the section when it has more, the first always included), triage_sections_per_call
    # windows to a call; a section is retained when any window is. Ten windows of 1,500 with
    # a 200 overlap read a section of up to ~13,300 characters in full (raised from six after
    # the first live audit missed a footnote in a 10-window chunk).
    retention_triage: Literal["auto", "on", "off"] = "auto"
    triage_excerpt_chars: int = Field(default=1500, ge=200, le=20_000)
    triage_windows_per_section: int = Field(default=10, ge=1, le=50)
    triage_sections_per_call: int = Field(default=15, ge=1, le=50)
    # Consecutive windows overlap by this many characters, so a sentence at a window's
    # boundary is read whole in the next one (less than triage_excerpt_chars).
    triage_window_overlap_chars: int = Field(default=200, ge=0, le=10_000)
    # The triage audit (`atlas triage audit`, ticket 33): the full-section judge reads a
    # skipped section whole, in chunks of at most this many characters only when it is
    # longer (overlapping like the windows), and one `triage_audit` attempt judges at most
    # this many samples before it is requeued (so it stays inside a job lease and is paced by
    # the minimax budget between attempts).
    triage_judge_max_chars: int = Field(default=60_000, ge=2_000, le=1_000_000)
    triage_audit_samples_per_attempt: int = Field(default=3, ge=1, le=100)
    # Mental models: the worker enqueues each template model's daily refresh from this UTC
    # time of day on (HH:MM; empty: never scheduled). The template's own refresh_cron runs
    # at 06:00 UTC, so by default Atlas's job finds and records its refresh. A refresh job
    # polls its operation like a retain poll (keep the timeout below job_lease_seconds).
    mental_model_refresh_at: str = Field(default="06:30", pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")
    mental_model_poll_timeout_seconds: float = Field(default=240.0, gt=0)
    mental_model_poll_interval_seconds: float = Field(default=5.0, gt=0)
    # Replay banks (atlas.replay, §9.2): the **local** Hindsight a replay creates its
    # `atlas-replay-<id>` bank on (never the shared server; without it replays are refused),
    # the fixed question sets, how many Source Versions one replay retains at most (the
    # latest eligible ones; each is a Codex-spending retain), and how long it waits for
    # consolidation in one attempt (keep it below job_lease_seconds). Its retains wait like
    # retain polls (retain_poll_timeout_seconds, at most retain_poll_attempts times).
    replay_hindsight_url: str | None = None
    replay_hindsight_api_key: str | None = None
    replay_question_sets_config: Path = Path("configs/replay/question-sets.yaml")
    replay_max_source_versions: int = Field(default=3, ge=1, le=25)
    replay_consolidation_timeout_seconds: float = Field(default=240.0, gt=0)
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
    # Entity resolution (atlas.identity, `atlas companies resolve`): the sources' base URLs.
    # SEC's ticker file and submissions use sec_user_agent and the shared SEC rate limit.
    sec_files_url: str = "https://www.sec.gov/files"
    sec_data_url: str = "https://data.sec.gov"
    gleif_url: str = "https://api.gleif.org/api/v1"
    openfigi_url: str = "https://api.openfigi.com"
    # Fixture mode: recorded EDGAR responses, one directory per company slug
    # (e.g. tests/fixtures/edgar/lumentum). Unused when sec_live is on.
    sec_fixtures_dir: Path | None = None
    # Exchange adapters (HKEXnews, ...): live fetching is opt-in; without it they replay the
    # recorded (or hand-written) responses in `exchange_fixtures_dir/<company slug>`. Every
    # request, live or replayed, passes the fetch gate (the site register and robots.txt).
    exchange_live: bool = False
    # Non-SEC sources get a generic User-Agent without personal data (owner decision
    # 2026-09-29); SEC's contact-email rule is SEC's alone.
    exchange_user_agent: str = "AtlasResearch"
    exchange_fixtures_dir: Path | None = None
    # The site register: each site's terms decision (atlas.sources.gate).
    source_sites_config: Path = Path("configs/sources/sites.yaml")
    # Evidence Families: the SimHash Hamming distance within which a parse is a near
    # duplicate. A family keeps the threshold it was founded with (atlas.ledger.families).
    evidence_family_max_hamming_distance: int = Field(default=3, ge=0, le=64)

    # TradingView (atlas.tradingview; ticket 31): the owner's TradingView subscription through
    # its official MCP server, an owner override of TradingView's display-only terms for a
    # private, non-commercial proof of concept (docs/decisions.md). Off by default: while
    # off, nothing calls TradingView. The OAuth 2.1 tokens are the owner's: the token file
    # `atlas tradingview login` writes (mode 0600, gitignored; a refresh rewrites it), else
    # the access (and refresh) token given as secrets; never logged. Requests are paced at
    # tradingview_rate_per_s (at most 1/s), each job makes at most
    # tradingview_max_calls_per_job tool calls, and the `tradingview` budget allows
    # tradingview_budget_requests tool calls per rolling window.
    tradingview_enabled: bool = False
    tradingview_mcp_url: str = "https://mcp.tradingview.com/mcp"
    tradingview_access_token: SecretStr | None = None
    tradingview_refresh_token: SecretStr | None = None
    # For a refresh token given as a secret: the OAuth token endpoint and the client the
    # tokens were issued to (the token file records its own).
    tradingview_token_url: str | None = None
    tradingview_client_id: str | None = None
    tradingview_token_file: Path = Path(".atlas/tradingview-token.json")
    # `atlas tradingview login`'s loopback redirect port (0: any free port).
    tradingview_login_port: int = Field(default=0, ge=0, le=65535)
    tradingview_timeout_seconds: float = Field(default=60.0, gt=0)
    tradingview_rate_per_s: float = Field(default=0.5, gt=0, le=1)
    tradingview_max_calls_per_job: int = Field(default=20, ge=1, le=100)
    tradingview_budget_requests: int = Field(default=200, ge=1)
    tradingview_lookback_days: int = Field(default=730, ge=1)
    tradingview_documents_limit: int = Field(default=100, ge=1, le=500)
    tradingview_news_limit: int = Field(default=50, ge=1, le=200)
    tradingview_news_language: str = Field(default="en", pattern=r"^[a-z]{2}$")

    # The versioned company universe and themes (company membership is config, not code).
    themes_config: Path = Path("configs/themes/ai-infrastructure.yaml")
    # The canonical financial metrics: XBRL concept families by precedence (versioned config).
    financial_metrics_config: Path = Path("configs/financials/metrics.yaml")
    # The evaluation gold set `atlas evaluate` runs (docs/evaluation-methodology.md).
    evaluation_gold_dir: Path = Path("tests/evaluation/gold")

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

    @model_validator(mode="after")
    def _window_overlap_below_the_window(self) -> Self:
        if self.triage_window_overlap_chars >= self.triage_excerpt_chars:
            raise ValueError(
                "ATLAS_TRIAGE_WINDOW_OVERLAP_CHARS must be less than ATLAS_TRIAGE_EXCERPT_CHARS"
            )
        if self.triage_window_overlap_chars >= self.triage_judge_max_chars:
            raise ValueError(
                "ATLAS_TRIAGE_WINDOW_OVERLAP_CHARS must be less than ATLAS_TRIAGE_JUDGE_MAX_CHARS"
            )
        return self

    @model_validator(mode="after")
    def _tradingview_refresh_needs_its_client(self) -> Self:
        if self.tradingview_refresh_token and not (
            self.tradingview_token_url and self.tradingview_client_id
        ):
            raise ValueError(
                "ATLAS_TRADINGVIEW_REFRESH_TOKEN needs ATLAS_TRADINGVIEW_TOKEN_URL and"
                " ATLAS_TRADINGVIEW_CLIENT_ID (the OAuth token endpoint and client)"
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

    @field_validator("exchange_user_agent")
    @classmethod
    def _exchange_user_agent_is_generic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must name the client, e.g. 'AtlasResearch'")
        if "@" in value:
            raise ValueError("must not carry personal data such as an email address")
        return value

    def llm_aliases(self) -> list[str]:
        """The LiteLLM aliases whose routed deployments each run records."""
        return list(dict.fromkeys([self.llm_extract_alias, self.llm_reflect_alias]))

    def triage_enabled(self) -> bool:
        """Whether retention triage runs (ATLAS_RETENTION_TRIAGE; `auto`: with LiteLLM)."""
        if self.retention_triage == "auto":
            return bool(self.litellm_url and self.litellm_api_key)
        return self.retention_triage == "on"

    def searxng_engine_list(self) -> list[str]:
        return [engine.strip() for engine in self.searxng_engines.split(",") if engine.strip()]

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
        if not self.searxng_url:
            missing.append(("searxng", "ATLAS_SEARXNG_URL"))
        if not self.tradingview_enabled:
            missing.append(("tradingview", "ATLAS_TRADINGVIEW_ENABLED"))
        return missing
