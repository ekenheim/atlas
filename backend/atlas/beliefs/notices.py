"""Belief notices: what supports a Belief, beside its flags (atlas-beliefs ticket 26).

A confirmation is no doubt, so it is not a flag: it never counts in `open_flags` (the publish
gate, proposed updates and the pages' "needs a second look" read those) and raises no proposed
update. It is a `belief_notice`, insert-only like a flag and cleared only by a judgement
(`Beliefs.judge`); it never changes the judgement.

Two events raise `belief_confirmed`, both for a Fact recorded in a research session whose
document became public after the Belief's as-of time, on a Belief that is active and currently
proven:

- the counter-judge relates the Fact `supports` to a load-bearing, positively cited Fact of the
  Belief (`confirm_by_relation`: the relate and judge routes of `/statements`);
- the Fact is cited to the Belief with the relation `supports` (`confirm_by_citation`:
  `Beliefs.cite`). A citation with a plain positive valence is the author's own weighing and
  raises none.

The same Fact raises one open notice per Belief.
"""

import uuid
from typing import Any

from sqlalchemy import Connection, text

from atlas.audit import content_hash, record
from atlas.beliefs.flags import FLAGGER

NOTICE_CONFIRMED = "belief_confirmed"

_FACT = (
    "SELECT a.id, f.session_id, a.value_json->>'statement' AS statement,"
    " d.title, av.available_at"
    " FROM fact f JOIN assertion a ON a.id = f.assertion_id"
    " JOIN source_version v ON v.id = a.source_version_id"
    " JOIN source_document d ON d.id = v.source_document_id"
    " JOIN source_version_availability av ON av.source_version_id = v.id"
    " WHERE f.assertion_id = :id"
)
_PROVEN_ACTIVE = (
    "SELECT b.id FROM belief b"
    " JOIN LATERAL (SELECT x.judgement FROM belief_judgement x WHERE x.belief_id = b.id"
    "  ORDER BY x.at DESC, x.id DESC LIMIT 1) j ON true"
    " WHERE b.status = 'active' AND j.judgement = 'proven' AND b.as_of < :available"
)


def _notice(connection: Connection, belief_id: uuid.UUID, fact: Any) -> bool:
    """Raise one `belief_confirmed` notice for the Fact unless it is open already; audited."""
    detail = (
        f"A document public {fact.available_at.date().isoformat()}"
        f" ({fact.title or 'untitled'}) supports it: {fact.statement}"
    )
    notice_id = uuid.uuid4()
    inserted = connection.execute(
        text(
            "INSERT INTO belief_notice (id, belief_id, kind, ref_id, detail)"
            " VALUES (:id, :belief, :kind, :ref, :detail)"
            " ON CONFLICT (belief_id, kind, ref_id) WHERE cleared_by IS NULL DO NOTHING"
        ),
        {
            "id": notice_id,
            "belief": belief_id,
            "kind": NOTICE_CONFIRMED,
            "ref": fact.id,
            "detail": detail,
        },
    )
    if inserted.rowcount == 0:
        return False
    record(
        connection,
        FLAGGER,
        "belief.confirmed",
        entity_type="belief",
        entity_id=str(belief_id),
        new_hash=content_hash({"notice": notice_id, "ref": fact.id, "detail": detail}),
    )
    return True


def _session_fact(connection: Connection, fact_id: uuid.UUID) -> Any | None:
    """The Fact, if a research session recorded it."""
    fact = connection.execute(text(_FACT), {"id": fact_id}).one_or_none()
    return fact if fact is not None and fact.session_id is not None else None


def confirm_by_citation(connection: Connection, belief_id: uuid.UUID, fact_id: uuid.UUID) -> bool:
    """The Fact was cited to the Belief with the relation `supports`: whether a notice was
    raised."""
    fact = _session_fact(connection, fact_id)
    if fact is None:
        return False
    belief = connection.execute(
        text(f"{_PROVEN_ACTIVE} AND b.id = :belief"),
        {"available": fact.available_at, "belief": belief_id},
    ).one_or_none()
    return belief is not None and _notice(connection, belief_id, fact)


def confirm_by_relation(
    connection: Connection, fact_id: uuid.UUID, counter_fact_id: uuid.UUID
) -> list[uuid.UUID]:
    """The counter-judge related `counter_fact_id` to `fact_id` as `supports`: the Beliefs that
    rest on `fact_id` (a load-bearing citation of positive valence) and were noticed."""
    counter = _session_fact(connection, counter_fact_id)
    if counter is None:
        return []
    raised: list[uuid.UUID] = []
    candidates = connection.execute(
        text(
            f"{_PROVEN_ACTIVE} AND EXISTS (SELECT FROM belief_citation c"
            " WHERE c.belief_id = b.id AND c.ref_id = :fact AND c.weight = 'load_bearing'"
            " AND c.valence > 0) ORDER BY b.created_at, b.id"
        ),
        {"available": counter.available_at, "fact": fact_id},
    ).scalars()
    for belief_id in list(candidates):
        if _notice(connection, belief_id, counter):
            raised.append(belief_id)
    return raised
