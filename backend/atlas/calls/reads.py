"""Reading the prospective record's calls with their checkpoints (atlas-beliefs ticket 19)."""

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import Connection, text

from atlas.calls.model import (
    HORIZONS,
    Call,
    CallCompany,
    CallState,
    Checkpoint,
    CheckpointMove,
    NextDue,
    Origin,
    due_on,
)

# A call's state, from its checkpoints and its note: `settled` with all three, `unpriced` when
# it has been noted and nothing has priced it yet, else `open`.
_STATE = (
    "CASE WHEN (SELECT count(*) FROM call_checkpoint k WHERE k.call_id = c.id) >= :horizons"
    "  THEN 'settled'"
    " WHEN EXISTS (SELECT FROM call_unpriced u WHERE u.call_id = c.id)"
    "  AND NOT EXISTS (SELECT FROM call_checkpoint k WHERE k.call_id = c.id) THEN 'unpriced'"
    " ELSE 'open' END"
)


def list_calls(
    connection: Connection,
    *,
    theme: str | None = None,
    origin: Origin | None = None,
    state: CallState | None = None,
    company_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Call], int]:
    """The calls, newest first, each with its companies and checkpoints; and the total."""
    where = (
        " FROM call_record c WHERE (CAST(:theme AS text) IS NULL OR c.theme = :theme)"
        " AND (CAST(:origin AS text) IS NULL OR c.origin = :origin)"
        " AND (CAST(:company AS uuid) IS NULL OR EXISTS (SELECT FROM call_company cc"
        "   WHERE cc.call_id = c.id AND cc.company_id = :company))"
        f" AND (CAST(:state AS text) IS NULL OR ({_STATE}) = :state)"
    )
    params: dict[str, Any] = {
        "theme": theme,
        "origin": origin,
        "company": company_id,
        "state": state,
        "horizons": len(HORIZONS),
    }
    total = connection.execute(text("SELECT count(*)" + where), params).scalar_one()
    rows = connection.execute(
        text(
            f"SELECT c.id, c.origin, c.origin_id, c.lead_id, c.theme, c.claim, c.direction,"  # noqa: S608 (constant fragments)
            f" c.made_at, ({_STATE}) AS state,"
            " (SELECT reason FROM call_unpriced u WHERE u.call_id = c.id) AS unpriced_reason"
            + where
            + " ORDER BY c.made_at DESC, c.id LIMIT :limit OFFSET :offset"
        ),
        params | {"limit": limit, "offset": offset},
    ).all()
    ids = [row.id for row in rows]
    companies: dict[uuid.UUID, list[CallCompany]] = defaultdict(list)
    for each in connection.execute(
        text(
            "SELECT cc.call_id, cc.company_id, cc.symbol, co.slug, co.display_name"
            " FROM call_company cc JOIN company co ON co.id = cc.company_id"
            " WHERE cc.call_id = ANY(:ids) ORDER BY co.slug"
        ),
        {"ids": ids},
    ):
        companies[each.call_id].append(
            CallCompany(
                company_id=each.company_id,
                slug=each.slug,
                display_name=each.display_name,
                symbol=each.symbol,
            )
        )
    checkpoints: dict[uuid.UUID, list[Checkpoint]] = defaultdict(list)
    for each in connection.execute(
        text(
            "SELECT call_id, horizon_months, due_on, change, benchmark_change, relative_change,"
            " benchmark_members, companies, benchmark, settled_at FROM call_checkpoint"
            " WHERE call_id = ANY(:ids) ORDER BY horizon_months"
        ),
        {"ids": ids},
    ):
        checkpoints[each.call_id].append(
            Checkpoint(
                horizon_months=each.horizon_months,
                due_on=each.due_on,
                change=float(each.change),
                benchmark_change=_float(each.benchmark_change),
                relative_change=_float(each.relative_change),
                benchmark_members=each.benchmark_members,
                companies=[CheckpointMove.model_validate(m) for m in each.companies],
                benchmark=[CheckpointMove.model_validate(m) for m in each.benchmark],
                settled_at=each.settled_at,
            )
        )
    calls: list[Call] = []
    for row in rows:
        held = {each.horizon_months for each in checkpoints[row.id]}
        upcoming = [
            (months, due_on(row.made_at, months)) for months in HORIZONS if months not in held
        ]
        calls.append(
            Call(
                id=row.id,
                origin=row.origin,
                origin_id=row.origin_id,
                lead_id=row.lead_id,
                theme=row.theme,
                claim=row.claim,
                direction=row.direction,
                made_at=row.made_at,
                state=row.state,
                unpriced_reason=row.unpriced_reason,
                companies=companies[row.id],
                checkpoints=checkpoints[row.id],
                next_due=NextDue(horizon_months=upcoming[0][0], due_on=upcoming[0][1])
                if upcoming
                else None,
            )
        )
    return calls, total


def _float(value: Any) -> float | None:
    return None if value is None else float(value)
