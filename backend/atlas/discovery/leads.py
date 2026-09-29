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
"""

import uuid
from datetime import date, datetime
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel
from sqlalchemy import Connection, text

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


class Lead(BaseModel):
    id: uuid.UUID
    tier: Literal["C"]  # always: a lead is never Evidence
    canonical_url: str
    url: str  # as first found
    title: str
    snippet: str
    published_date: date | None  # the search result's, when it gave one
    engines: list[str]  # every engine that has returned it
    query: str  # the query that first found it
    theme: str  # the theme of the discovery that first found it
    sightings: int  # how many query results have returned it
    first_seen_at: datetime
    last_seen_at: datetime


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


_LEADS = """
    SELECT lead.id, lead.tier, lead.canonical_url, lead.url, lead.title, lead.snippet,
        lead.published_date, lead.engines, lead.first_seen_at, lead.last_seen_at,
        first.query, discovery.theme,
        (SELECT count(*) FROM lead_sighting s WHERE s.lead_id = lead.id) AS sightings
    FROM lead
    JOIN discovery_query first ON first.id = lead.first_query_id
    JOIN discovery ON discovery.id = first.discovery_id
"""
# A lead belongs to a theme when a discovery for that theme has returned it.
_IN_THEME = """
    WHERE CAST(:theme AS text) IS NULL OR EXISTS (
        SELECT 1 FROM lead_sighting s
        JOIN discovery_query q ON q.id = s.discovery_query_id
        JOIN discovery d ON d.id = q.discovery_id
        WHERE s.lead_id = lead.id AND d.theme = :theme)
"""


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
    return [Lead.model_validate(dict(row)) for row in rows], int(total)
