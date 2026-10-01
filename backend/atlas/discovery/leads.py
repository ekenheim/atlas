"""Leads: Tier C metadata about web pages a discovery found, one per canonical URL.

A lead is where to look, never proof (spec §4.1 Tier C): it holds a search result's URL,
title, snippet, published date and engines, and the query that first found it. It is never
Evidence and never retained into Hindsight: no Source Version, Assertion, memory document
or job is made from it (a Candidate, ticket 09, is the only thing a lead can propose).

**Canonical URL** (the dedupe key): only `http` and `https` URLs are leads. The scheme and
host are lowercased, a leading `www.` and a default port are dropped, the fragment is
dropped, tracking parameters (`utm_*`, `gclid`, `fbclid`, `msclkid`, `mc_cid`, `mc_eid`,
`igshid`) are removed and the rest sorted, and a trailing `/` is dropped from a non-root
path. The path's case is kept. Syndicated copies at different URLs stay separate leads;
grouping them is Evidence Families' job.

**Origins.** A `searxng` lead was found by a discovery's query. A `tradingview_news` lead is a
TradingView news headline (ticket 31, an owner override that is off by default): its
metadata only (title, original publisher, published time, TradingView link, related
symbols), with no query; it belongs to the themes of the company it was listed for. Story
text is never stored. An `edgar_fts` lead is a filing document an EDGAR full-text search
returned for a query's filing phrase (atlas.discovery.edgar_fts; pilot fix 12): its URL is
the document's in the EDGAR archive, its title `<filer> <form> filed <date>`, its snippet
says which phrase EDGAR matched in it (EDGAR returns no text), and its `filing` holds the
filer's CIK, the form and dates, the universe company that filed it, the Source Version Atlas
archived of it, if any, and whether it is `ingestable` (a universe company's filing Atlas
hasn't archived). The document is not fetched: the lead is where to look.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel
from sqlalchemy import Connection, RowMapping, text

from atlas.discovery.edgar_fts import FilingHit, filing_phrases
from atlas.discovery.ranking import Sighting
from atlas.discovery.searxng import SearchResult

_TRACKING = frozenset({"gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "igshid"})
_DEFAULT_PORTS = {"http": 80, "https": 443}


def canonical_url(url: str) -> str | None:
    """The lead's dedupe key for `url` (see the module), or None when it isn't a web URL."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    host = host.removeprefix("www.")
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key not in _TRACKING and not key.startswith("utm_")
        )
    )
    return urlunsplit((scheme, netloc, path, query, ""))


class Headline(BaseModel):
    """A TradingView news headline's metadata (a `tradingview_news` lead)."""

    headline_id: str  # TradingView's
    company_id: uuid.UUID  # the company whose symbol it was listed for
    symbol: str
    publisher: str | None  # the original publisher, as TradingView names it
    publisher_url: str | None  # the original story's link, when TradingView gives one
    published_at: datetime | None
    related_symbols: list[str]
    owner_override: str  # the owner's recorded override of TradingView's terms


class Filing(BaseModel):
    """An `edgar_fts` lead's filing (EDGAR full-text search's metadata)."""

    cik: str  # the filer's
    filer: str
    ticker: str | None
    form: str
    file_type: str | None  # the document's type when it isn't the form (an exhibit)
    file_date: date
    period_ending: date | None
    accession: str
    document: str  # the file name in the filing
    company_id: uuid.UUID | None  # the universe company that filed it, if any
    source_version_id: uuid.UUID | None  # the latest Source Version Atlas archived of it
    ingestable: bool  # a universe company's filing Atlas hasn't archived


class Lead(BaseModel):
    id: uuid.UUID
    tier: Literal["C"]  # always: a lead is never Evidence
    origin: Literal["searxng", "tradingview_news", "edgar_fts"]
    canonical_url: str
    url: str  # as first found
    title: str
    snippet: str
    published_date: date | None  # the search result's, when it gave one
    engines: list[str]  # every engine that has returned it
    query: str | None  # the query that first found it (None: a TradingView headline)
    theme: str | None  # the theme of the discovery (or the headline's company) it came from
    sightings: int  # how many query results have returned it
    first_seen_at: datetime
    last_seen_at: datetime
    headline: Headline | None = None  # a `tradingview_news` lead's metadata
    filing: Filing | None = None  # an `edgar_fts` lead's filing


def store_result(connection: Connection, query_id: uuid.UUID, result: SearchResult) -> bool | None:
    """Record `result` of query `query_id` as a lead sighting, creating the lead if its
    canonical URL is new. Returns whether a lead was created, or None when the result isn't
    a web URL (no lead). A result the same query already returned is recorded once."""
    canonical = canonical_url(result.url)
    if canonical is None:
        return None
    row = connection.execute(
        text(
            "INSERT INTO lead (id, canonical_url, url, title, snippet, published_date, engines,"
            " first_query_id) VALUES (:id, :canonical, :url, :title, :snippet, :published,"
            " :engines, :query)"
            " ON CONFLICT (canonical_url) DO UPDATE SET last_seen_at = now(),"
            " engines = ARRAY(SELECT DISTINCT e FROM unnest(lead.engines || EXCLUDED.engines) e"
            " ORDER BY e)"
            " RETURNING id, (xmax = 0) AS created"
        ),
        {
            "id": uuid.uuid4(),
            "canonical": canonical,
            "url": result.url,
            "title": result.title,
            "snippet": result.snippet,
            "published": result.published_date,
            "engines": sorted(set(result.engines)),
            "query": query_id,
        },
    ).one()
    connection.execute(
        text(
            "INSERT INTO lead_sighting (lead_id, discovery_query_id, position, url, title,"
            " snippet, engines, published_date) VALUES (:lead, :query, :position, :url,"
            " :title, :snippet, :engines, :published) ON CONFLICT DO NOTHING"
        ),
        {
            "lead": row.id,
            "query": query_id,
            "position": result.position,
            "url": result.url,
            "title": result.title,
            "snippet": result.snippet,
            "engines": result.engines,
            "published": result.published_date,
        },
    )
    return bool(row.created)


def filing_snippet(query: str, hit: FilingHit) -> str:
    """What an `edgar_fts` lead's snippet says: that EDGAR matched the phrase(s) in it."""
    document = hit.file_type if hit.file_type and hit.file_type != hit.form else hit.form
    period = f", period ending {hit.period_ending.isoformat()}" if hit.period_ending else ""
    return (
        f"EDGAR full-text search matched {query} in this {document} of {hit.filer}"
        f" (CIK {hit.cik}{period})."
    )


def store_filing(connection: Connection, query_id: uuid.UUID, query: str, hit: FilingHit) -> bool:
    """Record filing `hit` of query `query_id`'s EDGAR search (`query`: the `q` sent) as a
    lead sighting, creating the `edgar_fts` lead if its canonical URL is new; its filing is
    recorded (or refreshed) with the universe company that filed it and its archived Source
    Version. Returns whether a lead was created."""
    canonical = canonical_url(hit.url)
    assert canonical is not None  # an EDGAR archive URL
    snippet = filing_snippet(query, hit)
    row = connection.execute(
        text(
            "INSERT INTO lead (id, canonical_url, url, title, snippet, published_date, engines,"
            " first_query_id, origin) VALUES (:id, :canonical, :url, :title, :snippet,"
            " :published, ARRAY['edgar_fts'], :query, 'edgar_fts')"
            " ON CONFLICT (canonical_url) DO UPDATE SET last_seen_at = now(),"
            " engines = ARRAY(SELECT DISTINCT e FROM unnest(lead.engines || EXCLUDED.engines) e"
            " ORDER BY e)"
            " RETURNING id, (xmax = 0) AS created"
        ),
        {
            "id": uuid.uuid4(),
            "canonical": canonical,
            "url": hit.url,
            "title": hit.title,
            "snippet": snippet,
            "published": hit.file_date,
            "query": query_id,
        },
    ).one()
    connection.execute(
        text(
            "INSERT INTO lead_sighting (lead_id, discovery_query_id, position, url, title,"
            " snippet, engines, published_date, channel) VALUES (:lead, :query, :position,"
            " :url, :title, :snippet, ARRAY['edgar_fts'], :published, 'edgar_fts')"
            " ON CONFLICT DO NOTHING"
        ),
        {
            "lead": row.id,
            "query": query_id,
            "position": hit.position,
            "url": hit.url,
            "title": hit.title,
            "snippet": snippet,
            "published": hit.file_date,
        },
    )
    company_id = connection.execute(
        text("SELECT id FROM company WHERE cik = :cik AND role = 'researched'"), {"cik": hit.cik}
    ).scalar_one_or_none()
    version_id = connection.execute(
        text(
            "SELECT v.id FROM source_version v JOIN source_document d"
            " ON d.id = v.source_document_id WHERE d.canonical_url = :url"
            " ORDER BY v.available_at DESC, v.id DESC LIMIT 1"
        ),
        {"url": hit.url},
    ).scalar_one_or_none()
    connection.execute(
        text(
            "INSERT INTO edgar_filing (lead_id, cik, filer, ticker, form, file_type, file_date,"
            " period_ending, accession, document, company_id, source_version_id, ingestable)"
            " VALUES (:lead, :cik, :filer, :ticker, :form, :file_type, :file_date, :period,"
            " :accession, :document, :company, :version, :ingestable)"
            " ON CONFLICT (lead_id) DO UPDATE SET company_id = EXCLUDED.company_id,"
            " source_version_id = EXCLUDED.source_version_id,"
            " ingestable = EXCLUDED.ingestable, updated_at = now()"
        ),
        {
            "lead": row.id,
            "cik": hit.cik,
            "filer": hit.filer,
            "ticker": hit.ticker,
            "form": hit.form,
            "file_type": hit.file_type,
            "file_date": hit.file_date,
            "period": hit.period_ending,
            "accession": hit.accession,
            "document": hit.document,
            "company": company_id,
            "version": version_id,
            "ingestable": company_id is not None and version_id is None,
        },
    )
    return bool(row.created)


def store_headline(
    connection: Connection,
    *,
    url: str,
    title: str,
    published_at: datetime | None,
    headline_id: str,
    company_id: uuid.UUID,
    symbol: str,
    themes: Sequence[str],
    publisher: str | None,
    publisher_url: str | None,
    related_symbols: Sequence[str],
    urgency: int | None,
    owner_override: str,
    job_id: uuid.UUID | None,
) -> bool | None:
    """Record a TradingView headline as a `tradingview_news` lead (metadata only), unless its
    canonical URL is a lead already. Returns whether a lead was created, or None when `url`
    isn't a web URL (no lead)."""
    canonical = canonical_url(url)
    if canonical is None:
        return None
    row = connection.execute(
        text(
            "INSERT INTO lead (id, canonical_url, url, title, snippet, published_date, engines,"
            " first_query_id, origin) VALUES (:id, :canonical, :url, :title, '', :published,"
            " ARRAY['tradingview'], NULL, 'tradingview_news')"
            " ON CONFLICT (canonical_url) DO UPDATE SET last_seen_at = now()"
            " RETURNING id, (xmax = 0) AS created"
        ),
        {
            "id": uuid.uuid4(),
            "canonical": canonical,
            "url": url,
            "title": title,
            "published": published_at.date() if published_at else None,
        },
    ).one()
    connection.execute(
        text(
            "INSERT INTO tradingview_headline (lead_id, headline_id, company_id, symbol, themes,"
            " publisher, publisher_url, published_at, related_symbols, urgency, owner_override,"
            " job_id) VALUES (:lead, :headline, :company, :symbol, :themes, :publisher,"
            " :publisher_url, :published, :related, :urgency, :override, :job)"
            " ON CONFLICT DO NOTHING"
        ),
        {
            "lead": row.id,
            "headline": headline_id,
            "company": company_id,
            "symbol": symbol,
            "themes": list(themes),
            "publisher": publisher,
            "publisher_url": publisher_url,
            "published": published_at,
            "related": list(related_symbols),
            "urgency": urgency,
            "override": owner_override,
            "job": job_id,
        },
    )
    return bool(row.created)


def discovery_sightings(connection: Connection, discovery_id: uuid.UUID) -> list[Sighting]:
    """Every lead sighting of a discovery as ranking scores it (atlas.discovery.ranking), in
    the order found: each with the query that returned it and that query's purpose. An EDGAR
    filing hit is scored against its query like a web result, and carries the phrases its
    search matched (`matched`)."""
    rows = connection.execute(
        text(
            "SELECT s.lead_id, s.url, s.title, s.snippet, q.query, q.purpose,"
            " CASE WHEN s.channel = 'edgar_fts' THEN e.query END AS matched"
            " FROM lead_sighting s"
            " JOIN discovery_query q ON q.id = s.discovery_query_id"
            " LEFT JOIN edgar_search e ON e.discovery_query_id = q.id"
            " WHERE q.discovery_id = :discovery"
            " ORDER BY q.position, s.channel DESC, s.position, s.lead_id"
        ),
        {"discovery": discovery_id},
    )
    return [
        Sighting(
            lead_id=row.lead_id,
            url=row.url,
            title=row.title,
            snippet=row.snippet,
            query=row.query,
            purpose=row.purpose,
            matched=tuple(filing_phrases(row.matched)),
        )
        for row in rows
    ]


_LEADS = """
    SELECT lead.id, lead.tier, lead.origin, lead.canonical_url, lead.url, lead.title,
        lead.snippet, lead.published_date, lead.engines, lead.first_seen_at, lead.last_seen_at,
        first.query, COALESCE(discovery.theme, h.themes[1]) AS theme,
        (SELECT count(*) FROM lead_sighting s WHERE s.lead_id = lead.id) AS sightings,
        h.headline_id, h.company_id AS headline_company_id, h.symbol AS headline_symbol,
        h.publisher, h.publisher_url, h.published_at AS headline_published_at,
        h.related_symbols, h.owner_override,
        f.cik AS filing_cik, f.filer AS filing_filer, f.ticker AS filing_ticker,
        f.form AS filing_form, f.file_type AS filing_file_type, f.file_date AS filing_file_date,
        f.period_ending AS filing_period_ending, f.accession AS filing_accession,
        f.document AS filing_document, f.company_id AS filing_company_id,
        f.source_version_id AS filing_source_version_id, f.ingestable AS filing_ingestable
    FROM lead
    LEFT JOIN discovery_query first ON first.id = lead.first_query_id
    LEFT JOIN discovery ON discovery.id = first.discovery_id
    LEFT JOIN tradingview_headline h ON h.lead_id = lead.id
    LEFT JOIN edgar_filing f ON f.lead_id = lead.id
"""
# A lead belongs to a theme when a discovery for that theme has returned it, or when it is a
# headline listed for a company in that theme.
_IN_THEME = """
    WHERE CAST(:theme AS text) IS NULL OR EXISTS (
        SELECT 1 FROM lead_sighting s
        JOIN discovery_query q ON q.id = s.discovery_query_id
        JOIN discovery d ON d.id = q.discovery_id
        WHERE s.lead_id = lead.id AND d.theme = :theme)
    OR EXISTS (
        SELECT 1 FROM tradingview_headline t WHERE t.lead_id = lead.id AND :theme = ANY(t.themes))
"""
_HEADLINE_COLUMNS = (
    "headline_id",
    "headline_company_id",
    "headline_symbol",
    "publisher",
    "publisher_url",
    "headline_published_at",
    "related_symbols",
    "owner_override",
)


def _lead(row: RowMapping) -> Lead:
    fields = {
        k: v for k, v in row.items() if k not in _HEADLINE_COLUMNS and not k.startswith("filing_")
    }
    filing = None
    if row["filing_cik"] is not None:
        filing = Filing.model_validate(
            {k.removeprefix("filing_"): v for k, v in row.items() if k.startswith("filing_")}
        )
    headline = None
    if row["headline_id"] is not None:
        headline = Headline(
            headline_id=row["headline_id"],
            company_id=row["headline_company_id"],
            symbol=row["headline_symbol"],
            publisher=row["publisher"],
            publisher_url=row["publisher_url"],
            published_at=row["headline_published_at"],
            related_symbols=list(row["related_symbols"]),
            owner_override=row["owner_override"],
        )
    return Lead.model_validate({**fields, "headline": headline, "filing": filing})


def list_leads(
    connection: Connection, *, theme: str | None, limit: int, offset: int
) -> tuple[list[Lead], int]:
    """Leads, newest first (optionally only those a discovery for `theme` returned), and
    how many there are in all."""
    total = connection.execute(
        text(f"SELECT count(*) FROM lead {_IN_THEME}"),  # noqa: S608 (constant SQL)
        {"theme": theme},
    ).scalar_one()
    rows = connection.execute(
        text(
            f"{_LEADS} {_IN_THEME} ORDER BY lead.first_seen_at DESC, lead.id"
            " LIMIT :limit OFFSET :offset"
        ),
        {"theme": theme, "limit": limit, "offset": offset},
    ).mappings()
    return [_lead(row) for row in rows], int(total)
