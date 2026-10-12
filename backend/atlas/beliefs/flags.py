"""Belief flags: raised by code, in the transaction that records the event, never a change.

A Belief cites Facts (and Assertions). Three events flag the Beliefs citing them, each flag
insert-only and open until an author's judgement clears it (`Beliefs.judge`):

- `assertion_reviewed` / `fact_superseded`: a cited Assertion reviewed disputed or rejected, or
  superseded (`on_assertion_reviewed` of the proposed-updates trigger path calls this);
- `source_revised`: a newer Source Version of a cited Assertion's document whose parsed text no
  longer contains the quote (the `check_contradictions` job, which has the archive, calls this);
- `counterevidence_stands`: a load-bearing citation with valence at or below
  `COUNTEREVIDENCE_VALENCE` whose Fact stands (raised when it is cited).

A flagged Belief keeps its judgement and its citations; the page shows the flag.
"""

import uuid

from sqlalchemy import Connection, text

from atlas.archive import Archive
from atlas.audit import Actor, content_hash, record

FLAGGER = Actor("atlas-beliefs")
COUNTEREVIDENCE_VALENCE = -0.75
_STANDING = ("unreviewed", "corroborated")
_PARSED = ("parsed", "incomplete")


def _flag(
    connection: Connection, belief_id: uuid.UUID, kind: str, ref_id: uuid.UUID, detail: str
) -> bool:
    """Raise one flag unless the same one is open already; audited. Whether it was raised."""
    flag_id = uuid.uuid4()
    inserted = connection.execute(
        text(
            "INSERT INTO belief_flag (id, belief_id, kind, ref_id, detail)"
            " VALUES (:id, :belief, :kind, :ref, :detail)"
            " ON CONFLICT (belief_id, kind, ref_id) WHERE cleared_by IS NULL DO NOTHING"
        ),
        {"id": flag_id, "belief": belief_id, "kind": kind, "ref": ref_id, "detail": detail},
    )
    if inserted.rowcount == 0:
        return False
    record(
        connection,
        FLAGGER,
        "belief.flagged",
        entity_type="belief",
        entity_id=str(belief_id),
        new_hash=content_hash({"flag": flag_id, "kind": kind, "ref": ref_id, "detail": detail}),
    )
    return True


def flag_assertion_reviewed(connection: Connection, assertion_id: uuid.UUID, state: str) -> None:
    """The active Beliefs citing the Assertion, when it is now disputed, rejected or superseded."""
    if state not in ("disputed", "rejected", "superseded"):
        return
    kind = "fact_superseded" if state == "superseded" else "assertion_reviewed"
    beliefs = connection.execute(
        text(
            "SELECT DISTINCT c.belief_id FROM belief_citation c"
            " JOIN belief b ON b.id = c.belief_id"
            " WHERE c.ref_id = :ref AND b.status = 'active' ORDER BY c.belief_id"
        ),
        {"ref": assertion_id},
    ).scalars()
    for belief_id in list(beliefs):
        _flag(connection, belief_id, kind, assertion_id, f"A cited statement was reviewed {state}.")


def cites_earlier_version(connection: Connection, source_version_id: uuid.UUID) -> bool:
    """Does an active Belief cite an Assertion in an earlier version of this one's document?"""
    return bool(
        connection.execute(
            text(
                "SELECT EXISTS (SELECT FROM source_version new"
                " JOIN source_version old ON old.source_document_id = new.source_document_id"
                "  AND old.version_number < new.version_number"
                " JOIN assertion a ON a.source_version_id = old.id"
                " JOIN belief_citation c ON c.ref_id = a.id"
                " JOIN belief b ON b.id = c.belief_id AND b.status = 'active'"
                " WHERE new.id = :id)"
            ),
            {"id": source_version_id},
        ).scalar_one()
    )


def flag_source_revised(
    connection: Connection, archive: Archive, source_version_id: uuid.UUID
) -> int:
    """Flag the active Beliefs citing a quote the revised version's parsed text lacks. A
    revision without parsed text can't be compared and flags nothing. Returns the flags raised."""
    new = (
        connection.execute(
            text(
                "SELECT v.source_document_id, v.version_number, v.parse_status,"
                " v.parsed_object_uri FROM source_version v WHERE v.id = :id"
            ),
            {"id": source_version_id},
        )
        .mappings()
        .one()
    )
    if new["parse_status"] not in _PARSED or new["parsed_object_uri"] is None:
        return 0
    cited = connection.execute(
        text(
            "SELECT DISTINCT c.belief_id, a.id AS assertion_id, a.quote"
            " FROM belief_citation c JOIN belief b ON b.id = c.belief_id AND b.status = 'active'"
            " JOIN assertion a ON a.id = c.ref_id"
            " JOIN source_version old ON old.id = a.source_version_id"
            " WHERE old.source_document_id = :document AND old.version_number < :number"
            " ORDER BY c.belief_id, a.id"
        ),
        {"document": new["source_document_id"], "number": new["version_number"]},
    ).all()
    if not cited:
        return 0
    revised = archive.get(new["parsed_object_uri"]).decode("utf-8")
    raised = 0
    for row in cited:
        if row.quote not in revised and _flag(
            connection,
            row.belief_id,
            "source_revised",
            row.assertion_id,
            f"A revised version of the document no longer contains the quote: {row.quote!r}",
        ):
            raised += 1
    return raised


def flag_counterevidence(
    connection: Connection,
    belief_id: uuid.UUID,
    ref_id: uuid.UUID,
    valence: float,
    weight: str,
) -> bool:
    """A load-bearing citation at or below -0.75 whose Fact stands: the Belief is flagged."""
    if weight != "load_bearing" or valence > COUNTEREVIDENCE_VALENCE:
        return False
    state = connection.execute(
        text("SELECT verification_status FROM assertion WHERE id = :id"), {"id": ref_id}
    ).scalar_one()
    if state not in _STANDING:
        return False
    return _flag(
        connection,
        belief_id,
        "counterevidence_stands",
        ref_id,
        f"A load-bearing citation against the Belief (valence {valence:g}) stands.",
    )
