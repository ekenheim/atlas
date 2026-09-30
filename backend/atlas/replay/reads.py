"""The read side of replays: `GET /api/v1/replay-jobs[/{id}]`."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import Connection, RowMapping, text

from atlas.replay.questions import ReplayQuestion
from atlas.research.provenance import (
    Citation,
    CitationState,
    Evidence,
    evidence_from,
    state_counts,
)
from atlas.research.service import AppliedScope, RecalledMemory

type ReplayStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
type ReplayStage = Literal[
    "create_bank", "retain", "consolidate", "questions", "delete_bank", "done"
]
type FinalStatus = Literal["completed", "failed", "cancelled"]
type RetainStatus = Literal["pending", "submitted", "completed", "failed"]


class ReplayLeakage(BaseModel):
    """What the replay accepted from after its cutoff: every count must be 0 (§9.2).

    Counted independently of the replay's own section ledger: from the Source Version each
    retained version, recalled memory (its document ID and metadata) and resolved citation
    names, checked against the versions the replay may see.
    """

    retained: int  # retained Source Versions whose availability is now after the cutoff
    recall_memories: int  # recalled memories that lead to a version the replay may not see
    citations: int  # resolved citations (and quotes) that lead to one
    source_version_ids: list[uuid.UUID]  # the versions they led to
    future_accepted: int  # the total


class ReplaySourceVersion(BaseModel):
    """A Source Version the replay may see, in retain order, with its retain's outcome."""

    position: int
    source_version_id: uuid.UUID
    available_at: datetime
    available_at_basis: str
    retain_status: RetainStatus
    operation_id: str | None
    polls: int
    sections: int | None
    facts: int | None
    error: str | None


class ReplayRecalledMemory(RecalledMemory):
    """A recalled memory, with the document and Source Version it names."""

    document_id: str | None
    source_version_id: str | None  # its metadata's, as Hindsight returned it


class AnswerLeakage(BaseModel):
    recall_memories: int
    citations: int
    source_version_ids: list[uuid.UUID]


class ReplayAnswer(BaseModel):
    """One question of the set: its scoped recall, and its reflect with resolved citations."""

    position: int
    question_key: str
    question: str
    recall: list[ReplayRecalledMemory]
    answer_text: str
    citations: list[Citation]
    counts: dict[CitationState, int]  # the answer's citations by state
    evidence: list[Evidence]  # the sections behind resolved citations only
    leakage: AnswerLeakage
    answered_at: datetime


class ReplayConsolidation(BaseModel):
    operation_id: str | None
    status: str  # pending, a terminal operation status, or timed_out
    polls: int


class ReplayJobSummary(BaseModel):
    id: uuid.UUID
    bank_id: str
    cutoff: datetime
    availability_convention: Literal["available_at"]
    company_ids: list[uuid.UUID]
    question_set: str
    question_set_version: str
    status: ReplayStatus
    stage: ReplayStage
    final_status: FinalStatus | None
    eligible_source_versions: int  # available at the cutoff, before the cap
    max_source_versions: int
    selected_source_versions: int
    leakage: ReplayLeakage | None  # once the questions are answered
    error: str | None
    job_id: uuid.UUID
    requested_by: str
    cancel_requested_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    bank_deleted_at: datetime | None
    bank_delete_error: str | None


class ReplayJob(ReplayJobSummary):
    scope: AppliedScope
    question_set_sha256: str
    questions: list[ReplayQuestion]
    template_version: str | None
    template_manifest_sha256: str | None
    consolidation: ReplayConsolidation | None
    source_versions: list[ReplaySourceVersion]
    answers: list[ReplayAnswer]


_RECALL = TypeAdapter(list[ReplayRecalledMemory])
_CITATIONS = TypeAdapter(list[Citation])
_QUESTIONS = TypeAdapter(list[ReplayQuestion])

_SUMMARY_SQL = (
    "SELECT r.*, (SELECT count(*) FROM replay_source_version s"
    "  WHERE s.replay_job_id = r.id) AS selected_source_versions FROM replay_job r"
)


def list_replays(
    connection: Connection, *, limit: int, offset: int
) -> tuple[list[ReplayJobSummary], int]:
    """Replays, newest first."""
    total = connection.execute(text("SELECT count(*) FROM replay_job")).scalar_one()
    rows = connection.execute(
        text(f"{_SUMMARY_SQL} ORDER BY r.created_at DESC, r.id DESC LIMIT :limit OFFSET :offset"),
        {"limit": limit, "offset": offset},
    ).mappings()
    return [ReplayJobSummary.model_validate(_summary(row)) for row in rows], total


def get_replay(connection: Connection, replay_id: uuid.UUID) -> ReplayJob | None:
    row = (
        connection.execute(text(f"{_SUMMARY_SQL} WHERE r.id = :id"), {"id": replay_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    versions = connection.execute(
        text("SELECT * FROM replay_source_version WHERE replay_job_id = :id ORDER BY position"),
        {"id": replay_id},
    ).mappings()
    answers = connection.execute(
        text("SELECT * FROM replay_answer WHERE replay_job_id = :id ORDER BY position"),
        {"id": replay_id},
    ).mappings()
    return ReplayJob.model_validate(
        _summary(row)
        | {
            "scope": row["scope"],
            "question_set_sha256": row["question_set_sha256"],
            "questions": _QUESTIONS.validate_python(row["questions"]),
            "template_version": row["template_version"],
            "template_manifest_sha256": row["template_manifest_sha256"],
            "consolidation": row["consolidation"],
            "source_versions": [ReplaySourceVersion.model_validate(dict(v)) for v in versions],
            "answers": [_answer(answer) for answer in answers],
        }
    )


def _summary(row: RowMapping) -> dict[str, Any]:
    fields = set(ReplayJobSummary.model_fields)
    return {key: value for key, value in row.items() if key in fields}


def _answer(row: RowMapping) -> ReplayAnswer:
    citations = _CITATIONS.validate_python(row["citations"])
    return ReplayAnswer(
        position=row["position"],
        question_key=row["question_key"],
        question=row["question"],
        recall=_RECALL.validate_python(row["recall"]),
        answer_text=row["answer_text"],
        citations=citations,
        counts=state_counts(citations),
        evidence=evidence_from(citations),
        leakage=AnswerLeakage.model_validate(row["leakage"]),
        answered_at=row["answered_at"],
    )
