"""What a published Hypothesis version depends on, and the events that may contradict it.

`record_dependencies` runs in the publishing transaction (atlas.hypotheses): the version's
findings' Assertions, the Claims they cite, the Relationships those Assertions support and
the Source Versions of their spans become insert-only `hypothesis_dependency` rows.

The `on_*` hooks run in the transaction that records each event, where it is recorded. Each
checks, with one indexed query, whether the event touches a published version's dependencies,
and only then enqueues the deterministic `check_contradictions` job (atlas.proposed_updates.
detection), which exists only if the event commits:

- `on_assertion_reviewed`: a dependent Assertion disputed, rejected or superseded;
- `on_relationship_rejected`: the owner rejects a dependent Relationship;
- `on_source_revised`: a newer Source Version of a Source Document a dependent version came
  from (the job compares the quotes);
- `on_counterevidence`: the Skeptic's accepted, independent counterevidence against a Claim
  whose Assertion states a dependent span (the same Source Version and offsets).
"""

import uuid
from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal

from sqlalchemy import Connection, text

from atlas.jobs.queue import JobQueue

if TYPE_CHECKING:
    from atlas.hypotheses.model import HypothesisVersion

CHECK_CONTRADICTIONS_KIND = "check_contradictions"
Trigger = Literal[
    "assertion_reviewed", "relationship_rejected", "source_revised", "counterevidence"
]
# The review states that contradict what an Assertion stated (as the version diff reads them).
CONTRADICTING_STATES = ("disputed", "rejected", "superseded")


def record_dependencies(connection: Connection, version: "HypothesisVersion") -> None:
    """Record what the published `version` depends on (in the publishing transaction)."""
    spans = [span for finding in version.content.findings for span in finding.source_spans]
    rows: list[tuple[str, uuid.UUID]] = [
        *(("assertion", span.assertion_id) for span in spans),
        *(("source_version", span.source_version_id) for span in spans),
        *(
            ("claim", claim_id)
            for finding in version.content.findings
            for claim_id in finding.claim_ids
        ),
    ]
    _insert(connection, version.id, rows)
    connection.execute(
        text(
            "INSERT INTO hypothesis_dependency (hypothesis_version_id, kind, ref_id)"
            " SELECT DISTINCT :version, 'relationship', ra.relationship_id"
            " FROM relationship_assertion ra WHERE ra.assertion_id = ANY(CAST(:ids AS uuid[]))"
            " ON CONFLICT DO NOTHING"
        ),
        {"version": version.id, "ids": [span.assertion_id for span in spans]},
    )


def _insert(
    connection: Connection, version_id: uuid.UUID, rows: Iterable[tuple[str, uuid.UUID]]
) -> None:
    unique = list(dict.fromkeys(rows))
    if not unique:
        return
    connection.execute(
        text(
            "INSERT INTO hypothesis_dependency (hypothesis_version_id, kind, ref_id)"
            " SELECT :version, kind, ref_id FROM unnest(CAST(:kinds AS text[]),"
            " CAST(:refs AS uuid[])) AS d(kind, ref_id) ON CONFLICT DO NOTHING"
        ),
        {
            "version": version_id,
            "kinds": [kind for kind, _ in unique],
            "refs": [ref for _, ref in unique],
        },
    )


# --- the events -----------------------------------------------------------------------------------

_DEPENDS = (
    "EXISTS (SELECT FROM hypothesis_dependency d"
    " JOIN hypothesis_version v ON v.id = d.hypothesis_version_id"
    " WHERE v.published_at IS NOT NULL AND d.kind = :kind AND d.ref_id = :ref)"
)


def on_assertion_reviewed(connection: Connection, assertion_id: uuid.UUID, state: str) -> None:
    if state in CONTRADICTING_STATES and _depends(connection, "assertion", assertion_id):
        _enqueue(connection, "assertion_reviewed", assertion_id, state)


def on_relationship_rejected(connection: Connection, relationship_id: uuid.UUID) -> None:
    if _depends(connection, "relationship", relationship_id):
        _enqueue(connection, "relationship_rejected", relationship_id)


def on_source_revised(connection: Connection, source_version_id: uuid.UUID) -> None:
    """A new Source Version: does a published version cite an earlier one of its document?"""
    revises = connection.execute(
        text(
            "SELECT EXISTS (SELECT FROM source_version new"
            " JOIN source_version old ON old.source_document_id = new.source_document_id"
            "  AND old.version_number < new.version_number"
            " JOIN hypothesis_dependency d ON d.kind = 'source_version' AND d.ref_id = old.id"
            " JOIN hypothesis_version v ON v.id = d.hypothesis_version_id"
            " WHERE new.id = :id AND v.published_at IS NOT NULL)"
        ),
        {"id": source_version_id},
    ).scalar_one()
    if revises:
        _enqueue(connection, "source_revised", source_version_id)


def on_counterevidence(connection: Connection, counterevidence_id: uuid.UUID) -> None:
    """Accepted, independent counterevidence against a Claim stating a dependent span."""
    touches = connection.execute(
        text(
            "SELECT EXISTS (SELECT FROM counterevidence ce"
            " JOIN claim c ON c.id = ANY(ce.contradicts_claim_ids)"
            " JOIN assertion ca ON ca.id = c.assertion_id"
            " JOIN assertion da ON da.source_version_id = ca.source_version_id"
            "  AND da.span_start = ca.span_start AND da.span_end = ca.span_end"
            "  AND da.parser_version = ca.parser_version"
            " JOIN hypothesis_dependency d ON d.kind = 'assertion' AND d.ref_id = da.id"
            " JOIN hypothesis_version v ON v.id = d.hypothesis_version_id"
            " WHERE ce.id = :id AND ce.outcome = 'accepted' AND ce.independent"
            "  AND v.published_at IS NOT NULL)"
        ),
        {"id": counterevidence_id},
    ).scalar_one()
    if touches:
        _enqueue(connection, "counterevidence", counterevidence_id)


def _depends(connection: Connection, kind: str, ref: uuid.UUID) -> bool:
    return bool(
        connection.execute(text(f"SELECT {_DEPENDS}"), {"kind": kind, "ref": ref}).scalar_one()
    )


def trigger_key(trigger: Trigger, ref: uuid.UUID, state: str | None = None) -> str:
    return f"{trigger}:{ref}" + (f":{state}" if state else "")


def _enqueue(
    connection: Connection, trigger: Trigger, ref: uuid.UUID, state: str | None = None
) -> None:
    payload: dict[str, str | None] = {"trigger": trigger, "id": str(ref), "state": state}
    JobQueue(connection.engine).enqueue_within(
        connection,
        CHECK_CONTRADICTIONS_KIND,
        trigger_key(trigger, ref, state),
        dict(payload),
    )
