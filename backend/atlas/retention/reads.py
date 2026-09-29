"""The retention read side: a Source Version's memory documents and their operations."""

import uuid
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel
from sqlalchemy import Connection, text

RetainState = Literal["pending", "completed", "failed", "zero_fact", "linked"]
RETAIN_STATES: tuple[RetainState, ...] = get_args(RetainState)


class MemoryOperation(BaseModel):
    """A Hindsight operation that retained (or reprocessed) some of the version's sections."""

    id: str
    kind: str
    status: str
    error_message: str | None
    # A failure's class: quota/unavailable paused the queue and resubmit; permanent fails.
    error_class: Literal["quota", "unavailable", "permanent"] | None
    retry_count: int
    document_ids: list[str]
    submitted_at: datetime
    last_polled_at: datetime | None
    completed_at: datetime | None


class MemoryDocument(BaseModel):
    """One section of the Source Version, as retained (or linked) into the bank."""

    section_anchor: str
    section_heading: str | None
    char_start: int
    char_end: int
    sectioner_version: str
    document_id: str | None  # the Hindsight document ID; None when linked
    retain_state: RetainState
    fact_count: int | None
    # The IDs of the memories Hindsight extracted from the section, listed once its operation
    # completed; None until then, and for a linked or failed section.
    memory_ids: list[str] | None
    reprocess_count: int
    template_version: str
    operation_id: str | None
    linked_to_source_version_id: uuid.UUID | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class SourceVersionMemory(BaseModel):
    source_version_id: uuid.UUID
    bank_id: str
    retained: bool  # any memory documents recorded (retained or linked)
    linked_to_source_version_id: uuid.UUID | None
    counts: dict[RetainState, int]  # memory documents by retain state
    fact_count: int  # memories counted across the version's completed sections
    documents: list[MemoryDocument]
    operations: list[MemoryOperation]


def source_version_memory(
    connection: Connection, source_version_id: uuid.UUID, bank_id: str
) -> SourceVersionMemory | None:
    """None when the Source Version doesn't exist."""
    exists = connection.execute(
        text("SELECT 1 FROM source_version WHERE id = :id"), {"id": source_version_id}
    ).scalar_one_or_none()
    if exists is None:
        return None
    documents = [
        MemoryDocument.model_validate({**row, "document_id": row["hindsight_document_id"]})
        for row in connection.execute(
            text(
                "SELECT * FROM memory_document WHERE source_version_id = :id AND bank_id = :bank"
                " ORDER BY char_start, section_anchor"
            ),
            {"id": source_version_id, "bank": bank_id},
        ).mappings()
    ]
    operations = [
        MemoryOperation.model_validate(dict(row))
        for row in connection.execute(
            text(
                "SELECT * FROM hindsight_operation WHERE source_version_id = :id"
                " AND bank_id = :bank ORDER BY submitted_at, id"
            ),
            {"id": source_version_id, "bank": bank_id},
        ).mappings()
    ]
    counts: dict[RetainState, int] = dict.fromkeys(RETAIN_STATES, 0)
    for document in documents:
        counts[document.retain_state] += 1
    linked_to = {d.linked_to_source_version_id for d in documents} - {None}
    return SourceVersionMemory(
        source_version_id=source_version_id,
        bank_id=bank_id,
        retained=bool(documents),
        linked_to_source_version_id=next(iter(linked_to)) if len(linked_to) == 1 else None,
        counts=counts,
        fact_count=sum(d.fact_count or 0 for d in documents if d.retain_state == "completed"),
        documents=documents,
        operations=operations,
    )
