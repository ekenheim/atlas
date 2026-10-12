"""When a Belief reaches Memory (beliefs ticket 06): the `retain_belief` job's trigger.

A Belief is retained once its judgement is anything but `unproven`, and again (the document
deleted first) when it is re-judged or superseded; one judged and then judged `unproven`
again has its document taken out. The job reads the Belief as it is when it runs, so it is
keyed by the judgement and status it was asked for. Called inside the transaction that
changes the Belief, so the job exists only if the change commits. Code:
`atlas.retention.beliefs`.
"""

import uuid

from sqlalchemy import Connection, text

from atlas.jobs.queue import JobQueue

RETAIN_BELIEF_KIND = "retain_belief"


def retain_belief_key(belief_id: uuid.UUID, judgement_id: uuid.UUID, status: str) -> str:
    return f"{RETAIN_BELIEF_KIND}:{belief_id}:{judgement_id}:{status}"


def enqueue_retain_belief(connection: Connection, belief_id: uuid.UUID) -> bool:
    """Ask for the Belief's document to match its current judgement and status. False (no
    job) for a Belief still `unproven` that Memory never held."""
    row = connection.execute(
        text(
            "SELECT b.status, j.id AS judgement_id, j.judgement,"
            " EXISTS (SELECT FROM belief_memory m WHERE m.belief_id = b.id"
            "   AND m.state <> 'removed') AS held"
            " FROM belief b JOIN LATERAL (SELECT * FROM belief_judgement x"
            "   WHERE x.belief_id = b.id ORDER BY x.at DESC, x.id DESC LIMIT 1) j ON true"
            " WHERE b.id = :id"
        ),
        {"id": belief_id},
    ).one_or_none()
    if row is None or (row.judgement == "unproven" and not row.held):
        return False
    JobQueue(connection.engine).enqueue_within(
        connection,
        RETAIN_BELIEF_KIND,
        retain_belief_key(belief_id, row.judgement_id, row.status),
        {"belief_id": str(belief_id)},
        max_attempts=5,
    )
    return True
