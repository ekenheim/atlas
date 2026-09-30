"""What an investigation searched and read, for its research card (pilot fix 01).

Written by code, never the Editor, so a card with no finding still says, from the records:

- **searched:** each round's Scout, its queries (in order), how many leads they found, and
  the leads the investigation took (Tier C, never Evidence);
- **read:** each Investigator task, the Source Versions it read with the sections of the
  passages it was sent (across a budget-exhausted extraction and its continuation) and how
  many passages, the documents the budget left out, and the extraction's outcomes: Claims
  proposed, accepted, and rejected by reason code; or why it read nothing. Then (pilot fix
  06) each round's Skeptic, the same way: the Source Versions it read (each with who chose
  it: its plan, its search or code's fallback) and the sections of the passages it was sent,
  whether its plan chose nothing for a seed company, and its counterevidence items proposed,
  accepted and rejected by reason code; or why it read nothing (skipped with no Claim to
  challenge, the budget spent, nothing archived, no passage matching the checklist).
"""

import uuid
from typing import Any

from sqlalchemy import Connection, Row, text

from atlas.investigations.model import (
    CardDocumentRead,
    CardQuery,
    CardReading,
    CardSearch,
)
from atlas.investigations.skeptic import used_fallback


def coverage(
    connection: Connection, investigation_id: uuid.UUID
) -> tuple[list[CardSearch], list[CardReading]]:
    """The investigation's `searched` and `read` sections, every round, in plan order."""
    return _searched(connection, investigation_id), _read(connection, investigation_id)


def _searched(connection: Connection, investigation_id: uuid.UUID) -> list[CardSearch]:
    scouts = connection.execute(
        text(
            "SELECT round, artifacts FROM investigation_task WHERE investigation_id = :id"
            " AND role = 'scout' AND artifacts -> 'discovery_id' IS NOT NULL"
            " ORDER BY round, position"
        ),
        {"id": investigation_id},
    ).all()
    searched: list[CardSearch] = []
    for scout in scouts:
        artifacts: dict[str, Any] = scout.artifacts
        discovery_id = uuid.UUID(str(artifacts["discovery_id"]))
        queries = [
            CardQuery(query=row.query, purpose=row.purpose)
            for row in connection.execute(
                text(
                    "SELECT query, purpose FROM discovery_query WHERE discovery_id = :d"
                    " ORDER BY position"
                ),
                {"d": discovery_id},
            )
        ]
        lead_ids = list(
            connection.execute(
                text(
                    "SELECT lead_id FROM investigation_lead WHERE investigation_id = :id"
                    " AND discovery_id = :d ORDER BY rank"
                ),
                {"id": investigation_id, "d": discovery_id},
            ).scalars()
        )
        searched.append(
            CardSearch(
                round=scout.round,
                discovery_id=discovery_id,
                queries=queries,
                leads_found=int(artifacts.get("leads_found") or 0),
                lead_ids=lead_ids,
            )
        )
    return searched


def _read(connection: Connection, investigation_id: uuid.UUID) -> list[CardReading]:
    tasks = connection.execute(
        text(
            "SELECT t.id, t.round, t.key, t.company_id, t.status, t.detail, t.artifacts,"
            " t.role, c.display_name FROM investigation_task t"
            " LEFT JOIN company c ON c.id = t.company_id"
            " WHERE t.investigation_id = :id AND t.role IN ('investigator', 'skeptic')"
            " ORDER BY t.round, t.position"
        ),
        {"id": investigation_id},
    ).all()
    read: list[CardReading] = []
    for task in tasks:
        if task.role == "skeptic":
            read.append(_skeptic_read(connection, task))
            continue
        artifacts: dict[str, Any] = task.artifacts
        chain = _extractions(connection, artifacts.get("extraction_id"))
        sections, sent = _sent(connection, chain)
        documents = [
            CardDocumentRead(
                source_version_id=row.source_version_id,
                title=row.title,
                sections=sections.get(row.source_version_id, []),
            )
            for row in connection.execute(
                text(
                    "SELECT doc.source_version_id, d.title FROM investigation_document doc"
                    " JOIN source_version v ON v.id = doc.source_version_id"
                    " JOIN source_document d ON d.id = v.source_document_id"
                    " WHERE doc.task_id = :task ORDER BY v.available_at DESC, v.id"
                ),
                {"task": task.id},
            )
        ]
        outcomes = connection.execute(
            text(
                "SELECT outcome, reason_code, count(*) AS n FROM claim"
                " WHERE extraction_id = ANY(:chain) GROUP BY outcome, reason_code"
                " ORDER BY outcome, reason_code"
            ),
            {"chain": chain},
        ).all()
        read.append(
            CardReading(
                round=task.round,
                task_key=task.key,
                company_id=task.company_id,
                company_name=task.display_name,
                status=task.status,
                detail=task.detail,
                documents=documents,
                documents_dropped=int(artifacts.get("documents_dropped") or 0),
                passages=sent,
                claims_proposed=sum(int(row.n) for row in outcomes),
                claims_accepted=sum(int(row.n) for row in outcomes if row.outcome == "accepted"),
                rejected={
                    str(row.reason_code): int(row.n)
                    for row in outcomes
                    if row.outcome == "rejected"
                },
            )
        )
    return read


def _skeptic_read(connection: Connection, task: Row[Any]) -> CardReading:
    """The Skeptic task's row: from its search (none when it was skipped or hasn't run)."""
    search = (
        connection.execute(
            text("SELECT * FROM skeptic_search WHERE task_id = :task"), {"task": task.id}
        )
        .mappings()
        .one_or_none()
    )
    reading = CardReading(
        round=task.round,
        task_key=task.key,
        company_id=None,
        company_name=None,
        status=task.status,
        detail=task.detail,
        documents=[],
        documents_dropped=0,
        passages=0,
        claims_proposed=0,
        claims_accepted=0,
        rejected={},
        role="skeptic",
    )
    if search is None:
        return reading
    sent: list[dict[str, Any]] = search["passages"][
        : search["batches_done"] * search["passages_per_call"]
    ]
    sections: dict[str, list[str]] = {}
    for passage in sent:
        anchors = sections.setdefault(str(passage["source_version_id"]), [])
        if passage["section_anchor"] not in anchors:
            anchors.append(passage["section_anchor"])
    chosen: list[dict[str, Any]] = search["documents"]
    titles = {
        row.id: row.title
        for row in connection.execute(
            text(
                "SELECT v.id, d.title FROM source_version v"
                " JOIN source_document d ON d.id = v.source_document_id WHERE v.id = ANY(:ids)"
            ),
            {"ids": [uuid.UUID(str(each["source_version_id"])) for each in chosen]},
        )
    }
    outcomes = connection.execute(
        text(
            "SELECT outcome, reason_code, count(*) AS n FROM counterevidence"
            " WHERE search_id = :search GROUP BY outcome, reason_code ORDER BY outcome, reason_code"
        ),
        {"search": search["id"]},
    ).all()
    return reading.model_copy(
        update={
            "documents": [
                CardDocumentRead(
                    source_version_id=uuid.UUID(str(each["source_version_id"])),
                    title=titles.get(uuid.UUID(str(each["source_version_id"])), ""),
                    sections=sections.get(str(each["source_version_id"]), []),
                    selected_by=each["selected_by"],
                )
                for each in chosen
            ],
            "documents_dropped": search["documents_dropped"],
            "passages": len(sent),
            "claims_proposed": sum(int(row.n) for row in outcomes),
            "claims_accepted": sum(int(row.n) for row in outcomes if row.outcome == "accepted"),
            "rejected": {
                str(row.reason_code): int(row.n) for row in outcomes if row.outcome == "rejected"
            },
            "documents_fallback": used_fallback(connection, task.id),
        }
    )


def _extractions(connection: Connection, last: Any) -> list[uuid.UUID]:
    """The task's extraction and the budget-exhausted ones it continues, first first."""
    if last is None:
        return []
    return list(
        connection.execute(
            text(
                "WITH RECURSIVE chain AS ("
                " SELECT id, continues_id, 0 AS depth FROM claim_extraction WHERE id = :id"
                " UNION ALL SELECT e.id, e.continues_id, chain.depth + 1 FROM claim_extraction e"
                " JOIN chain ON e.id = chain.continues_id)"
                " SELECT id FROM chain ORDER BY depth DESC"
            ),
            {"id": uuid.UUID(str(last))},
        ).scalars()
    )


def _sent(connection: Connection, chain: list[uuid.UUID]) -> tuple[dict[uuid.UUID, list[str]], int]:
    """The passages the extractions sent the Investigator (the batches done): each Source
    Version's section anchors, in order, each once; and how many passages. (A continuation
    holds the passages its predecessor hadn't sent.)"""
    sections: dict[uuid.UUID, list[str]] = {}
    count = 0
    for extraction_id in chain:
        row = connection.execute(
            text(
                "SELECT passages, batches_done * passages_per_call AS sent"
                " FROM claim_extraction WHERE id = :id"
            ),
            {"id": extraction_id},
        ).one()
        passages: list[dict[str, Any]] = row.passages[: row.sent]
        count += len(passages)
        for passage in passages:
            anchors = sections.setdefault(uuid.UUID(str(passage["source_version_id"])), [])
            if passage["section_anchor"] not in anchors:
                anchors.append(passage["section_anchor"])
    return sections, count
