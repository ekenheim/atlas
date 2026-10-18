"""Fetching a web page into the archive (Chokepoint Watch, W3): `atlas sources fetch`.

A company's own investor-relations or press page, a deck or slides (a PDF), or a page of
another site the register allows becomes a Source Version of provider `web`, so Atlas can quote
it as a Fact. One page per call, synchronous (the caller needs the Source Version and its
`available_at` in the answer; there is no job):

1. **The gate.** Every request, the page and each redirect hop, passes the fetch gate
   (`atlas.sources.gate`): the site must be in the register (`configs/sources/sites.yaml`) with
   terms that allow automation, and robots.txt must allow the path. Otherwise the decision is
   recorded `blocked` (`GET /api/v1/companies/{id}/fetch-gate-decisions?status=blocked`,
   audited) and nothing is requested from the site. A redirect is followed by hand, gate first:
   the site register is never bypassed by a 301 to another host.
2. **The bytes** are archived as served; HTML and PDF are parsed by the ledger's parser (any
   other type is refused before it is archived).
3. **`available_at` is never before Atlas had the page**: the `published_at` the call was given
   (basis `publisher_timestamp`); else the publication date the page's own HTML claims
   (`atlas.sources.web_dates`: `article:published_time`, or JSON-LD of an Article), but only when
   it is no later than the fetch and no more than seven days before it (basis
   `page_published_date`; `date_source` says which tag); else the fetch time (basis
   `observed_discovery`), with any older or later date the page claimed kept as written
   (`metadata.web.date_as_written`). A page is read by a session as of an earlier time only if
   that session fetched it (`session_id`, kept on the fetch observation; `atlas.mcp.tools`).
4. **The tier** is A when the site is the company's own (the register's `own_site_of`;
   `public_issuer`), else B (the register's `license_class` for the site, else `third_party`).
   A URL already in the ledger for another company is refused (`url_belongs_to_other_company`).
5. The new version joins its Evidence Family (the ledger does it); the same bytes again make no
   new version (`unchanged`, a fetch observation only), different bytes a new one available
   from the fetch (`observed_revision`), as for any revised document. When Hindsight is
   configured, a new English version is retained.

Requests are live only with `ATLAS_EXCHANGE_LIVE` (the generic `ATLAS_EXCHANGE_USER_AGENT`,
the site's rate); otherwise the pages replay from `ATLAS_EXCHANGE_FIXTURES_DIR/<company
slug>/manifest.json` (the gate applies to replays as to live requests); with neither, a page
the register allows is `web_fetch_off`.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from types import TracebackType
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from pydantic import BaseModel
from sqlalchemy import Engine, text

from atlas.archive import Archive, open_archive
from atlas.audit import Actor
from atlas.companies import extend_universe, load_universe, seed
from atlas.db import create_engine
from atlas.ledger.exchange_ingest import site_client
from atlas.ledger.gates import record_decision
from atlas.ledger.service import RecordedFetch, SourceLedger, web_canonical_url
from atlas.parsing import PDF_MEDIA_TYPES
from atlas.retention.service import enqueue_retains
from atlas.settings import Settings
from atlas.sources import FetchedDocument, HttpValidators, SourceCandidate, WebPage
from atlas.sources.adapter import AvailabilityBasis, FetchAttempt, FetchError, WebDateSource
from atlas.sources.gate import (
    FetchGate,
    GateDecision,
    SiteConfig,
    SiteRegister,
    SiteRegisterError,
    load_site_register,
)
from atlas.sources.sec_http import HttpResult, SecHttpClient
from atlas.sources.web_dates import page_date, page_title

PROVIDER_ID = "web"
MAX_REDIRECTS = 5
PAGE_DATE_WINDOW = timedelta(days=7)  # a page's own date is believed this far back
MAX_BYTES = 30 * 1024 * 1024
_HTML = frozenset({"text/html", "application/xhtml+xml"})
_UNTYPED = frozenset({"", "application/octet-stream", "binary/octet-stream"})


class WebFetchRefused(ValueError):
    """The call's arguments, or the page, cannot be recorded; `code` says why. Nothing was
    recorded (a blocked fetch is `WebFetchBlocked`)."""

    def __init__(self, code: str, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


class WebFetchBlocked(Exception):
    """The fetch gate blocked the URL (or a redirect's target); the decision is recorded."""

    def __init__(self, decision: GateDecision, decision_id: uuid.UUID) -> None:
        super().__init__(f"{decision.url} blocked by {decision.blocked_by}: {decision.reason}")
        self.decision = decision
        self.decision_id = decision_id


class WebFetchFailed(Exception):
    """The site was asked and did not give a page (an HTTP error, no connection)."""

    def __init__(self, message: str, *, url: str, status: int | None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class WebFetchOff(Exception):
    """The register allows the site, but Atlas has no way to request it: neither
    `ATLAS_EXCHANGE_LIVE` nor recorded pages for the company."""


class FetchedPage(BaseModel):
    outcome: str  # new_version, unchanged or not_modified
    company: str  # the slug
    company_id: uuid.UUID
    url: str  # as asked
    final_url: str  # after the redirects the gate allowed
    canonical_url: str  # the Source Document's identity
    source_document_id: uuid.UUID
    source_version_id: uuid.UUID
    observation_id: uuid.UUID
    available_at: datetime  # the version's effective availability
    available_at_basis: str  # publisher_timestamp, page_published_date, observed_discovery, ...
    date_source: str | None  # argument, article_published_time, json_ld, fetch_time
    date_as_written: str | None  # the date as given or as the page claimed it, believed or not
    tier: str
    license_class: str
    site: str
    media_type: str
    title: str
    gate_decision_id: uuid.UUID | None
    retain_jobs: list[str] | None  # None when Hindsight isn't configured


class _LazyClient:
    """An HTTP client built when first used, so a URL the register or the terms block needs no
    fixtures or network, and closed with the fetch."""

    def __init__(self, make: Callable[[], SecHttpClient]) -> None:
        self._make = make
        self._client: SecHttpClient | None = None

    def client(self) -> SecHttpClient:
        if self._client is None:
            self._client = self._make()
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def __aenter__(self) -> "_LazyClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()


def _error(message: str, url: str, status: int | None) -> FetchError:
    attempt = FetchAttempt(attempt=1, status=status, error=message)
    return FetchError(message, url=url, status=status, retryable=False, attempts=(attempt,))


async def _follow(
    lazy: _LazyClient,
    url: str,
    validators: HttpValidators | None,
    before: Callable[[str], Awaitable[None]],
) -> tuple[HttpResult, str]:
    """GET `url`, following up to `MAX_REDIRECTS` redirects by hand: `before(url)` is awaited
    ahead of every request (the page's, and each hop's) and may raise to stop; the client is
    built only after it has not. Returns the result and the URL it came from."""
    for hop in range(MAX_REDIRECTS + 1):
        await before(url)
        result = await lazy.client().get(url, validators if hop == 0 else None)
        if 300 <= result.status < 400 and result.status != 304:
            if not result.location:
                raise _error(
                    f"GET {url} returned {result.status} with no Location", url, result.status
                )
            url = urljoin(url, result.location)
            continue
        return result, url
    raise _error(f"GET {url}: more than {MAX_REDIRECTS} redirects", url, None)


class _RobotsGetter:
    """What the gate reads robots.txt through: redirects are followed (RFC 9309) but only to
    a host of a site the register allows (automation allowed, or a recorded consent); any other
    target is an unreachable robots.txt, which disallows everything."""

    def __init__(self, lazy: _LazyClient, register: SiteRegister) -> None:
        self._lazy = lazy
        self._register = register

    async def get(self, url: str, validators: HttpValidators | None = None) -> HttpResult:
        async def known(target: str) -> None:
            found = self._register.site_for(target)
            site = found[1] if found else None
            if site is None or not (site.automation == "allowed" or site.consent is not None):
                raise _error(
                    f"robots.txt redirects to a host the register bars: {target}", url, None
                )

        result, _ = await _follow(self._lazy, url, validators, known)
        return result


def _media_type(declared: str | None, content: bytes) -> str:
    kind = (declared or "").lower()
    if kind in _HTML or kind in PDF_MEDIA_TYPES:
        return "application/pdf" if kind in PDF_MEDIA_TYPES else kind
    head = content[:2048].lstrip().lower()
    if content[:5] == b"%PDF-":
        return "application/pdf"
    if kind in _UNTYPED and (head.startswith((b"<!doctype html", b"<html")) or b"<html" in head):
        return "text/html"
    raise WebFetchRefused(
        "unsupported_media_type",
        f"only HTML and PDF pages are archived, not {declared or 'an untyped body'}",
        media_type=declared,
    )


def _title(url: str, media_type: str, content: bytes) -> str:
    if media_type in _HTML:
        found = page_title(content)
        if found:
            return found
    name = PurePosixPath(unquote(urlsplit(url).path)).name
    return name or urlsplit(url).hostname or url


class _Availability(BaseModel):
    available_at: datetime
    basis: AvailabilityBasis
    source: WebDateSource
    written: str | None  # the date as given, or as the page claimed it (believed or not)
    page_tag: str | None  # the tag the page's own date was found in, if it had one


def _availability(
    media_type: str, content: bytes, published_at: datetime | None, fetched_at: datetime
) -> _Availability:
    """When the page became public, never before Atlas had it (module docstring, 3)."""
    if published_at is not None:
        return _Availability(
            available_at=published_at,
            basis="publisher_timestamp",
            source="argument",
            written=published_at.isoformat(),
            page_tag=None,
        )
    found = page_date(content) if media_type in _HTML else None
    if found is not None and fetched_at - PAGE_DATE_WINDOW <= found.moment <= fetched_at:
        return _Availability(
            available_at=found.moment,
            basis="page_published_date",
            source=found.source,
            written=found.written,
            page_tag=found.source,
        )
    return _Availability(
        available_at=fetched_at,
        basis="observed_discovery",
        source="fetch_time",
        written=found.written if found else None,
        page_tag=found.source if found else None,
    )


def fetch_page(
    settings: Settings,
    *,
    company: str,
    url: str,
    published_at: datetime | None = None,
    session_id: uuid.UUID | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FetchedPage:
    """Fetch `url` for `company` (a slug) into the ledger (see the module); `session_id` is the
    research session asking, kept on the fetch observation. Raises
    `WebFetchRefused`, `WebFetchBlocked`, `WebFetchFailed` or `WebFetchOff`."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebFetchRefused("invalid_url", f"the URL must be an http(s) URL, not {url!r}")
    if published_at is not None:
        if published_at.tzinfo is None:
            raise WebFetchRefused(
                "invalid_published_at", "the publication time needs its UTC offset"
            )
        if published_at > now():
            raise WebFetchRefused("invalid_published_at", "the publication time is in the future")
    try:
        register = load_site_register(settings.source_sites_config)
    except SiteRegisterError as error:
        raise WebFetchRefused("site_register_invalid", str(error)) from None
    actor = Actor.from_settings(settings)
    engine = create_engine(settings)
    try:
        company_id = _company_id(engine, actor, settings, company)
        if session_id is not None:
            with engine.connect() as connection:
                known = connection.execute(
                    text("SELECT 1 FROM research_session WHERE id = :id"), {"id": session_id}
                ).scalar_one_or_none()
            if known is None:
                raise WebFetchRefused("unknown_session", "no such research session")
        archive = open_archive(settings)
        return asyncio.run(
            _fetch(
                settings,
                engine,
                archive,
                register,
                actor,
                company,
                company_id,
                url.strip(),
                published_at,
                session_id,
                now,
            )
        )
    finally:
        engine.dispose()


def _company_id(engine: Engine, actor: Actor, settings: Settings, slug: str) -> uuid.UUID:
    universe = load_universe(settings.themes_config)
    with engine.begin() as connection:
        universe = extend_universe(connection, universe)
        if slug in universe.companies:
            (seeded,) = seed(connection, actor, universe, [slug])
            return seeded.company_id
        found = connection.execute(
            text("SELECT id FROM company WHERE slug = :slug"), {"slug": slug}
        ).scalar_one_or_none()
    if found is None:
        raise WebFetchRefused("unknown_company", f"no company has the slug {slug!r}")
    return found


async def _fetch(
    settings: Settings,
    engine: Engine,
    archive: Archive,
    register: SiteRegister,
    actor: Actor,
    slug: str,
    company_id: uuid.UUID,
    url: str,
    published_at: datetime | None,
    session_id: uuid.UUID | None,
    now: Callable[[], datetime],
) -> FetchedPage:
    found = register.site_for(url)
    _refuse_another_companys(engine, url, slug, company_id)
    rate_site = found[0] if found else "web"

    def make() -> SecHttpClient:
        try:
            return site_client(
                settings, register, rate_site, slug, follow_redirects=False, max_attempts=3
            )
        except FileNotFoundError as error:
            raise WebFetchOff(str(error)) from None

    decided: list[tuple[GateDecision, uuid.UUID]] = []

    def log(decision: GateDecision) -> uuid.UUID:
        decision_id = record_decision(
            engine,
            actor,
            decision,
            provider=PROVIDER_ID,
            purpose="document",
            company_id=company_id,
            job_id=None,
        )
        decided.append((decision, decision_id))
        return decision_id

    ledger = SourceLedger(
        engine,
        archive,
        actor,
        max_hamming_distance=settings.evidence_family_max_hamming_distance,
    )
    asked_at = now()
    provisional = _candidate(
        slug,
        url,
        url,
        asked_at,
        _Availability(
            available_at=asked_at,
            basis="observed_discovery",
            source="fetch_time",
            written=None,
            page_tag=None,
        ),
        None,
        found,
    )
    validators = ledger.validators_for(provisional)
    async with _LazyClient(make) as lazy:
        gate = FetchGate(register, _RobotsGetter(lazy, register), archive=archive)

        async def before(target: str) -> None:
            decision = await gate.check(target)
            decision_id = log(decision)
            if decision.status == "blocked":
                raise WebFetchBlocked(decision, decision_id)

        try:
            result, final_url = await _follow(lazy, url, validators, before)
        except FetchError as error:
            raise WebFetchFailed(str(error), url=error.url, status=error.status) from None
    gate_decision_id = decided[-1][1] if decided else None
    fetched_at = now()
    content = result.content
    if len(content) > MAX_BYTES:
        raise WebFetchRefused(
            "too_large", f"the page is {len(content)} bytes; the limit is {MAX_BYTES}"
        )
    media_type = "text/html" if result.not_modified else _media_type(result.media_type, content)
    availability = _availability(
        media_type, b"" if result.not_modified else content, published_at, fetched_at
    )
    title = final_url if result.not_modified else _title(final_url, media_type, content)
    _refuse_another_companys(engine, final_url, slug, company_id)
    candidate = _candidate(
        slug,
        final_url,
        title,
        fetched_at,
        availability,
        decided[-1][0].reason if decided else None,
        register.site_for(final_url),
    )
    fetched = FetchedDocument(
        candidate=candidate.model_copy(update={"validators": validators}),
        url=final_url,
        fetched_at=fetched_at,
        not_modified=result.not_modified,
        content=content,
        media_type=None if result.not_modified else media_type,
        validators=result.validators,
        attempts=result.attempts,
    )
    recorded = ledger.record(
        fetched, company_id=company_id, gate_decision_id=gate_decision_id, session_id=session_id
    )
    retain_jobs = (
        enqueue_retains(
            engine,
            [recorded.source_version_id] if recorded.outcome == "new_version" else [],
            actor=actor,
        )
        if settings.hindsight_url
        else None
    )
    return _page(engine, recorded, slug, company_id, url, final_url, gate_decision_id, retain_jobs)


def _refuse_another_companys(engine: Engine, url: str, slug: str, company_id: uuid.UUID) -> None:
    """A page is one Source Document, which belongs to the company it was first fetched for;
    fetching it for another is refused, not silently kept under the first."""
    with engine.connect() as connection:
        owner = connection.execute(
            text(
                "SELECT d.company_id, c.slug FROM source_document d"
                " LEFT JOIN company c ON c.id = d.company_id"
                " WHERE d.provider = :provider AND d.canonical_url = :url"
            ),
            {"provider": PROVIDER_ID, "url": web_canonical_url(url)},
        ).one_or_none()
    if owner is not None and owner.company_id is not None and owner.company_id != company_id:
        raise WebFetchRefused(
            "url_belongs_to_other_company",
            f"that page is already in the ledger for {owner.slug}, not {slug}",
            company=owner.slug,
        )


def _candidate(
    slug: str,
    url: str,
    title: str,
    discovered_at: datetime,
    availability: _Availability,
    gate_reason: str | None,
    found: tuple[str, SiteConfig] | None,
) -> SourceCandidate:
    site_name, site = found if found else ("unregistered", None)
    own_site = site is not None and slug in site.own_site_of
    available_at, basis = availability.available_at, availability.basis
    return SourceCandidate(
        provider_id=PROVIDER_ID,
        kind="web_page",
        url=url,
        title=title,
        discovered_at=discovered_at,
        available_at=available_at,
        available_at_basis=basis,
        web=WebPage(
            publisher=site.publisher if site else urlsplit(url).hostname or url,
            site=site_name,
            own_site=own_site,
            license_class="public_issuer"
            if own_site
            else (site.license_class if site and site.license_class else "third_party"),
            date_source=availability.source,
            date_as_written=availability.written,
            page_date_tag=availability.page_tag,
            gate_reason=gate_reason,
        ),
    )


def _page(
    engine: Engine,
    recorded: RecordedFetch,
    slug: str,
    company_id: uuid.UUID,
    url: str,
    final_url: str,
    gate_decision_id: uuid.UUID | None,
    retain_jobs: list[str] | None,
) -> FetchedPage:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT a.available_at, a.available_at_basis, v.media_type, v.metadata,"
                " d.canonical_url, d.source_tier, d.title, d.license_class"
                " FROM source_version v JOIN source_document d ON d.id = v.source_document_id"
                " JOIN source_version_availability a ON a.source_version_id = v.id"
                " WHERE v.id = :id"
            ),
            {"id": recorded.source_version_id},
        ).one()
    web: dict[str, Any] = row.metadata.get("web") or {}
    return FetchedPage(
        outcome=recorded.outcome,
        company=slug,
        company_id=company_id,
        url=url,
        final_url=final_url,
        canonical_url=row.canonical_url,
        source_document_id=recorded.source_document_id,
        source_version_id=recorded.source_version_id,
        observation_id=recorded.observation_id,
        available_at=row.available_at,
        available_at_basis=row.available_at_basis,
        date_source=web.get("date_source"),
        date_as_written=web.get("date_as_written"),
        license_class=row.license_class,
        tier=row.source_tier,
        site=str(web.get("site", "")),
        media_type=row.media_type,
        title=row.title,
        gate_decision_id=gate_decision_id,
        retain_jobs=retain_jobs,
    )


__all__ = [
    "MAX_BYTES",
    "FetchedPage",
    "WebFetchBlocked",
    "WebFetchFailed",
    "WebFetchOff",
    "WebFetchRefused",
    "fetch_page",
    "web_canonical_url",
]
