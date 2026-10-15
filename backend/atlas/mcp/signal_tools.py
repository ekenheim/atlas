"""The Atlas MCP server's archive-signal tool (atlas-beliefs ticket 18): `signal_leads`.

The nightly `scan_signals` job scores the sentences of archived documents for the cues of a
bottleneck (`atlas.discovery.signals`) and stores each hit as a Tier C lead of origin
`archive_signal`. This tool is a projection of `GET /api/v1/leads?origin=archive_signal` with the
session's as-of time as its bound, on the pattern of `upcoming_reports`: it takes no as-of
argument, never calls anything else, and labels everything it returns a lead. For this origin
the route's `known_by` is when the document became public, so a lead whose document is public
after the session's time is not listed, whenever the scan ran.

A lead is where to look, never a Fact: the agent reads the window around the span (`read`) and
records a Fact itself from what it read, if the sentence says what the lead suggests.

Registered by importing this module (`atlas.mcp`'s package init).
"""

from typing import Any

from pydantic import AwareDatetime, Field

from atlas.mcp.api import obj, rows
from atlas.mcp.tools import Bound, Ctx, iso, tool

SIGNAL_NOTE = (
    "Leads from Atlas's nightly scan of its archive for the cues of a bottleneck (few suppliers,"
    " demand beyond supply, lead times and backlog, capacity, gates, pricing power), ranked by"
    " score. A lead is where to look, never a Fact and never Evidence: `read` the window"
    " around `char_start`..`char_end` of `version_id` (with `parser_version`), and record a Fact"
    " only from what you read. A high score is a reason to read, not a finding; an analyst's"
    " words (`speaker_kind: analyst`) are not the company's statement."
)


class SignalLeadsArgs(Bound):
    theme: str | None = Field(default=None, description="a theme; default: the session's")
    since: AwareDatetime | None = Field(
        default=None,
        description="only sentences of documents public at or after this time (with an offset)",
    )
    limit: int = Field(default=20, ge=1, le=100)


@tool(
    "signal_leads",
    "The theme's archive-signal leads, highest score first (at most three of one document among"
    " the first ones, the rest after them): sentences of documents that were"
    " public by the session's as-of time which read like a bottleneck (the quote, its Source"
    " Version and span, the company, the cue families and the speaker of a call). A lead is where"
    " to look, never a Fact: `read` the window around the span, then record a Fact yourself."
    " Never a document public after the as-of time, whenever Atlas scanned it.",
    SignalLeadsArgs,
)
async def signal_leads(ctx: Ctx, args: SignalLeadsArgs) -> dict[str, Any]:
    theme = args.theme or ctx.bound.theme
    answer = await ctx.api.get(
        "/leads",
        origin="archive_signal",
        theme=theme,
        known_by=ctx.as_of_iso,
        available_from=iso(args.since) if args.since else None,
        limit=args.limit,
    )
    leads: list[dict[str, Any]] = []
    for lead in rows(answer.get("items")):
        signal = obj(lead.get("signal"))
        leads.append(
            {
                "lead_id": lead.get("id"),
                "company": signal.get("company"),
                "title": lead.get("title"),
                "public_at": signal.get("available_at"),
                "version_id": signal.get("source_version_id"),
                "parser_version": signal.get("parser_version"),
                "section_anchor": signal.get("section_anchor"),
                "char_start": signal.get("char_start"),
                "char_end": signal.get("char_end"),
                "quote": signal.get("quote"),
                "families": signal.get("families"),
                "score": signal.get("score"),
                "speaker": signal.get("speaker"),
                "speaker_kind": signal.get("speaker_kind"),
                "tier": lead.get("tier"),
            }
        )
    return {
        "theme": theme,
        "as_of": ctx.as_of_iso,
        "total": answer.get("total"),
        "leads": leads,
        "note": SIGNAL_NOTE,
    }
