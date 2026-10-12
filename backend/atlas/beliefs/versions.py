"""The Beliefs a Hypothesis version rests on (atlas-beliefs ticket 03).

A version rests on an active Belief that cites an Assertion its findings' spans cite. The Belief
is **load-bearing** for the version when one such citation is load-bearing for the Belief; a
context citation records the Belief but does not gate. Publishing records them (with the
judgement then current), the Research Snapshot carries them, and the publish gate requires every
load-bearing one `proven`, or the owner's explicit override with a reason.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, text


def version_beliefs(
    connection: Connection, assertion_ids: Sequence[uuid.UUID]
) -> list[dict[str, Any]]:
    """The active Beliefs citing any of `assertion_ids`, oldest first, with the judgement now."""
    if not assertion_ids:
        return []
    rows = connection.execute(
        text(
            "SELECT b.id AS belief_id, b.statement, b.theme, b.step, b.as_of,"
            " bool_or(c.weight = 'load_bearing') AS load_bearing,"
            " array_agg(DISTINCT c.ref_id) AS assertion_ids,"
            " j.judgement, j.confidence, j.at AS judged_at, j.actor AS judged_by"
            " FROM belief b JOIN belief_citation c ON c.belief_id = b.id"
            " JOIN LATERAL (SELECT * FROM belief_judgement x WHERE x.belief_id = b.id"
            "   ORDER BY x.at DESC, x.id DESC LIMIT 1) j ON true"
            " WHERE b.status = 'active' AND c.ref_id = ANY(CAST(:ids AS uuid[]))"
            " GROUP BY b.id, j.judgement, j.confidence, j.at, j.actor, j.id"
            " ORDER BY b.created_at, b.id"
        ),
        {"ids": list(assertion_ids)},
    ).mappings()
    return [dict(row) for row in rows]


def unproven_load_bearing(
    connection: Connection, assertion_ids: Sequence[uuid.UUID]
) -> list[dict[str, Any]]:
    """The load-bearing Beliefs of a version that are not `proven`."""
    return [
        each
        for each in version_beliefs(connection, assertion_ids)
        if each["load_bearing"] and each["judgement"] != "proven"
    ]


def record_version_beliefs(
    connection: Connection, version_id: uuid.UUID, assertion_ids: Sequence[uuid.UUID]
) -> None:
    """Record the Beliefs a version rests on (in the publishing transaction)."""
    for each in version_beliefs(connection, assertion_ids):
        connection.execute(
            text(
                "INSERT INTO hypothesis_version_belief (hypothesis_version_id, belief_id,"
                " load_bearing, judgement, confidence) VALUES (:version, :belief, :load_bearing,"
                " :judgement, :confidence)"
            ),
            {
                "version": version_id,
                "belief": each["belief_id"],
                "load_bearing": each["load_bearing"],
                "judgement": each["judgement"],
                "confidence": each["confidence"],
            },
        )
