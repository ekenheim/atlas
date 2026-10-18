"""The Atlas MCP server's TradingView tool (atlas-beliefs ticket 16b): `upcoming_reports`.

TradingView is the owner's override of its display-only terms (docs/decisions.md, "Owner
override: TradingView as a source"), and the agents reach it only through what Atlas stored:
the earnings calendar's reporting dates, kept as Tier C leads (`tradingview_calendar`) by the
`tradingview_calendar` job. The tool is a projection of `GET /api/v1/leads` with the session's
as-of time as its bound; it never calls TradingView, takes no as-of argument, and labels
everything it returns a lead, never Evidence. Price history is deliberately not a tool: it is
for settling predictions and replays (`GET /api/v1/companies/{id}/price-history`), never for a
Belief.

Registered by importing this module (`atlas.mcp`'s package init), so the tools module
(`atlas.mcp.tools`) stays untouched.
"""

from datetime import datetime, timedelta
from typing import Any

from pydantic import Field

from atlas.mcp.api import obj, rows
from atlas.mcp.tools import Bound, Ctx, iso, tool

UPCOMING_NOTE = (
    "Leads from TradingView's earnings calendar (an owner override of TradingView's terms): when"
    " a company reports, never what it says. Not Evidence and not support for a Belief; read the"
    " filing or the results-call transcript in the archive once it is public."
)


class UpcomingReportsArgs(Bound):
    theme: str | None = Field(default=None, description="a theme; default: the session's")
    window_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="reporting dates this many days before and after the session's as-of time",
    )


@tool(
    "upcoming_reports",
    "Companies of a theme with a reporting date within a window around the session's as-of"
    " time (recent and upcoming), soonest first, from TradingView's earnings calendar as Atlas"
    " stored it. A lead for when to look, never Evidence; what Atlas had not stored by the"
    " as-of time is not shown, and a date shows as Atlas knew it then.",
    UpcomingReportsArgs,
)
async def upcoming_reports(ctx: Ctx, args: UpcomingReportsArgs) -> dict[str, Any]:
    ctx.refuse_isolated("upcoming_reports")
    window = timedelta(days=args.window_days)
    theme = args.theme or ctx.bound.theme
    answer = await ctx.api.get(
        "/leads",
        origin="tradingview_calendar",
        theme=theme,
        known_by=ctx.as_of_iso,
        event_from=iso(ctx.as_of - window),
        event_to=iso(ctx.as_of + window),
        limit=200,
    )
    slugs = {each["id"]: each["slug"] for each in await ctx.companies()}
    reports: list[dict[str, Any]] = []
    for lead in rows(answer.get("items")):
        event = obj(lead.get("calendar"))
        company_id = str(event.get("company_id"))
        days = (datetime.fromisoformat(event["event_at"]) - ctx.as_of).total_seconds() / 86_400
        reports.append(
            {
                "company": slugs.get(company_id, company_id),
                "symbol": event.get("symbol"),
                "title": lead.get("title"),
                "event_at": event.get("event_at"),
                "days_from_as_of": round(days, 1),
                "status": event.get("status"),
                "period_end": event.get("period_end"),
                "period_basis": event.get("period_basis"),
                "known_since": event.get("observed_at"),
                "lead_id": lead.get("id"),
                "tier": lead.get("tier"),
            }
        )
    return {
        "theme": theme,
        "as_of": ctx.as_of_iso,
        "window_days": args.window_days,
        "reports": reports,
        "note": UPCOMING_NOTE,
    }
