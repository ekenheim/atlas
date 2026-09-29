"""The `ingest` job: fetch a configured company's SEC material into the source ledger.

Payload: `{"company": "<slug>", "forms": [...]?, "limit": N?}`. The job seeds the company
from the theme config, discovers its filings (fixture replay, or live SEC when
`ATLAS_SEC_LIVE` is on), fetches each document (conditionally, with the validators of its
last fetch) and records it in the ledger. Re-running is safe: unchanged material makes
no new Source Version. When Hindsight is configured, each new parsed Source Version gets a
`retain` job (`atlas.retention`). The company's companyfacts Source Version is then normalized
into as-of financial observations (`atlas.financials`) unless it already was, with each
fact's availability taken from its filing in the submissions index.

Only companies whose source path is `sec` are ingested; any other (an exchange-disclosed
company such as Soitec) is refused before anything is seeded or fetched. The company's
configured `sec_forms` (e.g. 20-F/6-K for a foreign private issuer) apply when the job
names no forms.

A document whose fetch fails is skipped and the others are still recorded; the attempt
then fails listing every failed URL, so a gap in coverage is never silent, and the retry
re-checks only cheaply (unchanged documents cost a 304 or a hash comparison).
"""

import asyncio
import math
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Engine

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.companies import load_universe, seed
from atlas.db import create_engine
from atlas.financials import NormalizationSummary, is_normalized, normalize_source_version
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
    SecFiling,
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
    since: AwareDatetime | None = None  # only filings accepted after this (None: all history)


class IngestIncomplete(Exception):
    """Some documents could not be fetched; the rest were recorded."""


class NotAnSecFiler(ValueError):
    """The company's source path isn't `sec`, so the SEC ingest refuses it without fetching."""


def not_an_sec_filer_message(company: str, source_path: str) -> str:
    return (
        f"company {company!r} is not an SEC filer (source path {source_path!r}):"
        " the SEC ingest refuses it and fetches nothing; its exchange adapter ingests it"
    )


def ingest_payload(
    company: str,
    forms: list[str] | None,
    limit: int | None,
    since: datetime | None = None,
) -> dict[str, JsonValue]:
    payload = IngestPayload(company=company, forms=forms, limit=limit, since=since)
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
    if config.source_path != "sec" or config.cik is None:
        raise NotAnSecFiler(not_an_sec_filer_message(payload.company, config.source_path))
    actor = Actor.from_settings(settings)
    engine = create_engine(settings)
    try:
        with engine.begin() as connection:
            (seeded,) = seed(connection, actor, universe, [payload.company])
        archive = open_archive(settings)
        ledger = SourceLedger(
            engine,
            archive,
            actor,
            max_hamming_distance=settings.evidence_family_max_hamming_distance,
        )
        client = _sec_client(settings, payload.company)
        query = SearchQuery(
            cik=config.cik,
            # The job's forms, else the company's configured ones (e.g. 20-F/6-K), else the
            # adapter's default.
            forms=tuple(payload.forms or config.sec_forms or ()) or None,
            limit=payload.limit,
            since=payload.since,
        )
        recorded, errors, companyfacts = asyncio.run(
            _fetch_all(
                client,
                ledger,
                config.cik,
                query,
                seeded.company_id,
                job.id,
                eight_k_items=settings.eight_k_items(),
                exhibits_only_items=settings.eight_k_exhibits_only_items(),
                is_normalized=lambda version_id: _is_normalized(engine, version_id),
            )
        )
        # Every new parsed version is retained into memory, when Hindsight is configured;
        # also for a partial ingest, whose recorded versions are kept.
        retain_jobs = (
            enqueue_retains(
                engine,
                [f.source_version_id for f in recorded if f.outcome == "new_version"],
                job_class=job.job_class,  # a backfill ingest's retains are backfill too
                actor=actor,
            )
            if settings.hindsight_url
            else None
        )
        normalization = (
            normalize_source_version(
                engine,
                archive,
                actor,
                source_version_id=companyfacts[0],
                company_id=seeded.company_id,
                filings=companyfacts[1],
            )
            if companyfacts is not None
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
    if normalization is not None:
        artifacts["financial_normalization"] = _normalization_artifact(normalization)
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
    *,
    eight_k_items: tuple[str, ...] | None = None,
    exhibits_only_items: tuple[str, ...] = (),
    is_normalized: Callable[[uuid.UUID], bool] = lambda _: False,
) -> tuple[
    list[RecordedFetch],
    list[tuple[str, str]],
    tuple[uuid.UUID, list[SecFiling]] | None,
]:
    """(recorded fetches, failed URLs, the companyfacts version to normalize with the filer's
    filings), the last None when companyfacts wasn't recorded or is already normalized."""
    recorded: list[RecordedFetch] = []
    errors: list[tuple[str, str]] = []
    companyfacts: tuple[uuid.UUID, list[SecFiling]] | None = None
    async with client:
        adapter = EdgarAdapter(
            client,
            ciks=[cik],
            eight_k_items=eight_k_items,
            exhibits_only_items=exhibits_only_items,
        )
        for candidate in await adapter.discover(query):
            validators = ledger.validators_for(candidate)
            if validators is not None:
                candidate = candidate.model_copy(update={"validators": validators})
            try:
                fetched = await adapter.fetch(candidate)
            except FetchError as error:
                errors.append((candidate.url, str(error)))
                continue
            fetch = ledger.record(fetched, company_id=company_id, job_id=job_id)
            recorded.append(fetch)
            if candidate.kind == "sec_companyfacts" and not is_normalized(fetch.source_version_id):
                # The submissions index again (conditionally): each fact's filing's times.
                companyfacts = (fetch.source_version_id, await adapter.filings(cik))
    return recorded, errors, companyfacts


def _is_normalized(engine: Engine, source_version_id: uuid.UUID) -> bool:
    with engine.connect() as connection:
        return is_normalized(connection, source_version_id)


def _normalization_artifact(summary: NormalizationSummary) -> dict[str, JsonValue]:
    return {
        "id": str(summary.id),
        "source_version_id": str(summary.source_version_id),
        "normalizer_version": summary.normalizer_version,
        "facts_read": summary.facts_read,
        "observations_created": summary.observations_created,
    }


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
