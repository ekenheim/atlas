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

A `tradingview_calendar` lead is a company's reporting date from TradingView's earnings
calendar (ticket 16b; the same owner override, off by default): one lead per company and fiscal
period, no query, no snippet, the date and status in `calendar`. A date that moves is a new
insert-only observation of the same lead, so a read `known_by` an earlier time sees the date
Atlas knew then and nothing stored after it. A lead says when to look (e.g. for a results
call), never what a company said.

An `archive_signal` lead is a sentence of an archived document that reads like a bottleneck
(atlas-beliefs ticket 18; `atlas.discovery.signals`, stored by the `scan_signals` job): its
`signal` holds the sentence verbatim with its span in the named parse, the section, the
company, the cue families that matched, the score and the speaker of a call transcript's
sentence. A lead is where to look; the agent that follows it reads the window and records a
Fact itself. For this origin `known_by` is when the document became public (its effective
availability), not when the scan ran, and `GET /leads?origin=archive_signal` is ranked by score.
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


class CalendarEvent(BaseModel):
    """A `tradingview_calendar` lead's reporting date (TradingView's earnings calendar)."""

    company_id: uuid.UUID  # the company whose symbol it was listed for
    symbol: str
    event_key: str  # what Atlas deduplicates the lead by (TradingView's event ID, else the period)
    event_at: datetime  # the reporting date, as the calendar last gave it (by `known_by`)
    status: str | None  # as the calendar words it (scheduled, confirmed, reported ...)
    fiscal_period: str | None
    fiscal_year: str | None
    observed_at: datetime  # when Atlas saw that date
    owner_override: str  # the owner's recorded override of TradingView's terms


class SignalMatch(BaseModel):
    """One phrase of a cue family that matched the sentence."""

    family: str
    pattern: str
    text: str  # as the sentence writes it


class Signal(BaseModel):
    """An `archive_signal` lead's sentence and why it scored."""

    source_version_id: uuid.UUID
    company_id: uuid.UUID
    company: str  # the slug
    parser_version: str  # the parse the span is in: an Assertion on it names this version
    section_anchor: str | None
    char_start: int  # code points into that parse's text, like an Assertion's span
    char_end: int
    quote: str  # the text at the span, verbatim
    families: list[str]
    matches: list[SignalMatch]
    factors: dict[str, float]  # what made the score: the families, bonuses and multipliers
    score: float
    speaker: str | None  # a call transcript's speaker label
    speaker_kind: Literal["management", "analyst", "unknown"] | None
    available_at: datetime  # when the document became public
    scorer_version: str


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
    origin: Literal[
        "searxng", "tradingview_news", "edgar_fts", "tradingview_calendar", "archive_signal"
    ]
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
    calendar: CalendarEvent | None = None  # a `tradingview_calendar` lead's reporting date
    signal: Signal | None = None  # an `archive_signal` lead's sentence


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


def store_calendar_event(
    connection: Connection,
    *,
    url: str,
    title: str,
    event_key: str,
    company_id: uuid.UUID,
    symbol: str,
    themes: Sequence[str],
    fiscal_period: str | None,
    fiscal_year: str | None,
    event_at: datetime,
    status: str | None,
    owner_override: str,
    job_id: uuid.UUID | None,
    now: datetime,
) -> bool | None:
    """Record a TradingView calendar date as a `tradingview_calendar` lead (metadata only),
    one per event: the first sighting makes the lead, and a date or status that differs from
    the last observed one adds an observation (insert-only; `now` is when Atlas saw it).
    Returns whether a lead was created, or None when `url` isn't a web URL (no lead)."""
    canonical = canonical_url(url)
    if canonical is None:
        return None
    row = connection.execute(
        text(
            "INSERT INTO lead (id, canonical_url, url, title, snippet, published_date, engines,"
            " first_query_id, origin, first_seen_at, last_seen_at) VALUES (:id, :canonical, :url,"
            " :title, '', NULL, ARRAY['tradingview'], NULL, 'tradingview_calendar', :now, :now)"
            " ON CONFLICT (canonical_url) DO UPDATE SET last_seen_at = :now"
            " RETURNING id, (xmax = 0) AS created"
        ),
        {"id": uuid.uuid4(), "canonical": canonical, "url": url, "title": title, "now": now},
    ).one()
    connection.execute(
        text(
            "INSERT INTO tradingview_calendar_event (lead_id, event_key, company_id, symbol,"
            " themes, fiscal_period, fiscal_year, owner_override, job_id, first_seen_at)"
            " VALUES (:lead, :key, :company, :symbol, :themes, :period, :year, :override, :job,"
            " :now) ON CONFLICT (lead_id) DO NOTHING"
        ),
        {
            "lead": row.id,
            "key": event_key,
            "company": company_id,
            "symbol": symbol,
            "themes": list(themes),
            "period": fiscal_period,
            "year": fiscal_year,
            "override": owner_override,
            "job": job_id,
            "now": now,
        },
    )
    last = connection.execute(
        text(
            "SELECT event_at, status FROM tradingview_calendar_observation WHERE lead_id = :lead"
            " ORDER BY observed_at DESC, id DESC LIMIT 1"
        ),
        {"lead": row.id},
    ).one_or_none()
    if last is None or (last.event_at, last.status) != (event_at, status):
        connection.execute(
            text(
                "INSERT INTO tradingview_calendar_observation (id, lead_id, event_at, status,"
                " owner_override, job_id, observed_at) VALUES (:id, :lead, :event_at, :status,"
                " :override, :job, :now)"
            ),
            {
                "id": uuid.uuid4(),
                "lead": row.id,
                "event_at": event_at,
                "status": status,
                "override": owner_override,
                "job": job_id,
                "now": now,
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
        lead.snippet, lead.published_date, lead.engines, lead.first_seen_at,
        LEAST(lead.last_seen_at, CAST(:known_by AS timestamptz)) AS last_seen_at,
        first.query,
        COALESCE(discovery.theme, h.themes[1], ce.themes[1], sig.themes[1]) AS theme,
        (SELECT count(*) FROM lead_sighting s WHERE s.lead_id = lead.id) AS sightings,
        h.headline_id, h.company_id AS headline_company_id, h.symbol AS headline_symbol,
        h.publisher, h.publisher_url, h.published_at AS headline_published_at,
        h.related_symbols, h.owner_override,
        f.cik AS filing_cik, f.filer AS filing_filer, f.ticker AS filing_ticker,
        f.form AS filing_form, f.file_type AS filing_file_type, f.file_date AS filing_file_date,
        f.period_ending AS filing_period_ending, f.accession AS filing_accession,
        f.document AS filing_document, f.company_id AS filing_company_id,
        f.source_version_id AS filing_source_version_id, f.ingestable AS filing_ingestable,
        ce.company_id AS calendar_company_id, ce.symbol AS calendar_symbol,
        ce.event_key AS calendar_event_key, ce.fiscal_period AS calendar_fiscal_period,
        ce.fiscal_year AS calendar_fiscal_year, ce.owner_override AS calendar_owner_override,
        co.event_at AS calendar_event_at, co.status AS calendar_status,
        co.observed_at AS calendar_observed_at,
        sig.source_version_id AS signal_source_version_id, sig.company_id AS signal_company_id,
        sc.slug AS signal_company, sig.parser_version AS signal_parser_version,
        sig.section_anchor AS signal_section_anchor, sig.char_start AS signal_char_start,
        sig.char_end AS signal_char_end, sig.quote AS signal_quote,
        sig.families AS signal_families, sig.matches AS signal_matches,
        sig.factors AS signal_factors, sig.score AS signal_score,
        sig.speaker AS signal_speaker, sig.speaker_kind AS signal_speaker_kind,
        sa.available_at AS signal_available_at, sig.scorer_version AS signal_scorer_version
    FROM lead
    LEFT JOIN discovery_query first ON first.id = lead.first_query_id
    LEFT JOIN discovery ON discovery.id = first.discovery_id
    LEFT JOIN tradingview_headline h ON h.lead_id = lead.id
    LEFT JOIN edgar_filing f ON f.lead_id = lead.id
    LEFT JOIN tradingview_calendar_event ce ON ce.lead_id = lead.id
    LEFT JOIN archive_signal sig ON sig.lead_id = lead.id
    LEFT JOIN company sc ON sc.id = sig.company_id
    LEFT JOIN source_version_availability sa ON sa.source_version_id = sig.source_version_id
    LEFT JOIN LATERAL (
        SELECT o.event_at, o.status, o.observed_at FROM tradingview_calendar_observation o
        WHERE o.lead_id = lead.id
        AND (CAST(:known_by AS timestamptz) IS NULL OR o.observed_at <= :known_by)
        ORDER BY o.observed_at DESC, o.id DESC LIMIT 1) co ON true
"""
# The count needs the same joins, none of the columns.
_LEAD_JOINS = _LEADS[_LEADS.index("    FROM lead") :]
# A lead belongs to a theme when a discovery for that theme has returned it, or when it is a
# headline, a calendar date or an archive signal of a company in that theme. `known_by` bounds
# an archive signal by when its document became public (the lead is a pure function of the
# archived document), every other origin by when Atlas first saw the lead.
_IN_THEME = """
    WHERE (CAST(:theme AS text) IS NULL OR EXISTS (
        SELECT 1 FROM lead_sighting s
        JOIN discovery_query q ON q.id = s.discovery_query_id
        JOIN discovery d ON d.id = q.discovery_id
        WHERE s.lead_id = lead.id AND d.theme = :theme)
    OR EXISTS (
        SELECT 1 FROM tradingview_headline t WHERE t.lead_id = lead.id AND :theme = ANY(t.themes))
    OR :theme = ANY(COALESCE(ce.themes, ARRAY[]::text[]))
    OR :theme = ANY(COALESCE(sig.themes, ARRAY[]::text[])))
    AND (CAST(:origin AS text) IS NULL OR lead.origin = :origin)
    AND (CAST(:company_id AS uuid) IS NULL
        OR COALESCE(sig.company_id, h.company_id, ce.company_id, f.company_id) = :company_id)
    AND (CAST(:known_by AS timestamptz) IS NULL
        OR CASE WHEN lead.origin = 'archive_signal' THEN sa.available_at
                ELSE lead.first_seen_at END <= :known_by)
    AND (CAST(:available_from AS timestamptz) IS NULL OR sa.available_at >= :available_from)
    AND (CAST(:event_from AS timestamptz) IS NULL OR co.event_at >= :event_from)
    AND (CAST(:event_to AS timestamptz) IS NULL OR co.event_at <= :event_to)
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
        k: v
        for k, v in row.items()
        if k not in _HEADLINE_COLUMNS and not k.startswith(("filing_", "calendar_", "signal_"))
    }
    calendar = None
    if row["calendar_event_at"] is not None:
        calendar = CalendarEvent.model_validate(
            {k.removeprefix("calendar_"): v for k, v in row.items() if k.startswith("calendar_")}
        )
    filing = None
    if row["filing_cik"] is not None:
        filing = Filing.model_validate(
            {k.removeprefix("filing_"): v for k, v in row.items() if k.startswith("filing_")}
        )
    signal = None
    if row["signal_source_version_id"] is not None:
        signal = Signal.model_validate(
            {k.removeprefix("signal_"): v for k, v in row.items() if k.startswith("signal_")}
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
    return Lead.model_validate(
        {
            **fields,
            "headline": headline,
            "filing": filing,
            "calendar": calendar,
            "signal": signal,
        }
    )


def list_leads(
    connection: Connection,
    *,
    theme: str | None,
    limit: int,
    offset: int,
    origin: str | None = None,
    known_by: datetime | None = None,
    event_from: datetime | None = None,
    event_to: datetime | None = None,
    company_id: uuid.UUID | None = None,
    available_from: datetime | None = None,
) -> tuple[list[Lead], int]:
    """Leads, newest first (optionally only those a discovery for `theme` returned, or a
    headline, calendar date or archive signal of a company in it), and how many there are in
    all. The archive signals (`origin="archive_signal"`) are ranked instead: highest score
    first, then the latest document.

    `origin` keeps one origin; `company_id` the leads of one company (a headline's, a calendar
    date's, a filing's or a signal's). `known_by` keeps the leads Atlas had stored by then
    (their `last_seen_at` is capped at it) and a calendar lead shows the date it knew by then;
    a lead's `sightings` count is not bounded by it. For an archive signal `known_by` is when
    its document became public, and `available_from` keeps the archive signals whose document
    became public from then on. `event_from`/`event_to` keep the calendar leads whose date (as
    known by `known_by`) falls inside, soonest first.
    """
    params = {
        "theme": theme,
        "origin": origin,
        "company_id": company_id,
        "available_from": available_from,
        "known_by": known_by,
        "event_from": event_from,
        "event_to": event_to,
    }
    total = connection.execute(
        text(f"SELECT count(*) {_LEAD_JOINS} {_IN_THEME}"),
        params,
    ).scalar_one()
    windowed = event_from is not None or event_to is not None
    order = "co.event_at, lead.id" if windowed else "lead.first_seen_at DESC, lead.id"
    if origin == "archive_signal":
        order = "sig.score DESC, sa.available_at DESC, lead.id"
    rows = connection.execute(
        text(f"{_LEADS} {_IN_THEME} ORDER BY {order} LIMIT :limit OFFSET :offset"),
        {**params, "limit": limit, "offset": offset},
    ).mappings()
    return [_lead(row) for row in rows], int(total)
