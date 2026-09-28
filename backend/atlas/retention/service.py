"""The retention service: the bridge from the source ledger to Memory (spec Part B).

Three jobs carry a Source Version into the research bank:

1. `retain` (payload `{"source_version_id"}`), enqueued for each new parsed Source Version.
   If a Source Version with the same raw bytes is already retained in the bank, it records
   `linked` sections pointing at that one and stops (ADR-0001). Otherwise it splits the
   parse into sections (`atlas.retention.sections`), records each as a `pending` memory
   document with the ID `srcv:<source_version_uuid>:<section-anchor>`, and submits them as
   **one** batch. The operation is recorded and a `poll_operation` job follows it.
2. `poll_operation` (`{"operation_id"}`) waits for the operation's `status` (the only basis
   for an outcome) with a timeout. A timeout fails the attempt, so it is retried; a failed
   operation marks its sections `failed` with the error. On completion it counts each
   section's memories: sections with facts are `completed`; a zero-fact section that was
   never reprocessed gets a `reprocess` job; one that was is `zero_fact`.
3. `reprocess` (`{"operation_id"}`) re-retains that operation's zero-fact sections once, as
   one batch under the same document IDs, and polls the new operation. Hindsight 0.10.1 has a
   `documents/{id}/reprocess` route, but no interaction with it is recorded, so Atlas re-retains
   (re-retaining an ID replaces only that document's own, empty, extraction).

Every job is idempotent: a replayed retain of a Source Version that already has memory
documents submits nothing, and state changes are guarded by the state they expect. Each
memory document and operation row written is audited in the same transaction.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.archive import Archive
from atlas.audit import Actor, content_hash, record
from atlas.bank_template import applied_template_version
from atlas.companies import Universe
from atlas.hindsight import (
    HindsightGateway,
    HindsightNotFound,
    Operation,
    OperationTimeout,
    RetainItem,
)
from atlas.jobs.queue import Artifacts, JobQueue
from atlas.retention.sections import SECTIONER_VERSION, Section, split_sections

RETAIN_KIND = "retain"
POLL_KIND = "poll_operation"
REPROCESS_KIND = "reprocess"

RETAINABLE_PARSES = ("parsed", "incomplete")


class RetainPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_version_id: uuid.UUID


class OperationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str


class NoTemplateApplied(Exception):
    """The bank has no applied template, so a retain would run under unknown missions."""


@dataclass(frozen=True)
class RetainTimings:
    poll_timeout: float
    poll_interval: float
    poll_attempts: int


def enqueue_retains(engine: Engine, source_version_ids: Sequence[uuid.UUID]) -> list[str]:
    """Enqueue a retain job for each given Source Version that has a parse; returns job IDs."""
    if not source_version_ids:
        return []
    with engine.connect() as connection:
        retainable = connection.execute(
            text(
                "SELECT id FROM source_version WHERE id = ANY(:ids)"
                " AND parse_status = ANY(:parses) ORDER BY ingested_at, id"
            ),
            {"ids": list(source_version_ids), "parses": list(RETAINABLE_PARSES)},
        ).scalars()
        ids: list[uuid.UUID] = list(retainable)
    queue = JobQueue(engine)
    return [str(queue.enqueue(RETAIN_KIND, f"retain:{i}", retain_payload(i)).job.id) for i in ids]


def retain_payload(source_version_id: uuid.UUID) -> dict[str, JsonValue]:
    return RetainPayload(source_version_id=source_version_id).model_dump(mode="json")


@dataclass(frozen=True)
class _Version:
    id: uuid.UUID
    raw_sha256: str
    parse_status: str
    parsed_object_uri: str | None
    available_at: datetime
    provider: str
    source_type: str
    form_type: str | None
    document_type: str | None
    title: str
    company_id: uuid.UUID | None
    company_slug: str | None


class Retention:
    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        gateway: HindsightGateway,
        actor: Actor,
        universe: Universe,
        timings: RetainTimings,
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._gateway = gateway
        self._actor = actor
        self._universe = universe
        self._timings = timings
        self._queue = JobQueue(engine)

    @property
    def bank_id(self) -> str:
        return self._gateway.bank_id

    # --- retain --------------------------------------------------------------------------------

    def retain(self, source_version_id: uuid.UUID, job_id: uuid.UUID | None) -> Artifacts:
        version = self._version(source_version_id)
        base: Artifacts = {"source_version_id": str(version.id), "bank_id": self.bank_id}
        if version.parse_status not in RETAINABLE_PARSES or version.parsed_object_uri is None:
            return base | {"outcome": "not_retainable", "parse_status": version.parse_status}

        with self._engine.begin() as connection:
            # One decision per raw hash at a time: two identical versions can't both retain.
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"retain:{self.bank_id}:{version.raw_sha256}"},
            )
            existing = self._documents(connection, version.id)
            if not existing:
                target = self._retained_twin(connection, version)
                if target is not None:
                    linked: Artifacts = {
                        "outcome": "linked",
                        "linked_to_source_version_id": str(target),
                        "documents": [*self._link(connection, version, target)],
                    }
                    return base | linked
                existing = self._record_sections(connection, version)
                outcome = "submitted"
            else:
                outcome = "already_retained"

        unsubmitted = [row for row in existing if row["operation_id"] is None and _retainable(row)]
        if unsubmitted:
            operation_id = self._submit(version, unsubmitted, kind="retain", job_id=job_id)
            if outcome == "already_retained":
                outcome = "resubmitted"  # a crash left sections recorded but not submitted
        else:
            operation_id = None
        polls = self._enqueue_polls(version.id)
        result: Artifacts = {
            "outcome": outcome,
            "operation_id": operation_id,
            "documents": [row["hindsight_document_id"] for row in existing],
            "poll_jobs": [*polls],
        }
        return base | result

    def _version(self, source_version_id: uuid.UUID) -> _Version:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT v.id, v.raw_sha256, v.parse_status, v.parsed_object_uri,"
                        " v.available_at, d.provider, d.source_type, d.form_type,"
                        " d.document_type, d.title, d.company_id, c.slug AS company_slug"
                        " FROM source_version v"
                        " JOIN source_document d ON d.id = v.source_document_id"
                        " LEFT JOIN company c ON c.id = d.company_id WHERE v.id = :id"
                    ),
                    {"id": source_version_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise LookupError(f"source version {source_version_id} does not exist")
        return _Version(**row)

    def _documents(self, connection: Connection, version_id: uuid.UUID) -> list[RowMapping]:
        return list(
            connection.execute(
                text(
                    "SELECT * FROM memory_document"
                    " WHERE source_version_id = :version AND bank_id = :bank"
                    " ORDER BY char_start, section_anchor"
                ),
                {"version": version_id, "bank": self.bank_id},
            ).mappings()
        )

    def _retained_twin(self, connection: Connection, version: _Version) -> uuid.UUID | None:
        """Another Source Version with the same raw bytes, retained here and not failed."""
        return connection.execute(
            text(
                "SELECT m.source_version_id FROM memory_document m"
                " JOIN source_version v ON v.id = m.source_version_id"
                " WHERE v.raw_sha256 = :sha AND m.bank_id = :bank AND v.id <> :version"
                " GROUP BY m.source_version_id"
                " HAVING bool_and(m.retain_state NOT IN ('linked', 'failed'))"
                " ORDER BY min(m.created_at), m.source_version_id LIMIT 1"
            ),
            {"sha": version.raw_sha256, "bank": self.bank_id, "version": version.id},
        ).scalar_one_or_none()

    def _template_version(self, connection: Connection) -> str:
        template_version = applied_template_version(connection, self.bank_id)
        if template_version is None:
            raise NoTemplateApplied(
                f"no bank template has been applied to {self.bank_id!r};"
                " run `atlas hindsight apply-template` before retaining"
            )
        return template_version

    def _link(self, connection: Connection, version: _Version, target: uuid.UUID) -> list[str]:
        template_version = self._template_version(connection)
        anchors: list[str] = []
        for section in self._documents(connection, target):
            row = self._insert_document(
                connection,
                version.id,
                anchor=section["section_anchor"],
                heading=section["section_heading"],
                start=section["char_start"],
                end=section["char_end"],
                sectioner_version=section["sectioner_version"],
                document_id=None,
                state="linked",
                template_version=template_version,
                linked_to=target,
            )
            anchors.append(row["section_anchor"])
        return anchors

    def _record_sections(self, connection: Connection, version: _Version) -> list[RowMapping]:
        template_version = self._template_version(connection)
        sections = split_sections(
            self._parsed_text(version),
            form=version.form_type,
            primary=version.document_type is not None
            and version.document_type == version.form_type,
        )
        return [
            self._insert_document(
                connection,
                version.id,
                anchor=section.anchor,
                heading=section.heading,
                start=section.start,
                end=section.end,
                sectioner_version=SECTIONER_VERSION,
                document_id=document_id(version.id, section),
                state="pending",
                template_version=template_version,
                linked_to=None,
            )
            for section in sections
        ]

    def _insert_document(
        self,
        connection: Connection,
        version_id: uuid.UUID,
        *,
        anchor: str,
        heading: str | None,
        start: int,
        end: int,
        sectioner_version: str,
        document_id: str | None,
        state: str,
        template_version: str,
        linked_to: uuid.UUID | None,
    ) -> RowMapping:
        row = (
            connection.execute(
                text(
                    "INSERT INTO memory_document (id, source_version_id, section_anchor,"
                    " section_heading, char_start, char_end, sectioner_version,"
                    " hindsight_document_id, bank_id, retain_state, template_version,"
                    " linked_to_source_version_id) VALUES (:id, :version, :anchor, :heading,"
                    " :start, :end, :sectioner, :document_id, :bank, :state, :template,"
                    " :linked_to) RETURNING *"
                ),
                {
                    "id": uuid.uuid4(),
                    "version": version_id,
                    "anchor": anchor,
                    "heading": heading,
                    "start": start,
                    "end": end,
                    "sectioner": sectioner_version,
                    "document_id": document_id,
                    "bank": self.bank_id,
                    "state": state,
                    "template": template_version,
                    "linked_to": linked_to,
                },
            )
            .mappings()
            .one()
        )
        self._audit(connection, "memory_document.created", "memory_document", row["id"], row)
        return row

    def _parsed_text(self, version: _Version) -> str:
        assert version.parsed_object_uri is not None
        return self._archive.get(version.parsed_object_uri).decode("utf-8")

    def _items(self, version: _Version, rows: Sequence[RowMapping]) -> list[RetainItem]:
        parsed = self._parsed_text(version)
        tags = self._tags(version)
        return [
            RetainItem(
                content=parsed[row["char_start"] : row["char_end"]],
                document_id=row["hindsight_document_id"],
                timestamp=version.available_at,
                context=f"{version.title}: {row['section_heading'] or row['section_anchor']}",
                metadata={
                    "source_version_id": str(version.id),
                    "section_anchor": row["section_anchor"],
                    "char_start": str(row["char_start"]),
                    "char_end": str(row["char_end"]),
                    "available_at": version.available_at.isoformat(),
                },
                tags=tags,
            )
            for row in rows
        ]

    def _tags(self, version: _Version) -> list[str]:
        tags: list[str] = []
        if version.company_id is not None:
            tags.append(f"company:{version.company_id}")
            tags += [
                f"theme:{slug}"
                for slug, theme in sorted(self._universe.themes.items())
                if version.company_slug in theme.companies
            ]
        tags.append(f"source:{version.provider}")
        tags.append(f"doctype:{version.source_type}")
        if version.form_type:
            tags.append(f"form:{version.form_type}")
        return tags

    def _submit(
        self, version: _Version, rows: Sequence[RowMapping], *, kind: str, job_id: uuid.UUID | None
    ) -> str:
        """Submit the sections as one batch; record the operation and point the rows at it."""
        submitted = self._gateway.retain_batch(self._items(version, rows))
        operation_id = submitted.operation_id
        document_ids = [row["hindsight_document_id"] for row in rows]
        action = f"memory_document.{'reprocess_' if kind == 'reprocess' else ''}submitted"
        with self._engine.begin() as connection:
            created = (
                connection.execute(
                    text(
                        "INSERT INTO hindsight_operation (id, bank_id, kind, status,"
                        " source_version_id, document_ids, job_id) VALUES (:id, :bank, :kind,"
                        " 'pending', :version, CAST(:documents AS jsonb), :job)"
                        " ON CONFLICT (id) DO NOTHING RETURNING *"
                    ),
                    {
                        "id": operation_id,
                        "bank": self.bank_id,
                        "kind": kind,
                        "version": version.id,
                        "documents": json.dumps(document_ids),
                        "job": job_id,
                    },
                )
                .mappings()
                .one_or_none()
            )
            if created is not None:
                self._audit(
                    connection,
                    "hindsight_operation.submitted",
                    "hindsight_operation",
                    operation_id,
                    created,
                )
            for row in rows:
                self._change(
                    connection,
                    row["id"],
                    "operation_id = :operation, reprocess_count = :reprocess, fact_count = NULL",
                    {
                        "operation": operation_id,
                        "reprocess": row["reprocess_count"] + (kind == "reprocess"),
                    },
                    expect="retain_state = 'pending' AND operation_id IS NOT DISTINCT FROM :was",
                    expect_params={"was": row["operation_id"]},
                    action=action,
                )
        self._queue.enqueue(
            POLL_KIND,
            f"poll:{operation_id}",
            OperationPayload(operation_id=operation_id).model_dump(),
            max_attempts=self._timings.poll_attempts,
        )
        return operation_id

    def _enqueue_polls(self, version_id: uuid.UUID) -> list[str]:
        """Make sure every unfinished operation of the version is being polled."""
        with self._engine.connect() as connection:
            pending = connection.execute(
                text(
                    "SELECT id FROM hindsight_operation WHERE source_version_id = :version"
                    " AND completed_at IS NULL ORDER BY submitted_at, id"
                ),
                {"version": version_id},
            ).scalars()
            operation_ids: list[str] = list(pending)
        return [
            str(
                self._queue.enqueue(
                    POLL_KIND,
                    f"poll:{operation_id}",
                    OperationPayload(operation_id=operation_id).model_dump(),
                    max_attempts=self._timings.poll_attempts,
                ).job.id
            )
            for operation_id in operation_ids
        ]

    # --- poll ----------------------------------------------------------------------------------

    def poll(self, operation_id: str) -> Artifacts:
        base: Artifacts = {"operation_id": operation_id}
        with self._engine.connect() as connection:
            recorded = (
                connection.execute(
                    text("SELECT * FROM hindsight_operation WHERE id = :id"), {"id": operation_id}
                )
                .mappings()
                .one_or_none()
            )
        if recorded is None:
            raise LookupError(f"operation {operation_id} is not tracked")
        if recorded["completed_at"] is not None:
            # Recorded by an earlier attempt; make sure its zero-fact sections were handed on.
            awaiting = [row for row in self._pending_rows(operation_id) if row["fact_count"] == 0]
            reprocess_job = self._enqueue_reprocess(operation_id) if awaiting else None
            return base | {
                "outcome": "already_recorded",
                "status": recorded["status"],
                "reprocess_job": reprocess_job,
            }
        try:
            operation = self._gateway.wait_for_operation(
                operation_id,
                timeout=self._timings.poll_timeout,
                poll_interval=self._timings.poll_interval,
            )
        except OperationTimeout as error:
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE hindsight_operation SET status = :status,"
                        " last_polled_at = now(), updated_at = now() WHERE id = :id"
                    ),
                    {"status": error.last_status, "id": operation_id},
                )
            raise

        rows = self._pending_rows(operation_id)
        if not operation.succeeded:
            error = operation.error_message or (
                f"Hindsight reported the operation {operation.status} with no error message"
            )
            with self._engine.begin() as connection:
                self._record_terminal(connection, operation)
                for row in rows:
                    self._change(
                        connection,
                        row["id"],
                        "retain_state = 'failed', error = :error",
                        {"error": error},
                        expect="retain_state = 'pending' AND operation_id = :operation",
                        expect_params={"operation": operation_id},
                        action="memory_document.failed",
                    )
            return base | {"outcome": operation.status, "error": error, "failed": len(rows)}

        counts: dict[uuid.UUID, int | None] = {}
        for row in rows:
            try:
                counts[row["id"]] = self._gateway.get_document(
                    row["hindsight_document_id"]
                ).memory_unit_count
            except HindsightNotFound:
                counts[row["id"]] = None
        tally = {"completed": 0, "reprocess": 0, "zero_fact": 0, "failed": 0}
        with self._engine.begin() as connection:
            self._record_terminal(connection, operation)
            for row in rows:
                count = counts[row["id"]]
                if count is None:
                    state, assignments = "failed", "retain_state = 'failed', error = :error"
                    params: dict[str, Any] = {
                        "error": f"document {row['hindsight_document_id']} not found in"
                        " Hindsight after its operation completed"
                    }
                elif count > 0:
                    state, assignments = "completed", "retain_state = 'completed'"
                    params = {}
                elif row["reprocess_count"] == 0:
                    state, assignments = "reprocess", "retain_state = 'pending'"
                    params = {}
                else:
                    state, assignments = "zero_fact", "retain_state = 'zero_fact'"
                    params = {}
                if count is not None:
                    assignments += ", fact_count = :count"
                    params["count"] = count
                tally[state] += 1
                self._change(
                    connection,
                    row["id"],
                    assignments,
                    params,
                    expect="retain_state = 'pending' AND operation_id = :operation",
                    expect_params={"operation": operation_id},
                    action=f"memory_document.{'zero_facts' if state == 'reprocess' else state}",
                )
        reprocess_job = self._enqueue_reprocess(operation_id) if tally["reprocess"] else None
        return base | {"outcome": "completed", **tally, "reprocess_job": reprocess_job}

    def _enqueue_reprocess(self, operation_id: str) -> str:
        payload = OperationPayload(operation_id=operation_id).model_dump()
        return str(self._queue.enqueue(REPROCESS_KIND, f"reprocess:{operation_id}", payload).job.id)

    def _pending_rows(self, operation_id: str) -> list[RowMapping]:
        with self._engine.connect() as connection:
            return list(
                connection.execute(
                    text(
                        "SELECT * FROM memory_document WHERE operation_id = :operation"
                        " AND retain_state = 'pending' ORDER BY char_start, section_anchor"
                    ),
                    {"operation": operation_id},
                ).mappings()
            )

    def _record_terminal(self, connection: Connection, operation: Operation) -> None:
        old = (
            connection.execute(
                text("SELECT * FROM hindsight_operation WHERE id = :id FOR UPDATE"),
                {"id": operation.operation_id},
            )
            .mappings()
            .one()
        )
        new = (
            connection.execute(
                text(
                    "UPDATE hindsight_operation SET status = :status, error_message = :error,"
                    " retry_count = :retries, result_metadata = CAST(:metadata AS jsonb),"
                    " completed_at = coalesce(:completed_at, now()), last_polled_at = now(),"
                    " updated_at = now() WHERE id = :id RETURNING *"
                ),
                {
                    "id": operation.operation_id,
                    "status": operation.status,
                    "error": operation.error_message,
                    "retries": operation.retry_count or 0,
                    "metadata": json.dumps(operation.result_metadata),
                    "completed_at": operation.completed_at,
                },
            )
            .mappings()
            .one()
        )
        record(
            connection,
            self._actor,
            f"hindsight_operation.{operation.status}",
            entity_type="hindsight_operation",
            entity_id=operation.operation_id,
            old_hash=content_hash(dict(old)),
            new_hash=content_hash(dict(new)),
        )

    # --- reprocess -----------------------------------------------------------------------------

    def reprocess(self, operation_id: str, job_id: uuid.UUID | None) -> Artifacts:
        rows = [
            row
            for row in self._pending_rows(operation_id)
            if row["reprocess_count"] == 0 and row["fact_count"] == 0
        ]
        if not rows:
            return {"operation_id": operation_id, "outcome": "nothing_to_reprocess"}
        version = self._version(rows[0]["source_version_id"])
        new_operation = self._submit(version, rows, kind="reprocess", job_id=job_id)
        return {
            "operation_id": operation_id,
            "outcome": "resubmitted",
            "reprocess_operation_id": new_operation,
            "documents": [row["hindsight_document_id"] for row in rows],
        }

    # --- shared --------------------------------------------------------------------------------

    def _change(
        self,
        connection: Connection,
        row_id: uuid.UUID,
        assignments: str,
        params: dict[str, Any],
        *,
        expect: str,
        expect_params: dict[str, Any],
        action: str,
    ) -> bool:
        """Update one memory document if it is still in the expected state; audit the change."""
        old = (
            connection.execute(
                text(f"SELECT * FROM memory_document WHERE id = :id AND {expect} FOR UPDATE"),  # noqa: S608 (constant fragments)
                {"id": row_id, **expect_params},
            )
            .mappings()
            .one_or_none()
        )
        if old is None:
            return False
        new = (
            connection.execute(
                text(
                    f"UPDATE memory_document SET {assignments}, updated_at = now()"  # noqa: S608 (constant fragments)
                    " WHERE id = :id RETURNING *"
                ),
                {"id": row_id, **params},
            )
            .mappings()
            .one()
        )
        record(
            connection,
            self._actor,
            action,
            entity_type="memory_document",
            entity_id=str(row_id),
            old_hash=content_hash(dict(old)),
            new_hash=content_hash(dict(new)),
        )
        return True

    def _audit(
        self,
        connection: Connection,
        action: str,
        entity_type: str,
        entity_id: object,
        row: RowMapping,
    ) -> None:
        record(
            connection,
            self._actor,
            action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            new_hash=content_hash(dict(row)),
        )


def document_id(source_version_id: uuid.UUID, section: Section) -> str:
    """ADR-0001: per Source Version UUID and section anchor, never reused."""
    return f"srcv:{source_version_id}:{section.anchor}"


def _retainable(row: RowMapping) -> bool:
    return row["retain_state"] == "pending" and row["hindsight_document_id"] is not None
