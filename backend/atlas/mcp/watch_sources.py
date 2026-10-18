"""The Atlas MCP server's tools for primary sources beyond filings (Chokepoint Watch, W3):
`filing_search`, `web_search` and `fetch_page`.

Each is a projection of one route (`GET /filing-search`, `GET /web-search`, `POST
/sources/fetch`) bound by the session's as-of time, which no tool takes as an argument. All three
refuse an isolated session before they do anything (`refuse_isolated`: the early-call
scorecard's sessions see what they saw before these tools existed), and none is on the frozen
prompt's list; Atlas enforces it.

- `filing_search` clamps `end` to the session's as-of date; a window that starts after it is
  refused. Results are `edgar_fts` leads: where to look, never a Fact.
- `web_search` leaves out results that date themselves after the as-of date; a result with no
  date cannot be bounded and is a lead like the rest.
- `fetch_page` archives a page through the fetch gate. A page whose `available_at` is after the
  as-of time is recorded, but the session cannot read it (`readable: false`; `read` refuses it
  as `available_after_as_of`): a page with no date of its own is available when fetched, so a
  session as of an earlier time never reads it.

Registered by importing this module (`atlas.mcp`'s package init).
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import Field

from atlas.mcp.api import Refusal, rows
from atlas.mcp.tools import Bound, Ctx, tool

LEAD_NOTE = (
    "Leads, stored with their ids: where to look, never a Fact and never Evidence. To use a"
    " page or a filing, get it into the archive (`fetch_page`, or Atlas's own ingest) and read"
    " it there; record a Fact only from text you read in the archive."
)
WINDOW_DAYS = 365


class FilingSearchArgs(Bound):
    query: str = Field(
        min_length=1,
        description="an exact phrase in the filings' text; several, each in double quotes, must"
        ' all match (e.g. "indium phosphide" "sole source")',
    )
    forms: list[str] = Field(
        default_factory=list[str],
        description="form types to search (default 10-K, 10-Q, 8-K, 20-F, 6-K, 40-F)",
    )
    start: date | None = Field(default=None, description="first filing date; default a year back")
    end: date | None = Field(
        default=None, description="last filing date; never later than the session's as-of date"
    )
    limit: int = Field(default=20, ge=1, le=100)


@tool(
    "filing_search",
    "EDGAR full-text search over every filer: the filings (10-K, 10-Q, 8-K, 20-F, 6-K, 40-F by"
    " default) whose text holds an exact phrase, filed in a window that ends no later than the"
    " session's as-of date. Each hit is stored as a lead and returned with its lead id, filer,"
    " CIK, form, filing date and whether Atlas has the filing in its archive (`version_id`)."
    " Leads only: no text comes back.",
    FilingSearchArgs,
)
async def filing_search(ctx: Ctx, args: FilingSearchArgs) -> dict[str, Any]:
    ctx.refuse_isolated("filing_search")
    bound = ctx.as_of.astimezone(UTC).date()
    end = min(args.end or bound, bound)
    start = args.start or end - timedelta(days=WINDOW_DAYS)
    if start > bound:
        raise Refusal(
            "window_after_as_of",
            "the window starts after the session's as-of date",
            start=start.isoformat(),
            as_of=ctx.as_of_iso,
        )
    if start > end:
        raise Refusal("invalid_window", "the window starts after it ends")
    answer = await ctx.api.get(
        "/filing-search",
        q=args.query,
        forms=",".join(args.forms) if args.forms else None,
        start=start.isoformat(),
        end=end.isoformat(),
        session_id=str(args.session_id),
        limit=args.limit,
    )
    return {
        "query": answer.get("query"),
        "forms": answer.get("forms"),
        "window": {
            "start": answer.get("start"),
            "end": answer.get("end"),
            "clamped_to_as_of": args.end is not None and args.end > bound,
        },
        "as_of": ctx.as_of_iso,
        "total": answer.get("total"),
        "new_leads": answer.get("new_leads"),
        "hits": [
            {
                "lead_id": hit.get("lead_id"),
                "filer": hit.get("filer"),
                "cik": hit.get("cik"),
                "ticker": hit.get("ticker"),
                "company": hit.get("company"),
                "form": hit.get("form"),
                "document_type": hit.get("file_type"),
                "filed": hit.get("file_date"),
                "period_ending": hit.get("period_ending"),
                "accession": hit.get("accession"),
                "url": hit.get("url"),
                "version_id": hit.get("source_version_id"),
                "ingestable": hit.get("ingestable"),
                "new": hit.get("new"),
            }
            for hit in rows(answer.get("results"))
        ],
        "note": LEAD_NOTE,
    }


class WebSearchArgs(Bound):
    query: str = Field(min_length=1, description="the search query")
    limit: int = Field(default=10, ge=1, le=50)


@tool(
    "web_search",
    "Search the web (SearXNG; the configured engines). Each result is stored as a lead, one per"
    " canonical URL, and returned with its lead id, title, URL, snippet and publication date"
    " when the engine gives one. A result that dates itself after the session's as-of date is"
    " left out; one with no date cannot be bounded and is only a lead. Leads only: no page text"
    " comes back.",
    WebSearchArgs,
)
async def web_search(ctx: Ctx, args: WebSearchArgs) -> dict[str, Any]:
    ctx.refuse_isolated("web_search")
    bound = ctx.as_of.astimezone(UTC).date()
    answer = await ctx.api.get(
        "/web-search",
        q=args.query,
        session_id=str(args.session_id),
        published_by=bound.isoformat(),
        limit=args.limit,
    )
    return {
        "query": answer.get("query"),
        "engines": answer.get("engines"),
        "as_of": ctx.as_of_iso,
        "total": answer.get("total"),
        "new_leads": answer.get("new_leads"),
        "dropped_after_as_of": answer.get("dropped_after_bound"),
        "unresponsive_engines": answer.get("unresponsive_engines"),
        "results": [
            {
                "lead_id": each.get("lead_id"),
                "title": each.get("title"),
                "url": each.get("url"),
                "snippet": each.get("snippet"),
                "published": each.get("published_date"),
                "engines": each.get("engines"),
                "new": each.get("new"),
            }
            for each in rows(answer.get("results"))
        ],
        "note": LEAD_NOTE,
    }


class FetchPageArgs(Bound):
    company: str = Field(min_length=1, description="the company's slug the page is about")
    url: str = Field(min_length=1, description="the page's URL (HTML or PDF)")


@tool(
    "fetch_page",
    "Fetch one web page (HTML or a PDF: a company's investor-relations or press page, a deck)"
    " into Atlas's archive as a Source Version, so you can `read` it and record Facts from it."
    " The site must be in Atlas's site register with terms that allow automation, and its"
    " robots.txt must allow the path; otherwise the call is refused (`fetch_blocked`) and"
    " nothing is requested. Tier A when the site is the company's own, else B. `available_at`"
    " is the page's own publication date if its HTML carries one, else now: a page that became"
    " public after the session's as-of time is recorded but not `readable` by this session.",
    FetchPageArgs,
)
async def fetch_page(ctx: Ctx, args: FetchPageArgs) -> dict[str, Any]:
    ctx.refuse_isolated("fetch_page")
    page = await ctx.api.post("/sources/fetch", {"company": args.company, "url": args.url})
    available = datetime.fromisoformat(page["available_at"])
    readable = available <= ctx.as_of
    return {
        "fetched": True,
        "outcome": page.get("outcome"),
        "version_id": page.get("source_version_id"),
        "document_id": page.get("source_document_id"),
        "company": page.get("company"),
        "url": page.get("final_url"),
        "title": page.get("title"),
        "media_type": page.get("media_type"),
        "tier": page.get("tier"),
        "available_at": page.get("available_at"),
        "available_at_basis": page.get("available_at_basis"),
        "date_source": page.get("date_source"),
        "as_of": ctx.as_of_iso,
        "readable": readable,
        "note": (
            "Archived. `read` the version, then record Facts from what you read."
            if readable
            else "Recorded, but it became public after the session's as-of time: this session"
            " cannot read it (`read` refuses it as available_after_as_of)."
        ),
    }
