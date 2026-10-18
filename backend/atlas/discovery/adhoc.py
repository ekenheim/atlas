"""Searches outside a discovery (Chokepoint Watch, W3): `web_search` and `filing_search`.

A discovery (`atlas.discovery.service`) is the Scout's batch of queries for a theme's question.
A research session, or anyone calling `GET /api/v1/web-search` or `GET /api/v1/filing-search`,
searches one query at a time and wants the results back with their lead ids. The results are
stored exactly as a discovery's are: a SearXNG result is a `searxng` lead, an EDGAR full-text hit
an `edgar_fts` lead with its filing (filer, CIK, form, dates, whether Atlas has archived it),
one per canonical URL (`atlas.discovery.leads.canonical_url`), each sighting recorded against the
query that returned it. The query is a `discovery_query` with no discovery (migration 0120): its
`theme` makes `GET /leads?theme=` find the leads, its `session_id` says which research session
ran it, and a filing search keeps its `edgar_search` row (forms, window, outcome).

A lead is where to look, never Evidence: nothing here fetches a page or a filing.

`published_by` (web search): a result that dates itself after it is left out of the answer and is
not stored; a result that carries no date cannot be bounded and is kept as a lead.
"""

import json
import uuid
from datetime import date

from pydantic import BaseModel
from sqlalchemy import Connection, Engine, text

from atlas.discovery.edgar_fts import EdgarFullTextSearch, FilingHit, FilingSearchFailed
from atlas.discovery.edgar_fts import filing_query as edgar_query
from atlas.discovery.leads import canonical_url, store_filing, store_result
from atlas.discovery.searxng import SearchFailed, SearXNGClient, UnresponsiveEngine


class WebHit(BaseModel):
    position: int
    lead_id: uuid.UUID
    url: str
    canonical_url: str
    title: str
    snippet: str
    published_date: date | None
    engines: list[str]
    new: bool  # this search created the lead


class WebSearchResult(BaseModel):
    query: str
    engines: list[str]
    language: str
    total: int  # results SearXNG returned
    new_leads: int
    dropped_after_bound: int  # results dated after `published_by`, left out and not stored
    unresponsive_engines: list[UnresponsiveEngine]
    results: list[WebHit]


class FilingResult(BaseModel):
    position: int
    lead_id: uuid.UUID
    cik: str
    filer: str
    ticker: str | None
    form: str
    file_type: str | None
    file_date: date
    period_ending: date | None
    accession: str
    document: str
    url: str
    new: bool
    company: str | None  # the universe company that filed it, by slug
    source_version_id: uuid.UUID | None  # the latest Source Version Atlas archived of it
    ingestable: bool  # a universe company's filing Atlas has not archived


class FilingSearchResult(BaseModel):
    query: str  # the `q` sent: each phrase in double quotes
    forms: list[str]
    start: date
    end: date
    total: int  # documents EDGAR matched (only the first are kept)
    new_leads: int
    results: list[FilingResult]


class SearchUnavailable(Exception):
    """The search backend is not configured (SearXNG without a URL, EDGAR without the SEC
    User-Agent or switched off)."""


class SearchError(Exception):
    """The backend was asked and failed; the query is recorded `failed`."""


def _query_row(
    connection: Connection,
    *,
    query: str,
    theme: str | None,
    session_id: uuid.UUID | None,
    status: str,
    result_count: int | None,
    new_leads: int | None,
    unresponsive: list[UnresponsiveEngine],
    error: str | None,
    filing_phrase: str | None,
) -> uuid.UUID:
    query_id = uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO discovery_query (id, discovery_id, position, query, status, result_count,"
            " new_leads, unresponsive_engines, error, searched_at, filing_phrase, theme,"
            " session_id) VALUES (:id, NULL, 1, :query, :status, :count, :new,"
            " CAST(:unresponsive AS jsonb), :error, now(), :phrase, :theme, :session)"
        ),
        {
            "id": query_id,
            "query": query,
            "status": status,
            "count": result_count,
            "new": new_leads,
            "unresponsive": json.dumps([each.model_dump() for each in unresponsive]),
            "error": error,
            "phrase": filing_phrase,
            "theme": theme,
            "session": session_id,
        },
    )
    return query_id


def web_search(
    engine: Engine,
    client: SearXNGClient,
    *,
    query: str,
    theme: str | None,
    session_id: uuid.UUID | None,
    published_by: date | None = None,
    limit: int = 20,
) -> WebSearchResult:
    """Search the web through SearXNG and store the first `limit` results as leads."""
    try:
        answer = client.search(query)
    except SearchFailed as error:
        with engine.begin() as connection:
            _query_row(
                connection,
                query=query,
                theme=theme,
                session_id=session_id,
                status="failed",
                result_count=None,
                new_leads=None,
                unresponsive=[],
                error=str(error),
                filing_phrase=None,
            )
        raise SearchError(str(error)) from None
    results = answer.results
    kept = [
        each
        for each in results
        if published_by is None
        or each.published_date is None
        or each.published_date <= published_by
    ]
    dropped = len(results) - len(kept)
    kept = kept[:limit]
    hits: dict[uuid.UUID, WebHit] = {}
    new_leads = 0
    with engine.begin() as connection:
        query_id = _query_row(
            connection,
            query=query,
            theme=theme,
            session_id=session_id,
            status="searched",
            result_count=len(kept),
            new_leads=None,
            unresponsive=answer.unresponsive_engines,
            error=None,
            filing_phrase=None,
        )
        for result in kept:
            created = store_result(connection, query_id, result)
            if created is None:  # not a web URL: no lead
                continue
            canonical = canonical_url(result.url)
            lead_id: uuid.UUID = connection.execute(
                text("SELECT id FROM lead WHERE canonical_url = :url"), {"url": canonical}
            ).scalar_one()
            if lead_id in hits:
                continue
            new_leads += int(created)
            hits[lead_id] = WebHit(
                position=result.position,
                lead_id=lead_id,
                url=result.url,
                canonical_url=canonical or result.url,
                title=result.title,
                snippet=result.snippet,
                published_date=result.published_date,
                engines=result.engines,
                new=created,
            )
        connection.execute(
            text(
                "UPDATE discovery_query SET new_leads = :new, result_count = :count WHERE id = :id"
            ),
            {"new": new_leads, "count": len(hits), "id": query_id},
        )
    return WebSearchResult(
        query=query,
        engines=client.engines,
        language=client.language,
        total=len(results),
        new_leads=new_leads,
        dropped_after_bound=dropped,
        unresponsive_engines=answer.unresponsive_engines,
        results=list(hits.values()),
    )


def filing_search(
    engine: Engine,
    client: EdgarFullTextSearch,
    *,
    phrases: list[str],
    start: date,
    end: date,
    theme: str | None,
    session_id: uuid.UUID | None,
    filing_phrase: str,
) -> FilingSearchResult:
    """Search EDGAR full-text for the phrases in filings dated `start` to `end` and store the
    hits (the client's `max_hits`) as `edgar_fts` leads."""
    q = edgar_query(phrases)
    try:
        found = client.search(phrases, start=start, end=end)
    except FilingSearchFailed as error:
        with engine.begin() as connection:
            query_id = _query_row(
                connection,
                query=q,
                theme=theme,
                session_id=session_id,
                status="failed",
                result_count=None,
                new_leads=None,
                unresponsive=[],
                error=str(error),
                filing_phrase=filing_phrase,
            )
            _edgar_row(
                connection, query_id, q, client, start, end, "failed", None, None, None, str(error)
            )
        raise SearchError(str(error)) from None
    results: dict[uuid.UUID, FilingResult] = {}
    new_leads = 0
    with engine.begin() as connection:
        query_id = _query_row(
            connection,
            query=q,
            theme=theme,
            session_id=session_id,
            status="searched",
            result_count=len(found.hits),
            new_leads=None,
            unresponsive=[],
            error=None,
            filing_phrase=filing_phrase,
        )
        for hit in found.hits:
            created = store_filing(connection, query_id, q, hit)
            lead_id, company, version_id, ingestable = _filing_row(connection, hit)
            if lead_id in results:
                continue
            new_leads += int(created)
            results[lead_id] = FilingResult(
                position=hit.position,
                lead_id=lead_id,
                cik=hit.cik,
                filer=hit.filer,
                ticker=hit.ticker,
                form=hit.form,
                file_type=hit.file_type,
                file_date=hit.file_date,
                period_ending=hit.period_ending,
                accession=hit.accession,
                document=hit.document,
                url=hit.url,
                new=created,
                company=company,
                source_version_id=version_id,
                ingestable=ingestable,
            )
        connection.execute(
            text(
                "UPDATE discovery_query SET new_leads = :new, result_count = :count WHERE id = :id"
            ),
            {"new": new_leads, "count": len(results), "id": query_id},
        )
        _edgar_row(
            connection,
            query_id,
            q,
            client,
            start,
            end,
            "searched",
            found.total,
            len(results),
            new_leads,
            None,
        )
    return FilingSearchResult(
        query=q,
        forms=list(client.forms),
        start=start,
        end=end,
        total=found.total,
        new_leads=new_leads,
        results=list(results.values()),
    )


def _edgar_row(
    connection: Connection,
    query_id: uuid.UUID,
    q: str,
    client: EdgarFullTextSearch,
    start: date,
    end: date,
    status: str,
    total: int | None,
    count: int | None,
    new_leads: int | None,
    error: str | None,
) -> None:
    connection.execute(
        text(
            "INSERT INTO edgar_search (discovery_query_id, query, forms, start_date, end_date,"
            " status, total_hits, result_count, new_leads, error, searched_at) VALUES (:id, :q,"
            " :forms, :start, :end, :status, :total, :count, :new, :error, now())"
        ),
        {
            "id": query_id,
            "q": q,
            "forms": list(client.forms),
            "start": start,
            "end": end,
            "status": status,
            "total": total,
            "count": count,
            "new": new_leads,
            "error": error,
        },
    )


def _filing_row(
    connection: Connection, hit: FilingHit
) -> tuple[uuid.UUID, str | None, uuid.UUID | None, bool]:
    row = connection.execute(
        text(
            "SELECT l.id, c.slug, f.source_version_id, f.ingestable FROM lead l"
            " JOIN edgar_filing f ON f.lead_id = l.id LEFT JOIN company c ON c.id = f.company_id"
            " WHERE l.canonical_url = :url"
        ),
        {"url": canonical_url(hit.url)},
    ).one()
    return row.id, row.slug, row.source_version_id, bool(row.ingestable)
