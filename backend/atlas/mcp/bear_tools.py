"""The Atlas MCP server's bear-check tool (Chokepoint Watch ticket W4): `bear_checks`.

A projection of `GET /api/v1/companies/{id}/bear-checks` with the session's as-of time as its
bound, on the pattern of `signal_leads`: it takes no as-of argument and calls nothing else. The
six checks are mechanical (no model): XBRL figures and sentence patterns over the archived
filings public by the as-of time. A check is a reason to look, never a Fact: the sentence it
quotes comes with its Source Version and span, so the agent can `read` it and record a Fact
itself. Refused in an isolated session (ticket 29a's frozen surface).

Registered by importing this module (`atlas.mcp`'s package init).
"""

from typing import Any

from pydantic import Field

from atlas.mcp.tools import Bound, Ctx, tool

BEAR_NOTE = (
    "Mechanical checks, no model: XBRL figures and sentence patterns over filings public by the"
    " session's as-of time. `flag` is what a bear looks for, `clear` that the check looked and"
    " found none, `unknown` that Atlas does not hold what it needs (never read it as clear). A"
    " check is where to look, never a Fact: a quoted sentence comes with its `source_version_id`"
    " and span, so `read` it and record a Fact yourself; XBRL figures are not Facts."
)


class BearChecksArgs(Bound):
    company: str = Field(description="a company slug")


@tool(
    "bear_checks",
    "Six mechanical bear checks for a company as of the session's as-of time: dilution (shares"
    " outstanding against a year earlier), shelf or ATM filings, GAAP gross margin (trailing four"
    " quarters), customer concentration and going-concern language (the latest filing's"
    " sentences, with their spans), and net cash. Each is `flag`, `clear` or `unknown`, with its"
    " basis and sources. No model is called; nothing public after the as-of time is read.",
    BearChecksArgs,
)
async def bear_checks(ctx: Ctx, args: BearChecksArgs) -> dict[str, Any]:
    ctx.refuse_isolated("bear_checks")
    company_id = await ctx.company_id(args.company)
    answer = await ctx.api.get(f"/companies/{company_id}/bear-checks", as_of=ctx.as_of_iso)
    return {
        "company": args.company,
        "as_of": ctx.as_of_iso,
        "checks": answer.get("checks", []),
        "note": BEAR_NOTE,
    }
