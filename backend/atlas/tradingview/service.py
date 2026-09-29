"""The TradingView jobs: the catalog (documents and news metadata) and the transcripts.

Both run only with `ATLAS_TRADINGVIEW_ENABLED=true` (off by default: while off, a job fails
at once without calling TradingView). Both are `tradingview` budget kinds, and each makes
at most `ATLAS_TRADINGVIEW_MAX_CALLS_PER_JOB` tool calls, every one recorded in
`tradingview_request` (the budget's units), paced at `ATLAS_TRADINGVIEW_RATE_PER_S`.

**`tradingview_catalog`** (`{"company": "<slug>"}`): for the company's configured
`tradingview_symbol`,
1. `get_documents` over the lookback (`ATLAS_TRADINGVIEW_LOOKBACK_DAYS`): each document's
   metadata (category, form, fiscal period, reported time, title, upstream provider, its
   views' IDs and types) is upserted into the catalog (`tradingview_catalog_entry`). No
   summary or other content is stored; the catalog tells the owner and investigations which
   primary filings exist (e.g. which Innolight reports to download for manual import).
2. `get_news`: each headline's metadata becomes a Tier C lead (`tradingview_news`; its URL
   is the TradingView story, else the headline's link). Story text is never fetched.
3. When the catalog holds transcripts not yet recorded, it enqueues
   `tradingview_transcripts` for the company (same job class).

**`tradingview_transcripts`** (`{"company": "<slug>"}`): the catalog's transcript views for
the company, reported inside the lookback and not yet in the ledger, newest first, as many
as the job's call bound allows (a rerun takes the rest). Each `get_document_view` answer is
recorded by the source ledger exactly as received (media type
`application/x-tradingview-transcript+json`, parsed to text with speaker labels): a Tier B
Source Document of provider `tradingview`, the upstream provider (e.g. Quartr) as publisher,
`available_at` = the event's `reported` time (basis `publisher_timestamp`). With Hindsight
configured, each new English parse gets a `retain` job. A view TradingView answers with a
tool error (e.g. not retrievable) is skipped and listed; the attempt then fails after
recording the rest, like an exchange ingest.

Every stored item (catalog entry, headline, Source Version metadata, fetch observation)
records `OWNER_OVERRIDE`.
"""

import json
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Connection, Engine, text

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.companies import CompanyConfig, Universe, extend_universe, load_universe, seed
from atlas.discovery.leads import store_headline
from atlas.jobs.queue import Artifacts, Job, JobQueue
from atlas.ledger.service import SourceLedger, canonical_url
from atlas.parsing import TRADINGVIEW_TRANSCRIPT_MEDIA_TYPE
from atlas.retention.service import enqueue_retains
from atlas.settings import Settings
from atlas.sources import (
    FetchedDocument,
    HttpValidators,
    SourceCandidate,
    TokenBucket,
    TradingViewTranscript,
)
from atlas.tradingview.client import CallBoundReached, Document, TradingViewClient
from atlas.tradingview.mcp import McpClient, McpToolError
from atlas.tradingview.model import OWNER_OVERRIDE, PROVIDER_ID, TRANSCRIPTS_KIND, transcript_url
from atlas.tradingview.tokens import TokenStore

STORY_BASE = "https://www.tradingview.com"

# One limiter per rate in the process: every TradingView request waits for it.
_LIMITERS: dict[float, TokenBucket] = {}


class TradingViewDisabled(RuntimeError):
    """ATLAS_TRADINGVIEW_ENABLED is false: nothing calls TradingView."""


class TradingViewNotConfigured(ValueError):
    """The company has no TradingView symbol in the theme config."""


class TranscriptsIncomplete(Exception):
    """Some transcript views couldn't be fetched; the rest were recorded."""


class CompanyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company: str = Field(min_length=1)  # a company slug in the universe


def require_enabled(settings: Settings) -> None:
    if not settings.tradingview_enabled:
        raise TradingViewDisabled(
            "TradingView is off (ATLAS_TRADINGVIEW_ENABLED=false): nothing was called"
        )


def limiter(settings: Settings) -> TokenBucket:
    rate = settings.tradingview_rate_per_s
    return _LIMITERS.setdefault(rate, TokenBucket(rate_per_s=rate))


@contextmanager
def mcp_session(settings: Settings) -> Generator[McpClient]:
    """An MCP session with TradingView as the owner (tokens from `TokenStore`)."""
    require_enabled(settings)
    tokens = TokenStore(settings)
    try:
        with McpClient(
            settings.tradingview_mcp_url,
            tokens,
            limiter=limiter(settings),
            timeout=settings.tradingview_timeout_seconds,
            user_agent=settings.exchange_user_agent,
        ) as mcp:
            yield mcp
    finally:
        tokens.close()


def _recorder(engine: Engine, job_id: uuid.UUID | None) -> Callable[[str, str | None], None]:
    def record(tool: str, error: str | None) -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tradingview_request (id, job_id, tool, outcome, error)"
                    " VALUES (:id, :job, :tool, :outcome, :error)"
                ),
                {
                    "id": uuid.uuid4(),
                    "job": job_id,
                    "tool": tool,
                    "outcome": "ok" if error is None else "error",
                    "error": None if error is None else error[:500],
                },
            )

    return record


@dataclass(frozen=True)
class _Company:
    slug: str
    config: CompanyConfig
    company_id: uuid.UUID
    symbol: str
    themes: list[str]


def _company(engine: Engine, settings: Settings, actor: Actor, slug: str) -> _Company:
    universe: Universe = load_universe(settings.themes_config)
    with engine.begin() as connection:
        universe = extend_universe(connection, universe)
        if slug not in universe.companies:
            raise TradingViewNotConfigured(f"no company {slug!r} in the universe")
        (seeded,) = seed(connection, actor, universe, [slug])
    config = universe.companies[slug]
    if config.tradingview_symbol is None:
        raise TradingViewNotConfigured(
            f"company {slug!r} has no tradingview_symbol in {settings.themes_config}"
        )
    themes = sorted(t for t, theme in universe.themes.items() if slug in theme.companies)
    return _Company(slug, config, seeded.company_id, config.tradingview_symbol, themes)


def run_catalog(settings: Settings, engine: Engine, job: Job, now: datetime) -> Artifacts:
    require_enabled(settings)
    payload = CompanyPayload.model_validate(job.payload)
    actor = Actor.from_settings(settings)
    company = _company(engine, settings, actor, payload.company)
    documents: list[Document] = []
    new_documents = new_leads = headlines_listed = 0
    bounded = False
    with mcp_session(settings) as mcp:
        client = TradingViewClient(
            mcp,
            max_calls=settings.tradingview_max_calls_per_job,
            on_call=_recorder(engine, job.id),
        )
        try:
            documents = client.documents(
                company.symbol,
                start=now - timedelta(days=settings.tradingview_lookback_days),
                end=now,
                limit=settings.tradingview_documents_limit,
            ).items
            with engine.begin() as connection:
                for document in documents:
                    new_documents += _store_entry(connection, company, document, job.id)
            headlines = client.news(
                company.symbol,
                lang=settings.tradingview_news_language,
                limit=settings.tradingview_news_limit,
            )
            headlines_listed = len(headlines)
            with engine.begin() as connection:
                for headline in headlines:
                    story = (
                        f"{STORY_BASE}{headline.story_path}"
                        if headline.story_path and headline.story_path.startswith("/")
                        else headline.link
                    )
                    if not story:
                        continue
                    created = store_headline(
                        connection,
                        url=story,
                        title=headline.title,
                        published_at=headline.published_at,
                        headline_id=headline.id,
                        company_id=company.company_id,
                        symbol=company.symbol,
                        themes=company.themes,
                        publisher=headline.provider.name if headline.provider else None,
                        publisher_url=headline.link
                        if headline.link and headline.link != story
                        else headline.provider.url
                        if headline.provider
                        else None,
                        related_symbols=[s.symbol for s in headline.related_symbols],
                        urgency=headline.urgency,
                        owner_override=OWNER_OVERRIDE,
                        job_id=job.id,
                    )
                    new_leads += bool(created)
        except CallBoundReached:
            bounded = True
        calls = client.calls
    pending = len(_pending_transcripts(engine, settings, company, now))
    artifacts: Artifacts = {
        "company_id": str(company.company_id),
        "symbol": company.symbol,
        "documents": {"listed": len(documents), "new": new_documents},
        "news": {"listed": headlines_listed, "new_leads": new_leads},
        "transcripts_pending": pending,
        "tool_calls": calls,
        "bounded": bounded,
        "owner_override": OWNER_OVERRIDE,
    }
    if pending:
        enqueued = JobQueue(engine, actor=actor).enqueue(
            TRANSCRIPTS_KIND,
            f"catalog:{job.id}",
            {"company": company.slug},
            job_class=job.job_class,
        )
        artifacts["transcripts_job_id"] = str(enqueued.job.id)
    return artifacts


def _store_entry(
    connection: Connection, company: _Company, document: Document, job_id: uuid.UUID
) -> int:
    row = connection.execute(
        text(
            "INSERT INTO tradingview_catalog_entry (id, company_id, symbol, document_id,"
            " correlation_id, category_id, category, event, form_id, form, fiscal_period,"
            " fiscal_year, reported_at, status, title, upstream_provider_id, upstream_provider,"
            " views, owner_override, first_job_id) VALUES (:id, :company, :symbol, :document,"
            " :correlation, :category_id, :category, :event, :form_id, :form, :fiscal_period,"
            " :fiscal_year, :reported, :status, :title, :provider_id, :provider,"
            " CAST(:views AS jsonb), :override, :job)"
            " ON CONFLICT (document_id) DO UPDATE SET correlation_id = EXCLUDED.correlation_id,"
            " category_id = EXCLUDED.category_id, category = EXCLUDED.category,"
            " event = EXCLUDED.event, form_id = EXCLUDED.form_id, form = EXCLUDED.form,"
            " fiscal_period = EXCLUDED.fiscal_period, fiscal_year = EXCLUDED.fiscal_year,"
            " reported_at = EXCLUDED.reported_at, status = EXCLUDED.status,"
            " title = EXCLUDED.title, upstream_provider_id = EXCLUDED.upstream_provider_id,"
            " upstream_provider = EXCLUDED.upstream_provider, views = EXCLUDED.views,"
            " last_seen_at = now() RETURNING (xmax = 0) AS created"
        ),
        {
            "id": uuid.uuid4(),
            "company": company.company_id,
            "symbol": company.symbol,
            "document": document.id,
            "correlation": document.correlation_id,
            "category_id": document.category.id if document.category else None,
            "category": document.category.title if document.category else None,
            "event": document.event,
            "form_id": document.form.id if document.form else None,
            "form": document.form.title if document.form else None,
            "fiscal_period": document.fiscal_period,
            "fiscal_year": document.fiscal_year,
            "reported": document.reported_at,
            "status": document.status,
            "title": document.title,
            "provider_id": document.provider.id if document.provider else None,
            "provider": document.provider.name if document.provider else None,
            "views": _json([{"id": v.id, "type": v.type} for v in document.views]),
            "override": OWNER_OVERRIDE,
            "job": job_id,
        },
    ).one()
    return int(bool(row.created))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


@dataclass(frozen=True)
class _Pending:
    document_id: str
    view_id: str
    url: str
    title: str
    category: str | None
    event: str | None
    fiscal_period: str | None
    fiscal_year: str | None
    reported_at: datetime
    upstream_provider_id: str | None
    upstream_provider: str | None
    first_seen_at: datetime


def _pending_transcripts(
    engine: Engine, settings: Settings, company: _Company, now: datetime
) -> list[_Pending]:
    """The company's catalogued transcript views inside the lookback that the ledger doesn't
    hold yet, newest first."""
    since = now - timedelta(days=settings.tradingview_lookback_days)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT e.document_id, v->>'id' AS view_id, e.title, e.category, e.event,"
                " e.fiscal_period, e.fiscal_year, e.reported_at, e.upstream_provider_id,"
                " e.upstream_provider, e.first_seen_at FROM tradingview_catalog_entry e,"
                " jsonb_array_elements(e.views) v WHERE e.company_id = :company"
                " AND v->>'type' = 'transcript' AND e.reported_at >= :since"
                " AND e.reported_at <= :now ORDER BY e.reported_at DESC, e.document_id"
            ),
            {"company": company.company_id, "since": since, "now": now},
        ).mappings()
        pending = [
            _Pending(url=canonical_url(transcript_url(r["document_id"], r["view_id"])), **r)
            for r in rows
        ]
        recorded = set(
            connection.execute(
                text(
                    "SELECT canonical_url FROM source_document"
                    " WHERE provider = :provider AND canonical_url = ANY(:urls)"
                ),
                {"provider": PROVIDER_ID, "urls": [p.url for p in pending]},
            ).scalars()
        )
    return [p for p in pending if p.url not in recorded]


def run_transcripts(settings: Settings, engine: Engine, job: Job, now: datetime) -> Artifacts:
    require_enabled(settings)
    payload = CompanyPayload.model_validate(job.payload)
    actor = Actor.from_settings(settings)
    company = _company(engine, settings, actor, payload.company)
    pending = _pending_transcripts(engine, settings, company, now)
    ledger = SourceLedger(
        engine,
        open_archive(settings),
        actor,
        max_hamming_distance=settings.evidence_family_max_hamming_distance,
    )
    recorded: list[dict[str, JsonValue]] = []
    new_versions: list[uuid.UUID] = []
    errors: list[tuple[str, str]] = []
    bounded = False
    calls = 0
    if pending:
        with mcp_session(settings) as mcp:
            client = TradingViewClient(
                mcp,
                max_calls=settings.tradingview_max_calls_per_job,
                on_call=_recorder(engine, job.id),
            )
            for item in pending:
                try:
                    answer, view = client.document_view(item.view_id)
                except CallBoundReached:
                    bounded = True
                    break
                except McpToolError as error:
                    errors.append((item.view_id, str(error)))
                    continue
                fetched_at = datetime.now(UTC)
                upstream = (
                    (view.provider.name if view.provider else None)
                    or item.upstream_provider
                    or "unknown provider"
                )
                candidate = SourceCandidate(
                    provider_id=PROVIDER_ID,
                    kind="tradingview_transcript",
                    url=item.url,
                    title=view.title or item.title,
                    document_type=item.category,
                    discovered_at=item.first_seen_at,
                    available_at=item.reported_at,
                    available_at_basis="publisher_timestamp",
                    transcript=TradingViewTranscript(
                        symbol=company.symbol,
                        document_id=item.document_id,
                        view_id=item.view_id,
                        category=item.category,
                        event=item.event,
                        fiscal_period=item.fiscal_period,
                        fiscal_year=item.fiscal_year,
                        upstream_provider_id=(view.provider.id if view.provider else None)
                        or item.upstream_provider_id,
                        upstream_provider=upstream,
                        reported_at=item.reported_at,
                        view_published_at=view.published_at,
                        owner_override=OWNER_OVERRIDE,
                    ),
                )
                fetch = ledger.record(
                    FetchedDocument(
                        candidate=candidate,
                        url=item.url,
                        fetched_at=fetched_at,
                        not_modified=False,
                        content=answer.encode("utf-8"),
                        media_type=TRADINGVIEW_TRANSCRIPT_MEDIA_TYPE,
                        validators=HttpValidators(),
                        attempts=(),
                    ),
                    company_id=company.company_id,
                    job_id=job.id,
                    owner_override=OWNER_OVERRIDE,
                )
                if fetch.outcome == "new_version":
                    new_versions.append(fetch.source_version_id)
                recorded.append(
                    {
                        "view_id": item.view_id,
                        "outcome": fetch.outcome,
                        "source_document_id": str(fetch.source_document_id),
                        "source_version_id": str(fetch.source_version_id),
                    }
                )
            calls = client.calls
    retain_jobs = (
        enqueue_retains(engine, new_versions, job_class=job.job_class, actor=actor)
        if settings.hindsight_url
        else None
    )
    if errors:
        failed = "; ".join(f"{view}: {error}" for view, error in errors)
        raise TranscriptsIncomplete(
            f"{len(errors)} of {len(errors) + len(recorded)} transcript views not fetched"
            f" ({failed})"
        )
    artifacts: Artifacts = {
        "company_id": str(company.company_id),
        "symbol": company.symbol,
        "selected": len(pending),
        "recorded": list[JsonValue](recorded),
        "source_versions": [str(v) for v in new_versions],
        "remaining": len(pending) - len(recorded),
        "tool_calls": calls,
        "bounded": bounded,
        "owner_override": OWNER_OVERRIDE,
    }
    if retain_jobs is not None:
        artifacts["retain_jobs"] = list[JsonValue](retain_jobs)
    return artifacts
