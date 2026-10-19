"""The last day a dated lead was certainly public by an instant (Chokepoint Watch W3, W9).

A lead carries a day, not a time. The MCP searches (`atlas.mcp.watch_sources`) bound what they
return by these, and the board (`atlas.chokepoints.service`) bounds the leads a session found
after its as-of time by the same rule, so a lead the session's own search could not have
returned is never cited as public by then.
"""

from datetime import UTC, date, datetime, timedelta

# EDGAR files by Eastern day and a day is over by 05:00 UTC the next calendar day; a date-only
# publication can be as late as the end of that day at UTC-12 (12:00 UTC the next day).
EDGAR_DAY_END = timedelta(hours=5)
DATE_ONLY_END = timedelta(hours=12)


def filing_bound(as_of: datetime) -> date:
    """The last filing date every filing of which was accepted by `as_of`."""
    return (as_of.astimezone(UTC) - EDGAR_DAY_END).date() - timedelta(days=1)


def published_bound(as_of: datetime) -> date:
    """The last publication date, given as a date alone, that was certainly over by `as_of`."""
    return (as_of.astimezone(UTC) - DATE_ONLY_END).date() - timedelta(days=1)


def lead_bound(origin: str, as_of: datetime) -> date:
    """The last day a lead of `origin` may carry to count as public by `as_of`: an EDGAR filing
    hit's filing day by `filing_bound`, any other dated lead's by `published_bound`."""
    return filing_bound(as_of) if origin == "edgar_fts" else published_bound(as_of)
