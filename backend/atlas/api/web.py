"""Primary sources beyond filings (Chokepoint Watch, W3 phase 1).

- `GET /web-search?q=&theme=&session_id=&published_by=&limit=`: a SearXNG search (the configured
  engines and language). Each result is stored as a `searxng` lead (title, URL, snippet,
  publication date when the engine gives one; one lead per canonical URL, as a discovery's) and
  returned with its lead id. `published_by` leaves out, and does not store, a result that dates
  itself after that day. A lead is where to look, never Evidence.
- `GET /filing-search?q=&forms=&start=&end=&theme=&session_id=&limit=`: EDGAR full-text search
  over every filer (the SEC User-Agent and rate limit of `atlas.discovery.edgar_fts`). `q` is an
  exact phrase (several, each in double quotes, must all match), `forms` a comma-separated list
  (default 10-K, 10-Q, 8-K, 20-F, 6-K, 40-F), the window filing dates (default: the year to
  `end`, which defaults to today). Each hit is stored as an `edgar_fts` lead with its filing and
  returned with its lead id. No one-word rule applies: the caller asked for it.
- `POST /sources/fetch {company | company_name (+ cik | lei) | publisher, url, published_at?}`:
  fetch one page into the archive through the fetch gate (`atlas.ledger.web_fetch`) and record
  it as a Source Version of provider `web`, for a company Atlas has (slug), a company by name
  (a counterparty created if need be; W9) or the page's publisher. Blocked: 403
  `fetch_blocked` with the gate that blocked it, and the decision is recorded.

`session_id` (the MCP tools pass it) is recorded on the search and gives it the session's theme.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import Engine, text

from atlas.api.common import ErrorResponses, error_response, error_responses, not_found
from atlas.discovery.adhoc import (
    FilingSearchResult,
    SearchError,
    WebSearchResult,
    filing_search,
    web_search,
)
from atlas.discovery.edgar_fts import FORMS, EdgarFullTextSearch, filing_phrases
from atlas.discovery.searxng import SearXNGClient
from atlas.ledger.web_fetch import (
    FetchedPage,
    WebFetchBlocked,
    WebFetchFailed,
    WebFetchOff,
    WebFetchRefused,
    fetch_page,
)
from atlas.settings import Settings

SEARCH_FAILURES: ErrorResponses = error_responses(404, 422, 502, 503)
FETCH_FAILURES: ErrorResponses = error_responses(403, 404, 422, 502, 503)
DEFAULT_WINDOW_DAYS = 365


class FetchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str | None = Field(
        default=None, min_length=1, description="the slug of a company Atlas has"
    )
    company_name: str | None = Field(
        default=None,
        min_length=1,
        description="instead of `company`: a company by name, resolved through SEC and GLEIF (a"
        " counterparty company is created for one outside the universe)",
    )
    cik: str | None = Field(
        default=None, description="with `company_name`: its SEC CIK, which decides the company"
    )
    lei: str | None = Field(
        default=None, description="with `company_name`: its LEI, when it has no CIK"
    )
    publisher: bool = Field(
        default=False,
        description="instead of a company: the page is no company's (a government or regulator"
        " notice); its publisher, the site register's for the site, is its company",
    )
    url: str = Field(min_length=1)
    published_at: AwareDatetime | None = Field(
        default=None,
        description="when the page became public, if you know (with its UTC offset); else its"
        " own date (if within a week before the fetch), else the fetch time",
    )
    session_id: uuid.UUID | None = Field(
        default=None,
        description="the research session asking: a page fetched after a session's as-of time is"
        " read only by the session that fetched it",
    )


def web_router(engine: Engine, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["sources"])

    def session_theme(session_id: uuid.UUID | None, theme: str | None) -> str | JSONResponse | None:
        """The theme to record: the session's, else the caller's; a 404 for an unknown session."""
        if session_id is None:
            return theme
        with engine.connect() as connection:
            found = connection.execute(
                text("SELECT theme FROM research_session WHERE id = :id"), {"id": session_id}
            ).scalar_one_or_none()
        return not_found("research session") if found is None else found

    @router.get("/web-search", response_model=WebSearchResult, responses=SEARCH_FAILURES)
    def search_web(  # pyright: ignore[reportUnusedFunction]
        q: Annotated[str, Query(min_length=1, description="the search query")],
        theme: Annotated[str | None, Query(description="the theme the leads belong to")] = None,
        session_id: Annotated[uuid.UUID | None, Query()] = None,
        published_by: Annotated[
            date | None,
            Query(description="leave out results that date themselves after this day"),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> WebSearchResult | JSONResponse:
        owner = session_theme(session_id, theme)
        if isinstance(owner, JSONResponse):
            return owner
        client = SearXNGClient.from_settings(settings)
        if client is None:
            return error_response(503, "web_search_disabled", "ATLAS_SEARXNG_URL is not set")
        try:
            with client:
                return web_search(
                    engine,
                    client,
                    query=q.strip(),
                    theme=owner,
                    session_id=session_id,
                    published_by=published_by,
                    limit=limit,
                )
        except SearchError as error:
            return error_response(502, "search_failed", str(error))

    @router.get("/filing-search", response_model=FilingSearchResult, responses=SEARCH_FAILURES)
    def search_filings(  # pyright: ignore[reportUnusedFunction]
        q: Annotated[
            str,
            Query(
                min_length=1,
                description="an exact phrase; or several, each in double quotes (all must match)",
            ),
        ],
        forms: Annotated[
            str | None, Query(description="comma-separated form types (default: the 10-K family)")
        ] = None,
        start: Annotated[
            date | None, Query(description="first filing date (default: a year back)")
        ] = None,
        end: Annotated[date | None, Query(description="last filing date (default: today)")] = None,
        theme: Annotated[str | None, Query(description="the theme the leads belong to")] = None,
        session_id: Annotated[uuid.UUID | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> FilingSearchResult | JSONResponse:
        phrases = filing_phrases(q)
        if not phrases:
            return error_response(422, "invalid_request", "q holds no phrase")
        last = end or datetime.now(UTC).date()
        first = start or last - timedelta(days=DEFAULT_WINDOW_DAYS)
        if first > last:
            return error_response(
                422, "invalid_window", f"the window starts ({first}) after it ends ({last})"
            )
        form_list = [each.strip() for each in (forms or "").split(",") if each.strip()]
        owner = session_theme(session_id, theme)
        if isinstance(owner, JSONResponse):
            return owner
        client = EdgarFullTextSearch.from_settings(
            settings, max_hits=limit, forms=form_list or FORMS
        )
        if client is None:
            return error_response(
                503,
                "filing_search_disabled",
                "EDGAR full-text search needs ATLAS_SEC_USER_AGENT and ATLAS_DISCOVERY_EDGAR_FTS"
                " not off",
            )
        try:
            return filing_search(
                engine,
                client,
                phrases=phrases,
                start=first,
                end=last,
                theme=owner,
                session_id=session_id,
                filing_phrase=q.strip(),
            )
        except SearchError as error:
            return error_response(502, "search_failed", str(error))

    @router.post("/sources/fetch", response_model=FetchedPage, responses=FETCH_FAILURES)
    def fetch_source(request: FetchRequest) -> FetchedPage | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            return fetch_page(
                settings,
                company=request.company,
                company_name=request.company_name,
                cik=request.cik,
                lei=request.lei,
                publisher=request.publisher,
                url=request.url,
                published_at=request.published_at,
                session_id=request.session_id,
            )
        except WebFetchRefused as refused:
            status = {
                "unknown_company": 404,
                "unknown_session": 404,
                "url_belongs_to_other_company": 409,
            }.get(refused.code, 422)
            return error_response(status, refused.code, str(refused), refused.detail or None)
        except WebFetchBlocked as blocked:
            return error_response(
                403,
                "fetch_blocked",
                f"the fetch gate blocked it: {blocked.decision.reason}",
                {
                    "blocked_by": blocked.decision.blocked_by,
                    "reason": blocked.decision.reason,
                    "site": blocked.decision.site,
                    "url": blocked.decision.url,
                    "gate_decision_id": str(blocked.decision_id),
                },
            )
        except WebFetchFailed as failed:
            return error_response(
                502, "fetch_failed", str(failed), {"status": failed.status, "url": failed.url}
            )
        except WebFetchOff as off:
            return error_response(
                503,
                "web_fetch_off",
                "the site is allowed but Atlas has no way to request it (ATLAS_EXCHANGE_LIVE"
                f" is off and there are no recorded pages): {off}",
            )

    return router
