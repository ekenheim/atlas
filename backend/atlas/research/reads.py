"""The research answer read side: a stored reflect answer with its citation states."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, JsonValue, TypeAdapter
from sqlalchemy import Connection, text

from atlas.jobs.queue import JobStatus
from atlas.research.provenance import (
    Citation,
    CitationState,
    Evidence,
    evidence_from,
    state_counts,
)
from atlas.research.service import AppliedScope

type AnswerStatus = Literal["pending", "running", "completed", "failed"]

_CITATIONS = TypeAdapter(list[Citation])


class ResearchAnswer(BaseModel):
    id: uuid.UUID
    bank_id: str
    # pending/running follow the reflect job; completed/failed are the answer's own, final.
    status: AnswerStatus
    question: str
    scope: AppliedScope
    response_schema: dict[str, JsonValue] | None
    answer: str | None
    structured_output: dict[str, JsonValue] | None
    structured_output_error: str | None
    raw_citations: list[dict[str, JsonValue]] | None  # `based_on.memories` as Hindsight gave it
    citations: list[Citation] | None  # every cited memory, chunk and quote, with its state
    counts: dict[CitationState, int] | None
    evidence: list[Evidence] | None  # the sections behind resolved citations only
    evidence_missing: bool | None  # completed with no resolved citation
    quote_rule: str | None
    run_id: uuid.UUID | None
    job_id: uuid.UUID
    job_status: JobStatus | None
    error: str | None
    created_at: datetime
    answered_at: datetime | None


def research_answer(connection: Connection, answer_id: uuid.UUID) -> ResearchAnswer | None:
    row = (
        connection.execute(
            text(
                "SELECT a.*, j.status AS job_status, j.last_error AS job_error"
                " FROM research_answer a LEFT JOIN job j ON j.id = a.job_id WHERE a.id = :id"
            ),
            {"id": answer_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    citations = None if row["citations"] is None else _CITATIONS.validate_python(row["citations"])
    status: AnswerStatus = row["status"]
    if status == "pending" and row["job_status"] == "running":
        status = "running"
    elif status == "pending" and row["job_status"] == "failed":
        status = "failed"
    evidence = None if citations is None else evidence_from(citations)
    return ResearchAnswer(
        id=row["id"],
        bank_id=row["bank_id"],
        status=status,
        question=row["question"],
        scope=AppliedScope.model_validate(row["scope"]),
        response_schema=row["response_schema"],
        answer=row["answer_text"],
        structured_output=row["structured_output"],
        structured_output_error=row["structured_output_error"],
        raw_citations=row["raw_citations"],
        citations=citations,
        counts=None if citations is None else state_counts(citations),
        evidence=evidence,
        evidence_missing=None if evidence is None else not evidence,
        quote_rule=row["quote_rule"],
        run_id=row["run_id"],
        job_id=row["job_id"],
        job_status=row["job_status"],
        error=row["error"] or (row["job_error"] if status == "failed" else None),
        created_at=row["created_at"],
        answered_at=row["answered_at"],
    )
