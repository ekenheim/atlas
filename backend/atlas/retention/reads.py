"""The retention read side: a Source Version's memory documents and their operations."""

import uuid
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel
from sqlalchemy import Connection, text

# `cancelled`: the section's operation was cancelled (by the owner) before Hindsight stored
# it; not a failure, and `atlas retention retry-failed` enqueues it again (ticket 03).
RetainState = Literal["pending", "completed", "failed", "zero_fact", "linked", "cancelled"]
RETAIN_STATES: tuple[RetainState, ...] = get_args(RetainState)
# Why a failed or cancelled section is not in memory.
SectionErrorClass = Literal["cancelled", "permanent", "transient", "missing"]


class MemoryOperation(BaseModel):
    """A Hindsight operation that retained (or reprocessed) some of the version's sections."""

    id: str
    kind: str
    status: str
    error_message: str | None
    # A failure's class: quota/unavailable/transient paused the queue and resubmit (transient
    # a bounded number of times); permanent fails the sections it did not store; cancelled
    # leaves them cancelled.
    error_class: Literal["quota", "unavailable", "transient", "cancelled", "permanent"] | None
    retry_count: int
    document_ids: list[str]
    # The extractor its items asked Hindsight for (ATLAS_RETAIN_EXTRACTOR when it was
    # submitted); None: none, so Hindsight's primary LLM extracted them.
    extractor: str | None
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
    # The extractor Atlas asked Hindsight for when it last submitted the section (a
    # reprocess or a resubmission records its own); None: none (the primary), and for a
    # section never submitted (linked, or still awaiting its first batch). It is what Atlas
    # asked for, not what Hindsight did: Hindsight stores nothing about the route.
    extractor: str | None
    template_version: str
    operation_id: str | None
    linked_to_source_version_id: uuid.UUID | None
    error: str | None
    # Why a failed or cancelled section is not in memory (None for every other state):
    # cancelled, permanent, transient (retried past the bound) or missing (its document is
    # absent after its operation completed).
    error_class: SectionErrorClass | None
    # How many times its operation ended with a transient error since it was last reset.
    transient_retries: int
    # The extraction_errors_count Hindsight reported on the operation that stored the section
    # (None: none read). A completed section with a count above zero is partial: its
    # extraction lost something even after its one retry.
    extraction_errors: int | None
    partial: bool
    created_at: datetime
    updated_at: datetime


class SourceVersionMemory(BaseModel):
    source_version_id: uuid.UUID
    bank_id: str
    retained: bool  # any memory documents recorded (retained or linked)
    linked_to_source_version_id: uuid.UUID | None
    counts: dict[RetainState, int]  # memory documents by retain state
    partial: int  # completed sections whose extraction reported errors after their retry
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
        MemoryDocument.model_validate(
            {
                **row,
                "document_id": row["hindsight_document_id"],
                "partial": row["retain_state"] == "completed"
                and (row["extraction_errors"] or 0) > 0,
            }
        )
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
        partial=sum(1 for d in documents if d.partial),
        fact_count=sum(d.fact_count or 0 for d in documents if d.retain_state == "completed"),
        documents=documents,
        operations=operations,
    )
