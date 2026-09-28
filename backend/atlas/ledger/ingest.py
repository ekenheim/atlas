"""The `ingest` job: fetch a configured company's SEC material into the source ledger.

Payload: `{"company": "<slug>", "forms": [...]?, "limit": N?}`. The job seeds the company
from the theme config, discovers its filings (fixture replay, or live SEC when
`ATLAS_SEC_LIVE` is on), fetches each document (conditionally, with the validators of its
last fetch) and records it in the ledger. Re-running is safe: unchanged material makes
no new Source Version. When Hindsight is configured, each new parsed Source Version gets a
`retain` job (`atlas.retention`).

A document whose fetch fails is skipped and the others are still recorded; the attempt
then fails listing every failed URL, so a gap in coverage is never silent, and the retry
re-checks only cheaply (unchanged documents cost a 304 or a hash comparison).
"""

import asyncio
import math
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import create_engine

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.companies import load_universe, seed
from atlas.jobs.handlers import JobHandler
from atlas.jobs.queue import Artifacts, Job
from atlas.ledger.service import RecordedFetch, SourceLedger
from atlas.retention.service import enqueue_retains
from atlas.settings import Settings
from atlas.sources import (
    EdgarAdapter,
    FetchError,
    FixtureReplay,
    SearchQuery,
    SecHttpClient,
    TokenBucket,
)
from atlas.sources.edgar_fixtures import FIXTURE_USER_AGENT

INGEST_KIND = "ingest"


class IngestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    forms: list[str] | None = None  # default: the adapter's (10-K, 10-Q, 8-K and amendments)
    limit: int | None = Field(default=None, ge=1)  # at most this many recent filings


class IngestIncomplete(Exception):
    """Some documents could not be fetched; the rest were recorded."""


def ingest_payload(
    company: str, forms: list[str] | None, limit: int | None
) -> dict[str, JsonValue]:
    payload = IngestPayload(company=company, forms=forms, limit=limit)
    return payload.model_dump(mode="json", exclude_none=True)


def make_ingest_handler(settings: Settings) -> JobHandler:
    def handle(job: Job) -> Artifacts:
        return run_ingest(settings, job)

    return handle


def run_ingest(settings: Settings, job: Job) -> Artifacts:
    payload = IngestPayload.model_validate(job.payload)
    universe = load_universe(settings.themes_config)
    config = universe.companies.get(payload.company)
    if config is None:
        raise ValueError(f"company {payload.company!r} is not in {settings.themes_config}")
    if config.cik is None:
        raise ValueError(f"company {payload.company!r} has no SEC CIK configured")
    actor = Actor.from_settings(settings)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            (seeded,) = seed(connection, actor, universe, [payload.company])
        ledger = SourceLedger(engine, open_archive(settings), actor)
        client = _sec_client(settings, payload.company)
        query = SearchQuery(
            cik=config.cik,
            forms=tuple(payload.forms) if payload.forms else None,
            limit=payload.limit,
        )
        recorded, errors = asyncio.run(
            _fetch_all(client, ledger, config.cik, query, seeded.company_id, job.id)
        )
        # Every new parsed version is retained into memory, when Hindsight is configured;
        # also for a partial ingest, whose recorded versions are kept.
        retain_jobs = (
            enqueue_retains(
                engine, [f.source_version_id for f in recorded if f.outcome == "new_version"]
            )
            if settings.hindsight_url
            else None
        )
    finally:
        engine.dispose()
    if errors:
        failed = "; ".join(f"{url}: {error}" for url, error in errors)
        raise IngestIncomplete(
            f"{len(errors)} of {len(errors) + len(recorded)} documents not fetched ({failed})"
        )
    artifacts = _artifacts(seeded.company_id, recorded)
    if retain_jobs is not None:
        artifacts["retain_jobs"] = list[JsonValue](retain_jobs)
    return artifacts


def _sec_client(settings: Settings, company: str) -> SecHttpClient:
    if settings.sec_live:
        assert settings.sec_user_agent is not None  # required by settings validation
        return SecHttpClient(settings.sec_user_agent)
    root = settings.sec_fixtures_dir / company if settings.sec_fixtures_dir else None
    if root is None or not (root / "manifest.json").is_file():
        raise FileNotFoundError(
            f"no recorded EDGAR fixtures for {company}"
            + (f" in {settings.sec_fixtures_dir}" if settings.sec_fixtures_dir else "")
            + " (set ATLAS_SEC_FIXTURES_DIR, or ATLAS_SEC_LIVE=true to fetch from SEC)"
        )
    # Replays are local, so they skip the process-wide SEC rate limiter.
    return SecHttpClient(
        FIXTURE_USER_AGENT,
        transport=FixtureReplay(root).transport(),
        limiter=TokenBucket(rate_per_s=math.inf),
    )


async def _fetch_all(
    client: SecHttpClient,
    ledger: SourceLedger,
    cik: str,
    query: SearchQuery,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
) -> tuple[list[RecordedFetch], list[tuple[str, str]]]:
    recorded: list[RecordedFetch] = []
    errors: list[tuple[str, str]] = []
    async with client:
        adapter = EdgarAdapter(client, ciks=[cik])
        for candidate in await adapter.discover(query):
            validators = ledger.validators_for(candidate)
            if validators is not None:
                candidate = candidate.model_copy(update={"validators": validators})
            try:
                fetched = await adapter.fetch(candidate)
            except FetchError as error:
                errors.append((candidate.url, str(error)))
                continue
            recorded.append(ledger.record(fetched, company_id=company_id, job_id=job_id))
    return recorded, errors


def _artifacts(company_id: uuid.UUID, recorded: list[RecordedFetch]) -> Artifacts:
    counts: dict[str, int] = {"new_version": 0, "unchanged": 0, "not_modified": 0}
    observations: list[Any] = []
    for fetch in recorded:
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
    return {
        "company_id": str(company_id),
        "counts": dict(counts),
        "source_versions": [
            str(fetch.source_version_id) for fetch in recorded if fetch.outcome == "new_version"
        ],
        "observations": observations,
    }
