"""The exchange ingest: an exchange-disclosed company's documents into the source ledger.

The `ingest` job runs this for a company whose source path is `exchange:<name>` (the SEC
path is `atlas.ledger.ingest`). One path serves every exchange; what differs per exchange
is an `ExchangeSource` in `EXCHANGE_SOURCES` (its feed's site and how to build its adapter
from the company's config). HKEXnews is the first; LSE RNS and Euronext add theirs.

1. Seed the company; load the site register (`ATLAS_SOURCE_SITES_CONFIG`).
2. Every request goes through a `GatedHttpClient`: the fetch gate (register, terms,
   robots.txt) decides first, and each decision is recorded (`fetch_gate_decision`,
   audited) whether it allowed or blocked. A blocked request is never made.
3. Discover (the feed's search), then fetch each candidate conditionally and record it in
   the ledger with the gate decision it was allowed by. `available_at` is the feed's
   publication time (basis `publisher_timestamp`).
4. When Hindsight is configured, each new parsed Source Version in English gets a `retain`
   job (`enqueue_retains` skips other languages).

A blocked feed or document is not a failure: the job succeeds and lists it under
`blocked` (it stays visible at `GET /api/v1/companies/{id}/fetch-gate-decisions`). A
document whose fetch fails is skipped, and the attempt then fails listing it, like the SEC
ingest.

Live requests are opt-in (`ATLAS_EXCHANGE_LIVE`, with `ATLAS_EXCHANGE_USER_AGENT`); by
default the adapter replays `ATLAS_EXCHANGE_FIXTURES_DIR/<company>/manifest.json`. The
gate applies to replays exactly as to live requests.
"""

import asyncio
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import JsonValue

from atlas.archive import Archive, open_archive
from atlas.audit import Actor
from atlas.companies import CompanyConfig, Universe, seed
from atlas.db import create_engine
from atlas.jobs.queue import Artifacts, Job
from atlas.ledger.gates import Purpose, record_decision
from atlas.ledger.service import RecordedFetch, SourceLedger
from atlas.retention.service import enqueue_retains
from atlas.settings import Settings
from atlas.sources import FetchError, FixtureReplay, SearchQuery, SecHttpClient, TokenBucket
from atlas.sources.adapter import SourceAdapter
from atlas.sources.edgar_fixtures import FIXTURE_USER_AGENT
from atlas.sources.gate import (
    FetchBlocked,
    FetchGate,
    GateDecision,
    GatedHttpClient,
    HttpGetter,
    SiteRegister,
    load_site_register,
)
from atlas.sources.hkexnews import PROVIDER_ID as HKEXNEWS
from atlas.sources.hkexnews import HkexNewsAdapter


class ExchangeIngestIncomplete(Exception):
    """Some documents could not be fetched; the rest were recorded."""


@dataclass(frozen=True)
class ExchangeSource:
    """One exchange's disclosure feed: the register's site for it, its provider ID, and how
    to build its adapter over a (gated) client from the company's config."""

    site: str
    provider_id: str
    make_adapter: Callable[[HttpGetter, str, CompanyConfig], SourceAdapter]


def _hkexnews_adapter(client: HttpGetter, slug: str, config: CompanyConfig) -> SourceAdapter:
    if config.exchange is None or config.exchange.feed_id is None:
        raise ValueError(
            f"company {slug!r} needs exchange.feed_id (its HKEXnews stockId) in the theme config"
        )
    return HkexNewsAdapter(client, stock_id=config.exchange.feed_id)


# Source path -> the exchange source that ingests it. Tickets 05/06 add lse-rns, euronext.
EXCHANGE_SOURCES: dict[str, ExchangeSource] = {
    "exchange:hkex": ExchangeSource("hkexnews", HKEXNEWS, _hkexnews_adapter),
}

# One limiter per site in the process, at the register's rate (live requests only).
_SITE_LIMITERS: dict[str, TokenBucket] = {}


def exchange_refusal(company: str, source_path: str) -> str | None:
    """Why a company on this source path can't be ingested, or None if it can."""
    if source_path == "sec" or source_path in EXCHANGE_SOURCES:
        return None
    return (
        f"company {company!r} has source path {source_path!r}, which no adapter ingests yet:"
        " nothing is fetched"
    )


def run_exchange_ingest(
    settings: Settings,
    job: Job,
    universe: Universe,
    slug: str,
    *,
    since: Any,
    limit: int | None,
) -> Artifacts:
    config = universe.companies[slug]
    source = EXCHANGE_SOURCES[config.source_path]
    register = load_site_register(settings.source_sites_config)
    actor = Actor.from_settings(settings)
    engine = create_engine(settings)
    try:
        with engine.begin() as connection:
            (seeded,) = seed(connection, actor, universe, [slug])
        archive = open_archive(settings)
        ledger = SourceLedger(
            engine,
            archive,
            actor,
            max_hamming_distance=settings.evidence_family_max_hamming_distance,
        )

        def log(decision: GateDecision, purpose: Purpose) -> uuid.UUID:
            return record_decision(
                engine,
                actor,
                decision,
                provider=source.provider_id,
                purpose=purpose,
                company_id=seeded.company_id,
                job_id=job.id,
            )

        client = _client(settings, register, source, slug)
        outcome = asyncio.run(
            _ingest(
                client,
                register,
                archive,
                source,
                slug,
                config,
                ledger,
                log,
                SearchQuery(since=since, limit=limit),
                seeded.company_id,
                job.id,
            )
        )
        retain_jobs = (
            enqueue_retains(
                engine,
                [f.source_version_id for f in outcome.recorded if f.outcome == "new_version"],
                job_class=job.job_class,
                actor=actor,
            )
            if settings.hindsight_url
            else None
        )
    finally:
        engine.dispose()
    if outcome.errors:
        failed = "; ".join(f"{url}: {error}" for url, error in outcome.errors)
        total = len(outcome.errors) + len(outcome.recorded)
        raise ExchangeIngestIncomplete(
            f"{len(outcome.errors)} of {total} documents not fetched ({failed})"
        )
    artifacts = _artifacts(seeded.company_id, outcome)
    if retain_jobs is not None:
        artifacts["retain_jobs"] = list[JsonValue](retain_jobs)
    return artifacts


def _client(
    settings: Settings, register: SiteRegister, source: ExchangeSource, slug: str
) -> SecHttpClient:
    if settings.exchange_live:
        assert settings.exchange_user_agent is not None  # required by settings validation
        rate = register.sites[source.site].rate_per_s if source.site in register.sites else 1.0
        limiter = _SITE_LIMITERS.setdefault(source.site, TokenBucket(rate_per_s=rate))
        return SecHttpClient(settings.exchange_user_agent, limiter=limiter)
    root = settings.exchange_fixtures_dir / slug if settings.exchange_fixtures_dir else None
    if root is None or not (root / "manifest.json").is_file():
        raise FileNotFoundError(
            f"no exchange fixtures for {slug}"
            + (f" in {settings.exchange_fixtures_dir}" if settings.exchange_fixtures_dir else "")
            + " (set ATLAS_EXCHANGE_FIXTURES_DIR, or ATLAS_EXCHANGE_LIVE=true)"
        )
    return SecHttpClient(
        FIXTURE_USER_AGENT,
        transport=FixtureReplay(root).transport(),
        limiter=TokenBucket(rate_per_s=math.inf),
    )


@dataclass
class _Outcome:
    recorded: list[RecordedFetch]
    errors: list[tuple[str, str]]
    blocked: list[dict[str, Any]]
    decisions: int


async def _ingest(
    client: SecHttpClient,
    register: SiteRegister,
    archive: Archive,
    source: ExchangeSource,
    slug: str,
    config: CompanyConfig,
    ledger: SourceLedger,
    log: Callable[[GateDecision, Purpose], uuid.UUID],
    query: SearchQuery,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
) -> _Outcome:
    outcome = _Outcome([], [], [], 0)

    def record_taken(gated: GatedHttpClient, purpose: Purpose) -> uuid.UUID | None:
        """Record the gate's pending decisions; the ID of the last allowed one."""
        allowed: uuid.UUID | None = None
        for decision in gated.take_decisions():
            decision_id = log(decision, purpose)
            outcome.decisions += 1
            if decision.status == "allowed":
                allowed = decision_id
            else:
                outcome.blocked.append(
                    {
                        "url": decision.url,
                        "purpose": purpose,
                        "blocked_by": decision.blocked_by,
                        "reason": decision.reason,
                        "gate_decision_id": str(decision_id),
                    }
                )
        return allowed

    async with client:
        gated = GatedHttpClient(client, FetchGate(register, client, archive=archive))
        adapter = source.make_adapter(gated, slug, config)
        try:
            candidates = await adapter.discover(query)
        except FetchBlocked:
            record_taken(gated, "discovery")
            return outcome
        except FetchError:
            record_taken(gated, "discovery")  # allowed and made, then failed
            raise
        record_taken(gated, "discovery")
        for candidate in candidates:
            validators = ledger.validators_for(candidate)
            if validators is not None:
                candidate = candidate.model_copy(update={"validators": validators})
            try:
                fetched = await adapter.fetch(candidate)
            except FetchBlocked:
                record_taken(gated, "document")
                continue
            except FetchError as error:
                record_taken(gated, "document")  # allowed and made, then failed
                outcome.errors.append((candidate.url, str(error)))
                continue
            decision_id = record_taken(gated, "document")
            outcome.recorded.append(
                ledger.record(
                    fetched, company_id=company_id, job_id=job_id, gate_decision_id=decision_id
                )
            )
    return outcome


def _artifacts(company_id: uuid.UUID, outcome: _Outcome) -> Artifacts:
    counts: dict[str, int] = {"new_version": 0, "unchanged": 0, "not_modified": 0}
    observations: list[Any] = []
    for fetch in outcome.recorded:
        counts[fetch.outcome] += 1
        observations.append(
            {
                "url": fetch.url,
                "outcome": fetch.outcome,
                "source_document_id": str(fetch.source_document_id),
                "source_version_id": str(fetch.source_version_id),
                "observation_id": str(fetch.observation_id),
            }
        )
    counts["blocked"] = len(outcome.blocked)
    return {
        "company_id": str(company_id),
        "counts": dict(counts),
        "source_versions": [
            str(f.source_version_id) for f in outcome.recorded if f.outcome == "new_version"
        ],
        "observations": observations,
        "blocked": list[Any](outcome.blocked),
        "gate_decisions": outcome.decisions,
    }
