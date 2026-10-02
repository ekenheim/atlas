"""What an investigation searched and read, for its research card (pilot fix 01).

Written by code, never the Editor, so a card with no finding still says, from the records:

- **searched:** each round's Scout, its queries (in order), how many leads they found, and
  the leads the investigation took (Tier C, never Evidence);
- **read:** each Investigator task, the Source Versions it read with the sections of the
  passages it was sent (across a budget-exhausted extraction and its continuation), how
  many passages of each (pilot fix 10) and in all, how each document's passages were
  selected (pointer, search, entity, lead; memory-directed reading ticket 05), which
  documents its document floor chose (`floor`; pilot fix 24), the documents the budget left
  out, and
  the extraction's outcomes: Claims proposed, accepted, and rejected by reason code; or why
  it read nothing. Then (pilot fix 06) each round's Skeptic, the same way: the Source
  Versions it read (each with who chose it: its reading pointers, its search or code's
  fallback; memory-directed reading ticket 07), the sections of the passages it was sent
  and how each document's passages were selected (pointer, search, lead), whether Memory
  pointed at nothing of a company the Claims name, and its counterevidence items (of either
  kind) proposed, accepted and rejected by reason code; or why it read nothing (skipped with
  no Claim to challenge, the budget spent, nothing archived).
- **not_read** (memory-directed reading ticket 06): the companies a round's reading pointers
  name that got no Investigator, with their pointers and why (the company budget had no
  room, or the company's premise was disproven), so the next investigation can seed them;
  with the channels that reached each (`recall`, `entity`: the entity hop, memory-quality
  ticket 09). A document's `selections` in `read` count `entity_pointer` passages apart.
- **skeptic_coverage** (pilot-fixes ticket 25, the disclosure part): for each researched
  company the accepted Claims name, whether the Skeptic was sent a passage of one of its
  documents (`checked`, with the documents and passages and the counterevidence items it
  accepted about the company) or not (`not_checked`, with a reason code and the reason in
  words: it did not run, the document budget was spent, Memory pointed only at Tier B
  documents, it has no Tier A document, or none of its documents was chosen). It changes
  nothing the Skeptic reads.
"""

import uuid
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy import Connection, Row, RowMapping, text

from atlas.claims.selection import placements, selections
from atlas.investigations.companies import COMPANY_BUDGET, POINTED_COMPANIES, not_read_reason
from atlas.investigations.model import (
    CardCompanyNotRead,
    CardDocumentRead,
    CardQuery,
    CardReading,
    CardSearch,
    CardSkepticCompany,
    CardSkepticDocument,
)
from atlas.investigations.skeptic import WITNESS_TIER, used_fallback


def coverage(
    connection: Connection, investigation_id: uuid.UUID
) -> tuple[list[CardSearch], list[CardReading]]:
    """The investigation's `searched` and `read` sections, every round, in plan order."""
    return _searched(connection, investigation_id), _read(connection, investigation_id)


def not_read(connection: Connection, investigation_id: uuid.UUID) -> list[CardCompanyNotRead]:
    """The card's `not_read` section: the companies each round's reading pointers name that
    got no Investigator (the company budget had no room, or its premise was disproven), as
    the round's Scout task recorded them when the plan grew; rounds in order, best ranked
    first."""
    scouts = connection.execute(
        text(
            "SELECT round, artifacts FROM investigation_task WHERE investigation_id = :id"
            " AND role = 'scout' ORDER BY round, position"
        ),
        {"id": investigation_id},
    ).all()
    unread: list[CardCompanyNotRead] = []
    for scout in scouts:
        artifacts: dict[str, Any] = scout.artifacts
        budget = int(artifacts.get(COMPANY_BUDGET) or 0)
        ranked: list[dict[str, Any]] = artifacts.get(POINTED_COMPANIES) or []
        for each in ranked:
            reason = not_read_reason(each, budget)
            if reason is not None:
                unread.append(
                    CardCompanyNotRead(
                        round=scout.round,
                        company_id=uuid.UUID(str(each["company_id"])),
                        company_name=each["company_name"],
                        pointers=each["pointers"],
                        score=each["score"],
                        best_rank=each["best_rank"],
                        reason=reason,
                        # The channels that reached it (memory-quality ticket 09).
                        entity_pointers=int(each.get("entity_pointers") or 0),
                        channels=[
                            *(["recall"] if each["pointers"] else []),
                            *(["entity"] if each.get("entity_pointers") else []),
                        ],
                    )
                )
    return unread


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
        sections, per_document, selected, sent = _sent(connection, chain)
        placed = _placed(connection, chain)
        recorded: list[Any] = artifacts.get("documents_floor") or []
        floor = {str(each) for each in recorded}
        documents = [
            CardDocumentRead(
                source_version_id=row.source_version_id,
                title=row.title,
                sections=sections.get(row.source_version_id, []),
                passages=per_document.get(row.source_version_id, 0),
                selections=selected.get(row.source_version_id, {}),
                pointers_placed_by=placed.get(row.source_version_id, {}),
                floor=str(row.source_version_id) in floor,
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
    per_document: dict[str, int] = {}
    selected: dict[str, dict[str, int]] = {}
    placed: dict[str, dict[str, int]] = {}
    for passage in sent:
        key = str(passage["source_version_id"])
        per_document[key] = per_document.get(key, 0) + 1
        anchors = sections.setdefault(key, [])
        if passage["section_anchor"] not in anchors:
            anchors.append(passage["section_anchor"])
        kinds = selected.setdefault(key, {})
        for kind in selections(passage.get("selected_by") or []):
            kinds[kind] = kinds.get(kind, 0) + 1
        rules = placed.setdefault(key, {})
        for rule in placements(passage.get("selected_by") or []):
            rules[rule] = rules.get(rule, 0) + 1
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
                    passages=per_document.get(str(each["source_version_id"]), 0),
                    selections=selected.get(str(each["source_version_id"]), {}),
                    pointers_placed_by=placed.get(str(each["source_version_id"]), {}),
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


_NotChecked = Literal[
    "skeptic_not_run", "no_budget", "only_tier_b_pointed", "no_document", "not_chosen"
]


def skeptic_coverage(
    connection: Connection, investigation: RowMapping, claims: Sequence[RowMapping]
) -> list[CardSkepticCompany]:
    """The card's `skeptic_coverage`: a row for each researched company the accepted `claims`
    name (as subject or object; a counterparty is not challenged), in the Claims' order, from
    the Skeptic's own records of every round. A company is `checked` when the Skeptic was
    sent a passage of one of its documents."""
    named: dict[uuid.UUID, int] = {}
    for claim in claims:
        for key in ("subject_company_id", "object_company_id"):
            if claim[key] is not None:
                named[claim[key]] = named.get(claim[key], 0) + 1
    if not named:
        return []
    names = {
        row.id: row.display_name
        for row in connection.execute(
            text(
                "SELECT id, display_name FROM company WHERE id = ANY(:ids) AND role = 'researched'"
            ),
            {"ids": list(named)},
        )
    }
    searches = (
        connection.execute(
            text(
                "SELECT s.passages, s.batches_done, s.passages_per_call, s.documents_dropped"
                " FROM skeptic_search s JOIN investigation_task t ON t.id = s.task_id"
                " WHERE s.investigation_id = :id ORDER BY t.round"
            ),
            {"id": investigation["id"]},
        )
        .mappings()
        .all()
    )
    per_version: dict[uuid.UUID, int] = {}
    for search in searches:
        sent: list[dict[str, Any]] = search["passages"][
            : search["batches_done"] * search["passages_per_call"]
        ]
        for passage in sent:
            key = uuid.UUID(str(passage["source_version_id"]))
            per_version[key] = per_version.get(key, 0) + 1
    read: dict[uuid.UUID, list[CardSkepticDocument]] = {}
    for row in connection.execute(
        text(
            "SELECT v.id, d.company_id, d.title FROM source_version v"
            " JOIN source_document d ON d.id = v.source_document_id WHERE v.id = ANY(:ids)"
            " ORDER BY v.available_at DESC, v.id"
        ),
        {"ids": list(per_version)},
    ):
        if row.company_id is not None:
            read.setdefault(row.company_id, []).append(
                CardSkepticDocument(
                    source_version_id=row.id, title=row.title, passages=per_version[row.id]
                )
            )
    items = {
        (row.subject_company_id, row.kind): int(row.n)
        for row in connection.execute(
            text(
                "SELECT subject_company_id, kind, count(*) AS n FROM counterevidence"
                " WHERE investigation_id = :id AND outcome = 'accepted'"
                " GROUP BY subject_company_id, kind"
            ),
            {"id": investigation["id"]},
        )
    }
    tier_a = set(
        connection.execute(
            text(
                "SELECT DISTINCT d.company_id FROM source_version v"
                " JOIN source_document d ON d.id = v.source_document_id"
                " WHERE d.company_id = ANY(:ids) AND d.source_tier = :tier"
                " AND d.source_type <> 'xbrl_companyfacts' AND v.available_at <= :as_of"
                " AND v.parse_status IN ('parsed', 'incomplete')"
                " AND v.parsed_object_uri IS NOT NULL"
            ),
            {"ids": list(named), "tier": WITNESS_TIER, "as_of": investigation["as_of"]},
        ).scalars()
    )
    tier_b = set(
        connection.execute(
            text(
                "SELECT DISTINCT p.company_id FROM reading_pointer p"
                " JOIN investigation_task t ON t.id = p.task_id AND t.role = 'skeptic'"
                " JOIN source_version v ON v.id = p.source_version_id"
                " JOIN source_document d ON d.id = v.source_document_id"
                " WHERE p.investigation_id = :id AND p.company_id = ANY(:ids)"
                " AND d.source_tier <> :tier"
            ),
            {"id": investigation["id"], "ids": list(named), "tier": WITNESS_TIER},
        ).scalars()
    )
    skeptic = connection.execute(
        text(
            "SELECT status, detail FROM investigation_task WHERE investigation_id = :id"
            " AND role = 'skeptic' ORDER BY round DESC, position LIMIT 1"
        ),
        {"id": investigation["id"]},
    ).one_or_none()
    dropped = sum(int(search["documents_dropped"]) for search in searches)
    covered: list[CardSkepticCompany] = []
    for company_id in (each for each in named if each in names):
        documents = read.get(company_id, [])
        shared: dict[str, Any] = {
            "company_id": company_id,
            "company_name": names[company_id],
            "claims": named[company_id],
            "documents": documents,
            "passages": sum(each.passages for each in documents),
            "contradictions": items.get((company_id, "contradiction"), 0),
            "bear_context": items.get((company_id, "bear_context"), 0),
        }
        if documents:
            covered.append(CardSkepticCompany(outcome="checked", **shared))
            continue
        also_b = (
            "; Memory also pointed at Tier B documents of it (transcripts), which the Skeptic"
            " does not read"
            if company_id in tier_b
            else ""
        )
        code: _NotChecked
        if not searches:
            code = "skeptic_not_run"
            why = ""
            if skeptic is not None:
                why = f" ({skeptic.status}{': ' + skeptic.detail if skeptic.detail else ''})"
            reason = f"the Skeptic did not run{why}"
        elif company_id in tier_a and dropped:
            code = "no_budget"
            reason = (
                f"the document budget ({investigation['max_documents']}) was spent and {dropped}"
                f" documents were left out; none of this company's was read{also_b}"
            )
        elif company_id in tier_a:
            code = "not_chosen"
            reason = f"none of its archived Tier A documents was chosen for the Skeptic{also_b}"
        elif company_id in tier_b:
            code = "only_tier_b_pointed"
            reason = (
                "Memory pointed only at Tier B documents of it (transcripts), which the Skeptic"
                " does not read, and it has no archived Tier A document"
            )
        else:
            code = "no_document"
            as_of = investigation["as_of"].isoformat()
            reason = f"it has no parsed Tier A document archived as of {as_of}"
        covered.append(
            CardSkepticCompany(outcome="not_checked", reason_code=code, reason=reason, **shared)
        )
    return covered


def unchecked_note(covered: Sequence[CardSkepticCompany]) -> str | None:
    """The stop detail's clause for the companies the Skeptic did not check, or None when it
    checked every one. It never says a company was checked."""
    missed = [each.company_name for each in covered if each.outcome == "not_checked"]
    if not missed:
        return None
    return (
        f"the Skeptic did not check {', '.join(missed)}, so nothing said of"
        f" {'it' if len(missed) == 1 else 'them'} was challenged (see the card's skeptic_coverage)"
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


def _sent(
    connection: Connection, chain: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, list[str]], dict[uuid.UUID, int], dict[uuid.UUID, dict[str, int]], int]:
    """The passages the extractions sent the Investigator (the batches done): each Source
    Version's section anchors, in order, each once, its passage count, and its passages per
    kind of selection (pointer, search, entity, lead: a passage counts under each kind that
    chose it); and how many passages in all. (A continuation holds the passages its
    predecessor hadn't sent.)"""
    sections: dict[uuid.UUID, list[str]] = {}
    per_document: dict[uuid.UUID, int] = {}
    selected: dict[uuid.UUID, dict[str, int]] = {}
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
            version_id = uuid.UUID(str(passage["source_version_id"]))
            anchors = sections.setdefault(version_id, [])
            if passage["section_anchor"] not in anchors:
                anchors.append(passage["section_anchor"])
            per_document[version_id] = per_document.get(version_id, 0) + 1
            kinds = selected.setdefault(version_id, {})
            for kind in selections(passage.get("selected_by") or []):
                kinds[kind] = kinds.get(kind, 0) + 1
    return sections, per_document, selected, count


def _placed(connection: Connection, chain: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """Of the passages the extractions sent, how the pointers that chose them were placed,
    per Source Version: passages per rule (`chunk`, `match`; memory-quality ticket 08)."""
    placed: dict[uuid.UUID, dict[str, int]] = {}
    for extraction_id in chain:
        row = connection.execute(
            text(
                "SELECT passages, batches_done * passages_per_call AS sent"
                " FROM claim_extraction WHERE id = :id"
            ),
            {"id": extraction_id},
        ).one()
        for passage in row.passages[: row.sent]:
            rules = placed.setdefault(uuid.UUID(str(passage["source_version_id"])), {})
            for rule in placements(passage.get("selected_by") or []):
                rules[rule] = rules.get(rule, 0) + 1
    return placed
