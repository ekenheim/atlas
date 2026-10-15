"""Making a call (atlas-beliefs ticket 19): the three origins insert one in the transaction that
makes them, and the backfill gives the Beliefs proven before this existed theirs.

A call is dated by what made it, never earlier: the `at` of the judgement that proved the
Belief, the publication time of the Hypothesis version, the creation time of the question
Issue. Each caller passes that database timestamp; nothing here takes a date from a request.
A call is made once for its origin (`UNIQUE (origin, origin_id)`; a signal lead makes one
call too), so a Belief judged `proven` again, or an Issue made twice from a lead, adds nothing.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from sqlalchemy import Connection, text

from atlas.audit import Actor, content_hash, record
from atlas.calls.model import Direction, Origin, step_direction
from atlas.companies import extend_universe, load_universe


def company_symbols(
    connection: Connection, themes_config: Path | None, company_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    """Each company's TradingView symbol from the theme config (None: it has none, is a
    counterparty, or no config was given)."""
    ids = list(dict.fromkeys(company_ids))
    if not ids:
        return {}
    slugs = {
        row.id: row.slug
        for row in connection.execute(
            text("SELECT id, slug FROM company WHERE id = ANY(:ids)"), {"ids": ids}
        )
    }
    symbols: dict[uuid.UUID, str | None] = dict.fromkeys(ids)
    if themes_config is None:
        return symbols
    universe = extend_universe(connection, load_universe(themes_config))
    for company_id, slug in slugs.items():
        config = universe.companies.get(slug)
        symbols[company_id] = config.tradingview_symbol if config else None
    return symbols


def record_call(
    connection: Connection,
    actor: Actor,
    *,
    origin: Origin,
    origin_id: uuid.UUID,
    theme: str,
    claim: str,
    direction: Direction | None,
    made_at: datetime,
    company_ids: Sequence[uuid.UUID],
    themes_config: Path | None,
    lead_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Insert the call and its companies; its ID, or None when the origin (or the lead) already
    made one."""
    call_id = uuid.uuid4()
    inserted = connection.execute(
        text(
            "INSERT INTO call_record (id, origin, origin_id, lead_id, theme, claim, direction,"
            " made_at) VALUES (:id, :origin, :origin_id, :lead, :theme, :claim, :direction,"
            " :made_at) ON CONFLICT DO NOTHING RETURNING id"
        ),
        {
            "id": call_id,
            "origin": origin,
            "origin_id": origin_id,
            "lead": lead_id,
            "theme": theme,
            "claim": claim.strip(),
            "direction": direction,
            "made_at": made_at,
        },
    ).scalar_one_or_none()
    if inserted is None:
        return None
    symbols = company_symbols(connection, themes_config, company_ids)
    for company_id, symbol in symbols.items():
        connection.execute(
            text(
                "INSERT INTO call_company (call_id, company_id, symbol)"
                " VALUES (:call, :company, :symbol)"
            ),
            {"call": call_id, "company": company_id, "symbol": symbol},
        )
    record(
        connection,
        actor,
        "call.recorded",
        entity_type="call",
        entity_id=str(call_id),
        new_hash=content_hash(
            {
                "origin": origin,
                "origin_id": origin_id,
                "theme": theme,
                "claim": claim.strip(),
                "direction": direction,
                "made_at": made_at,
                "companies": sorted(str(each) for each in symbols),
            }
        ),
    )
    return call_id


def belief_call(
    connection: Connection,
    actor: Actor,
    belief_id: uuid.UUID,
    *,
    made_at: datetime,
    themes_config: Path | None,
) -> uuid.UUID | None:
    """The call a Belief makes when it is judged `proven`, dated `made_at` (that judgement's
    time): the statement, the companies it names, the step's direction."""
    belief = connection.execute(
        text("SELECT theme, statement, step FROM belief WHERE id = :id"), {"id": belief_id}
    ).one()
    companies = list(
        connection.execute(
            text("SELECT company_id FROM belief_company WHERE belief_id = :id ORDER BY company_id"),
            {"id": belief_id},
        ).scalars()
    )
    return record_call(
        connection,
        actor,
        origin="belief",
        origin_id=belief_id,
        theme=belief.theme,
        claim=belief.statement,
        direction=step_direction(belief.step),
        made_at=made_at,
        company_ids=companies,
        themes_config=themes_config,
    )


def hypothesis_call(
    connection: Connection,
    actor: Actor,
    version_id: uuid.UUID,
    *,
    made_at: datetime,
    themes_config: Path | None,
) -> uuid.UUID | None:
    """The call a published Hypothesis version makes, dated its publication: the thesis, the
    Hypothesis's related companies, no direction."""
    row = connection.execute(
        text(
            "SELECT h.theme_id, h.related_company_ids, v.content->>'thesis_statement' AS thesis"
            " FROM hypothesis_version v JOIN hypothesis h ON h.id = v.hypothesis_id"
            " WHERE v.id = :id"
        ),
        {"id": version_id},
    ).one()
    if not (row.thesis or "").strip():
        return None
    return record_call(
        connection,
        actor,
        origin="hypothesis",
        origin_id=version_id,
        theme=row.theme_id,
        claim=row.thesis,
        direction=None,
        made_at=made_at,
        company_ids=list(row.related_company_ids),
        themes_config=themes_config,
    )


def signal_call(
    connection: Connection,
    actor: Actor,
    *,
    issue_id: uuid.UUID,
    lead_id: uuid.UUID,
    theme: str,
    made_at: datetime,
    themes_config: Path | None,
) -> uuid.UUID | None:
    """The call a Scout session makes when it escalates an archive signal to a question Issue,
    dated the Issue's creation: the sentence the scan found, the company it is about."""
    signal = connection.execute(
        text("SELECT quote, company_id FROM archive_signal WHERE lead_id = :lead"),
        {"lead": lead_id},
    ).one_or_none()
    if signal is None:
        return None
    return record_call(
        connection,
        actor,
        origin="signal",
        origin_id=issue_id,
        theme=theme,
        claim=signal.quote,
        direction=None,
        made_at=made_at,
        company_ids=[signal.company_id],
        themes_config=themes_config,
        lead_id=lead_id,
    )


def backfill_belief_calls(
    connection: Connection, actor: Actor, themes_config: Path | None
) -> list[uuid.UUID]:
    """A call for each Belief that was ever judged `proven` and has none, dated its first
    `proven` judgement (the time it was proven, not today). Idempotent."""
    rows = connection.execute(
        text(
            "SELECT b.id, min(j.at) AS proven_at FROM belief b"
            " JOIN belief_judgement j ON j.belief_id = b.id AND j.judgement = 'proven'"
            " WHERE NOT EXISTS (SELECT FROM call_record c"
            "   WHERE c.origin = 'belief' AND c.origin_id = b.id)"
            " GROUP BY b.id ORDER BY min(j.at), b.id"
        )
    ).all()
    made: list[uuid.UUID] = []
    for row in rows:
        call_id = belief_call(
            connection, actor, row.id, made_at=row.proven_at, themes_config=themes_config
        )
        if call_id is not None:
            made.append(call_id)
    return made
