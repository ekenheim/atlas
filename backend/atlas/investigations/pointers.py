"""Reading pointers: Memory as the reading index of an investigation (memory-directed reading
ticket 01; docs/decisions.md, "Memory as the reading index").

Once the Scout has its queries, the investigation asks Memory each of them, and the round's
question, across the theme: one scoped recall each (atlas.research; no LLM call, counted
against no budget; at most the query budget plus one). Every recalled memory whose provenance
**resolves** becomes one reading pointer per Source Version section it resolves to: this
query, this memory at this rank of the recall, this section, this company. An observation
points at the sections of the facts it was consolidated from. A section of a Source Version
that became available after the investigation's as-of time makes none, and neither does an
unverified or broken memory.

A pointer is Memory used as an index. It says where to read; it is never Evidence, never
quoted, never a witness, and never sent to a role as a statement. An Investigator's passages
are chosen by the Scout's pointers of its round (`round_reading`; atlas.claims.selection,
ticket 05): the pointer's Memory text finds the window of the pointed section to read and
goes no further. Companies and documents are not chosen by them yet (ticket 06).

**The Skeptic's pointers** (ticket 07; atlas.investigations.skeptic) are stored the same way,
by its own task: one recall per bear-checklist item for each company the accepted Claims name
(`query_kind` `bear_checklist`, with the `checklist_item` and the company asked about,
`query_company_id`; `query_index` the query's position among the task's, from 1). The
Scout's are `query_kind` `scout`. `skeptic_pointers` reads a Skeptic task's; an Investigator
is never given them.

**Stored** insert-only (`reading_pointer`), a task's whole set in one transaction together
with its events, its counts in the task's artifacts and one audit event
(`investigation.pointers_recorded`, by the asking role's actor, `atlas-scout` or
`atlas-skeptic`, its hash over the rows). A later attempt of the task finds the counts
recorded and asks nothing again.

**Failures.** A recall that fails for a reason of its own (an HTTP error that is neither a
quota nor an outage, an answer off the contract) is recorded as a `pointer_recall_failed`
event and the other queries proceed: the pointers are fewer. A quota or outage failure is
re-raised before anything is stored, so the task pauses with the queue like any
Hindsight-backed job and asks again when it lifts. The `pointers_recorded` event names the
queries that gave no pointer.
"""

import json
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import JsonValue
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.audit import Actor, content_hash, record
from atlas.claims.selection import Pointer, Reading
from atlas.hindsight import HindsightError
from atlas.investigations.service import event, lock
from atlas.jobs.pacing import classify_failure
from atlas.research.service import RecallResponse

SCOUT_ACTOR = Actor("atlas-scout")
# `query_index` of the round's question; the Scout's queries follow, by position (from 1).
QUESTION_INDEX = 0
# What a pointer's query was: the Scout's (the question or one of its queries), or a
# Skeptic's bear-checklist query about a company.
type QueryKind = Literal["scout", "bear_checklist"]
SCOUT_QUERY: QueryKind = "scout"
BEAR_CHECKLIST_QUERY: QueryKind = "bear_checklist"
# A recall's query is at most this long (atlas.research.service.RecallRequest).
MAX_QUERY_CHARS = 4000
# The task artifact that says its pointers are recorded.
_RECORDED = "pointer_recalls"
_NO_COMPANY = "(none)"
_ERROR_LIMIT = 500

# The theme-scoped recall of a query, each memory with its provenance.
Recall = Callable[[str], RecallResponse]


@dataclass(frozen=True)
class PointerQuery:
    index: int  # QUESTION_INDEX, or the query's position among its task's (from 1)
    text: str
    discovery_query_id: uuid.UUID | None = None  # a Scout query's; None otherwise
    kind: QueryKind = SCOUT_QUERY
    # A bear-checklist query's item and the company it asks about; None for a Scout's.
    checklist_item: str | None = None
    company_id: uuid.UUID | None = None


def scout_queries(
    connection: Connection, discovery_id: uuid.UUID, question: str
) -> list[PointerQuery]:
    """What a Scout task asks Memory: the round's question, then its discovery's queries."""
    rows = connection.execute(
        text(
            "SELECT id, position, query FROM discovery_query WHERE discovery_id = :discovery"
            " ORDER BY position"
        ),
        {"discovery": discovery_id},
    )
    return [
        PointerQuery(QUESTION_INDEX, question),
        *(PointerQuery(row.position, row.query, row.id) for row in rows),
    ]


def round_reading(
    connection: Connection,
    investigation_id: uuid.UUID,
    round_: int,
    source_version_ids: Sequence[uuid.UUID],
) -> Reading:
    """What directs an Investigator's reading of these Source Versions in a round of the
    investigation (atlas.claims.selection): the reading pointers the round's Scout recorded
    into them (the question's and its queries'; never a Skeptic's bear-checklist pointers,
    which direct the Skeptic's own reading), best rank first; and the queries of the round's
    Scout, in order, which the search selection uses beside the round's question."""
    pointers = [
        Pointer(
            source_version_id=row.source_version_id,
            section_anchor=row.section_anchor,
            rank=row.rank,
            query_index=row.query_index,
            memory_text=row.memory_text,
        )
        for row in connection.execute(
            text(
                "SELECT source_version_id, section_anchor, rank, query_index, memory_text"
                " FROM reading_pointer WHERE investigation_id = :id AND round = :round"
                " AND query_kind = :kind AND source_version_id = ANY(:versions)"
                " ORDER BY rank, query_index, source_version_id, section_char_start,"
                " section_anchor, id"
            ),
            {
                "id": investigation_id,
                "round": round_,
                "kind": SCOUT_QUERY,
                "versions": list(source_version_ids),
            },
        )
    ]
    queries = list(
        connection.execute(
            text(
                "SELECT q.query FROM investigation_task t JOIN discovery_query q"
                " ON q.discovery_id = CAST(t.artifacts ->> 'discovery_id' AS uuid)"
                " WHERE t.investigation_id = :id AND t.round = :round AND t.role = 'scout'"
                " ORDER BY t.position, q.position"
            ),
            {"id": investigation_id, "round": round_},
        ).scalars()
    )
    return Reading(pointers=pointers, queries=queries)


@dataclass(frozen=True)
class SkepticPointer:
    """A reading pointer of a Skeptic task: where Memory pointed for a bear-checklist item
    asked about a company (`query_company_id`), and whose document that is (`company_id`)."""

    source_version_id: uuid.UUID
    section_anchor: str
    rank: int
    query_index: int
    memory_text: str  # finds the window; never quoted and never sent to a role
    checklist_item: str
    query_company_id: uuid.UUID
    company_id: uuid.UUID | None


def skeptic_pointers(connection: Connection, task_id: uuid.UUID) -> list[SkepticPointer]:
    """The reading pointers a Skeptic task recorded, best rank first (then the earlier
    query: the companies in the task's order, each in checklist order)."""
    return [
        SkepticPointer(**dict(row))
        for row in connection.execute(
            text(
                "SELECT source_version_id, section_anchor, rank, query_index, memory_text,"
                " checklist_item, query_company_id, company_id FROM reading_pointer"
                " WHERE task_id = :task AND query_kind = :kind"
                " ORDER BY rank, query_index, source_version_id, section_char_start,"
                " section_anchor, id"
            ),
            {"task": task_id, "kind": BEAR_CHECKLIST_QUERY},
        ).mappings()
    ]


def record_pointers(
    engine: Engine,
    recall: Recall,
    investigation: RowMapping,
    task: RowMapping,
    queries: Sequence[PointerQuery],
    *,
    actor: Actor = SCOUT_ACTOR,
) -> dict[str, JsonValue]:
    """Ask Memory each query and store the task's reading pointers (see the module); returns
    the task's pointer artifacts. A task whose pointers are recorded asks nothing. `actor`
    is the asking role's, for the audit event (the Scout's by default)."""
    recorded = _recorded(task["artifacts"])
    if recorded is not None:
        return recorded
    as_of: datetime = investigation["as_of"]
    rows: list[dict[str, Any]] = []
    failed: list[tuple[PointerQuery, str]] = []
    without: list[str] = []
    memories = unresolved = later = 0
    for query in queries:
        try:
            response = recall(query.text[:MAX_QUERY_CHARS])
        except HindsightError as error:
            if classify_failure(error) is not None:
                raise  # a quota or an outage: the queue pauses and the task asks again
            failed.append((query, f"{type(error).__name__}: {error}"[:_ERROR_LIMIT]))
            continue
        found = _resolved(investigation, task, query, response, as_of)
        memories += len(response.memories)
        unresolved += found.unresolved
        later += found.later
        rows.extend(found.rows)
        if not found.rows:
            without.append(query.text)
    with engine.begin() as connection:
        lock(connection, investigation["id"])
        recorded = _recorded(
            connection.execute(
                text("SELECT artifacts FROM investigation_task WHERE id = :id"), {"id": task["id"]}
            ).scalar_one()
        )
        if recorded is not None:
            return recorded  # by an earlier attempt
        if rows:
            connection.execute(text(_INSERT), rows)
        artifacts: dict[str, JsonValue] = {
            "pointer_recalls": len(queries),
            "pointer_recalls_failed": len(failed),
            "memories_recalled": memories,
            "memories_unresolved": unresolved,
            "sections_after_as_of": later,
            "pointers": len(rows),
            "pointers_by_company": _by_company(connection, rows),
        }
        for query, error in failed:
            event(
                connection,
                investigation["id"],
                "pointer_recall_failed",
                round=task["round"],
                task_key=task["key"],
                query_index=query.index,
                query=query.text,
                error=error,
            )
        event(
            connection,
            investigation["id"],
            "pointers_recorded",
            round=task["round"],
            task_key=task["key"],
            **artifacts,
            queries_without_pointers=list[JsonValue](without),
        )
        connection.execute(
            text(
                "UPDATE investigation_task SET artifacts = artifacts || CAST(:new AS jsonb)"
                " WHERE id = :id"
            ),
            {"id": task["id"], "new": json.dumps(artifacts)},
        )
        if rows:
            record(
                connection,
                actor,
                "investigation.pointers_recorded",
                entity_type="investigation_task",
                entity_id=str(task["id"]),
                new_hash=content_hash({"pointers": rows}),
            )
    return artifacts


_COLUMNS = (
    "id, investigation_id, round, task_id, query_index, query, discovery_query_id, rank,"
    " memory_id, memory_type, memory_text, source_version_id, section_anchor, section_heading,"
    " section_char_start, section_char_end, company_id, available_at, citation_state,"
    " query_kind, checklist_item, query_company_id"
)
_INSERT = (
    f"INSERT INTO reading_pointer ({_COLUMNS}) VALUES ("  # noqa: S608 (constant SQL)
    + ", ".join(f":{column.strip()}" for column in _COLUMNS.split(","))
    + ")"
)


@dataclass
class _Found:
    rows: list[dict[str, Any]]
    unresolved: int = 0  # memories whose provenance is unverified or broken
    later: int = 0  # sections of Source Versions available only after the as-of time


def _resolved(
    investigation: RowMapping,
    task: RowMapping,
    query: PointerQuery,
    response: RecallResponse,
    as_of: datetime,
) -> _Found:
    """The recall's pointers: one per resolved memory and section available by `as_of`."""
    found = _Found(rows=[])
    for rank, memory in enumerate(response.memories, start=1):
        citation = memory.provenance
        if citation.state != "resolved":
            found.unresolved += 1
            continue
        seen: set[tuple[uuid.UUID, str]] = set()
        for source in citation.sources:
            section = (source.source_version_id, source.section_anchor)
            if section in seen:
                continue  # an observation's facts from one section point there once
            seen.add(section)
            if source.available_at > as_of:
                found.later += 1
                continue
            found.rows.append(
                {
                    "id": uuid.uuid4(),
                    "investigation_id": investigation["id"],
                    "round": task["round"],
                    "task_id": task["id"],
                    "query_index": query.index,
                    "query": query.text,
                    "discovery_query_id": query.discovery_query_id,
                    "rank": rank,
                    "memory_id": memory.memory_id,
                    "memory_type": memory.type,
                    "memory_text": memory.text,
                    "source_version_id": source.source_version_id,
                    "section_anchor": source.section_anchor,
                    "section_heading": source.section_heading,
                    "section_char_start": source.section_char_start,
                    "section_char_end": source.section_char_end,
                    "company_id": source.company_id,
                    "available_at": source.available_at,
                    "citation_state": citation.state,
                    "query_kind": query.kind,
                    "checklist_item": query.checklist_item,
                    "query_company_id": query.company_id,
                }
            )
    return found


def _by_company(connection: Connection, rows: Sequence[Mapping[str, Any]]) -> dict[str, JsonValue]:
    """How many pointers name each company, by slug."""
    counts = Counter[uuid.UUID | None](row["company_id"] for row in rows)
    slugs = {
        row.id: row.slug
        for row in connection.execute(
            text("SELECT id, slug FROM company WHERE id = ANY(:ids)"),
            {"ids": [each for each in counts if each is not None]},
        )
    }
    return {
        slugs.get(company, str(company)) if company is not None else _NO_COMPANY: count
        for company, count in counts.most_common()
    }


def _recorded(artifacts: Mapping[str, Any]) -> dict[str, JsonValue] | None:
    """The task's pointer artifacts, once recorded."""
    if _RECORDED not in artifacts:
        return None
    return {key: value for key, value in artifacts.items() if key in _ARTIFACTS}


_ARTIFACTS = frozenset(
    {
        "pointer_recalls",
        "pointer_recalls_failed",
        "memories_recalled",
        "memories_unresolved",
        "sections_after_as_of",
        "pointers",
        "pointers_by_company",
    }
)
