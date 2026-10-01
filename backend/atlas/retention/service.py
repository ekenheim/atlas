"""The retention service: the bridge from the source ledger to Memory (spec Part B).

Three jobs carry a Source Version into the research bank:

1. `retain` (payload `{"source_version_id"}`), enqueued for each new parsed Source Version
   in English (`RETAINABLE_LANGUAGES`: extraction is English-only in the pilot; a version in
   another language is archived, never retained).
   If a Source Version with the same raw bytes is already retained in the bank, it records
   `linked` sections pointing at that one and stops (ADR-0001). Otherwise it splits the
   parse into sections (`atlas.retention.sections`), records each as a `pending` memory
   document with the ID `srcv:<source_version_uuid>:<section-anchor>`, and submits them as
   **one** batch. The operation is recorded and a `poll_operation` job follows it.
   With retention triage on (`atlas.retention.triage`), a version whose sections aren't all
   decided yet is handed to a `triage` job first, and only the sections decided `retain`
   are recorded and submitted; a section retained on demand later is recorded and
   submitted by the next retain (triage on or off). With triage off, every section is.
2. `poll_operation` (`{"operation_id"}`) waits for the operation's `status` (the only basis
   for an outcome) with a timeout. A timeout fails the attempt, so it is retried. A failed
   operation's error is classified (`error_class`): a `permanent` one marks its sections
   `failed` with the error; a `quota` or `unavailable` one (a 429 or outage behind Hindsight)
   leaves them `pending` and raises `TransientFailure`, so the queue pauses and this job is
   requeued; once the pause lifts, its next attempt resubmits the same sections as a new
   batch under the same document IDs (never another model). On completion it counts each
   section's memories and records their IDs (the memory list, by document): sections with
   facts are `completed`; a zero-fact section that was never reprocessed gets a `reprocess`
   job; one that was is `zero_fact`.
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
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.archive import Archive
from atlas.audit import SYSTEM_ACTOR, Actor, content_hash, record
from atlas.bank_template import applied_template_version
from atlas.companies import Universe
from atlas.hindsight import (
    HindsightGateway,
    HindsightNotFound,
    Operation,
    OperationTimeout,
    RetainItem,
)
from atlas.jobs.budget import RetainExtractor
from atlas.jobs.pacing import FailureClass, JobClass, TransientFailure, classify_error_text
from atlas.jobs.queue import Artifacts, JobQueue
from atlas.retention.decisions import effective_decisions
from atlas.retention.sections import SECTIONER_VERSION, Section, split_sections
from atlas.sources import keep_8k_document

RETAIN_KIND = "retain"
TRIAGE_KIND = "triage"
POLL_KIND = "poll_operation"
REPROCESS_KIND = "reprocess"

# The retain item metadata key Hindsight's metadata routing matches (the shared server's
# strategy routes `extractor: minimax` to its MiniMax chain member; home-ops PR #7180).
EXTRACTOR_METADATA_KEY = "extractor"

RETAINABLE_PARSES = ("parsed", "incomplete")
# Retention and extraction are English-only in the pilot (spec, "PDF parsing").
RETAINABLE_LANGUAGES = ("en",)


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


def enqueue_retains(
    engine: Engine,
    source_version_ids: Sequence[uuid.UUID],
    job_class: JobClass = "interactive",
    actor: Actor = SYSTEM_ACTOR,
    key_suffix: str = "",
) -> list[str]:
    """Enqueue a retain job for each given Source Version that has a parse in a retainable
    language; returns job IDs.

    A backfill ingest enqueues backfill retains (held by the backfill window, if one is
    set, and by the interactive reserve of the budget the retains spend: Codex's, or the
    routed extractor's when `ATLAS_RETAIN_EXTRACTOR` is set).
    Each new job is audited as `actor`'s.
    """
    if not source_version_ids:
        return []
    with engine.connect() as connection:
        retainable = connection.execute(
            text(
                "SELECT id FROM source_version WHERE id = ANY(:ids)"
                " AND parse_status = ANY(:parses) AND language = ANY(:languages)"
                " ORDER BY ingested_at, id"
            ),
            {
                "ids": list(source_version_ids),
                "parses": list(RETAINABLE_PARSES),
                "languages": list(RETAINABLE_LANGUAGES),
            },
        ).scalars()
        ids: list[uuid.UUID] = list(retainable)
    queue = JobQueue(engine, actor=actor)
    return [
        str(
            queue.enqueue(
                RETAIN_KIND, f"retain:{i}{key_suffix}", retain_payload(i), job_class=job_class
            ).job.id
        )
        for i in ids
    ]


def unretained_versions(engine: Engine, company_id: uuid.UUID) -> list[uuid.UUID]:
    """The company's retainable Source Versions that were never retained nor queued for it,
    newest first by availability: each Source Document's latest version, with a parse in a
    retainable language, no memory documents and no `retain` job. An ingest with a retain
    cap retains the first of these, and a later capped ingest the next (ticket 27)."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT latest.id FROM ("
                "  SELECT DISTINCT ON (v.source_document_id) v.id, v.available_at, v.ingested_at,"
                "    v.parse_status, v.language"
                "  FROM source_version v JOIN source_document d ON d.id = v.source_document_id"
                "  WHERE d.company_id = :company"
                "  ORDER BY v.source_document_id, v.version_number DESC"
                ") latest WHERE parse_status = ANY(:parses) AND language = ANY(:languages)"
                " AND NOT EXISTS (SELECT FROM memory_document m"
                "   WHERE m.source_version_id = latest.id)"
                " AND NOT EXISTS (SELECT FROM job j WHERE j.kind = :kind"
                "   AND j.payload ->> 'source_version_id' = CAST(latest.id AS text))"
                " ORDER BY latest.available_at DESC, latest.ingested_at, latest.id"
            ),
            {
                "company": company_id,
                "parses": list(RETAINABLE_PARSES),
                "languages": list(RETAINABLE_LANGUAGES),
                "kind": RETAIN_KIND,
            },
        ).scalars()
        return list(rows)


def retry_failed(
    engine: Engine,
    actor: Actor,
    *,
    since: datetime | None,
    job_class: JobClass = "interactive",
    eight_k_items: Sequence[str] | None = None,
    exhibits_only_items: Sequence[str] = (),
) -> dict[str, Any]:
    """Reset the failed sections of Source Versions available after `since` (None: all) to
    `pending`, and enqueue a new retain for each such version, which resubmits them.

    The ingest's 8-K selection applies here too (`keep_8k_document`), so documents a current
    ingest would not fetch are not resubmitted. A failed operation stays recorded; each
    section's reset is audited. Resubmitting the same content under the same document ID is
    allowed (ADR-0001, amendment).
    """
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f")
    with engine.begin() as connection:
        failed = (
            connection.execute(
                text(
                    "SELECT m.id, m.source_version_id, m.hindsight_document_id,"
                    " v.metadata, d.document_type, d.form_type, d.accession,"
                    " EXISTS (SELECT 1 FROM source_document x WHERE x.accession = d.accession"
                    "   AND x.document_type LIKE 'EX-%') AS has_exhibits"
                    " FROM memory_document m"
                    " JOIN source_version v ON v.id = m.source_version_id"
                    " JOIN source_version_availability a ON a.source_version_id = v.id"
                    " JOIN source_document d ON d.id = v.source_document_id"
                    " WHERE m.retain_state = 'failed'"
                    " AND (CAST(:since AS timestamptz) IS NULL OR a.available_at >= :since)"
                ),
                {"since": since},
            )
            .mappings()
            .all()
        )
        chosen: list[RowMapping] = []
        skipped = 0
        for row in failed:
            form = (row["form_type"] or "").removesuffix("/A")
            metadata = cast(dict[str, Any], row["metadata"] or {})
            items = tuple(str(item) for item in cast(list[Any], metadata.get("items") or []))
            if form == "8-K" and not keep_8k_document(
                items,
                is_cover=row["document_type"] == row["form_type"],
                has_exhibits=bool(row["has_exhibits"]),
                eight_k_items=eight_k_items,
                exhibits_only_items=exhibits_only_items,
            ):
                skipped += 1
                continue
            chosen.append(row)
        for row in chosen:
            connection.execute(
                text(
                    "UPDATE memory_document SET retain_state = 'pending', operation_id = NULL,"
                    " error = NULL WHERE id = :id AND retain_state = 'failed'"
                ),
                {"id": row["id"]},
            )
            record(
                connection,
                actor,
                "memory_document.retry",
                entity_type="memory_document",
                entity_id=str(row["id"]),
                new_hash=content_hash(
                    {"retain_state": "pending", "document": row["hindsight_document_id"]}
                ),
            )
    versions = list(dict.fromkeys(row["source_version_id"] for row in chosen))
    jobs = enqueue_retains(
        engine, versions, job_class=job_class, actor=actor, key_suffix=f":retry:{stamp}"
    )
    return {
        "sections": len(chosen),
        "source_versions": len(versions),
        "skipped_by_selection": skipped,
        "retain_jobs": jobs,
    }


def retain_payload(source_version_id: uuid.UUID) -> dict[str, JsonValue]:
    return RetainPayload(source_version_id=source_version_id).model_dump(mode="json")


@dataclass(frozen=True)
class SourceVersionInfo:
    """What retention (and triage) read about a Source Version."""

    id: uuid.UUID
    raw_sha256: str
    parse_status: str
    parsed_object_uri: str | None
    language: str | None
    available_at: datetime
    provider: str
    source_type: str
    form_type: str | None
    document_type: str | None
    title: str
    company_id: uuid.UUID | None
    company_slug: str | None


def load_version(engine: Engine, source_version_id: uuid.UUID) -> SourceVersionInfo:
    """The version's retention facts; LookupError if it doesn't exist."""
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT v.id, v.raw_sha256, v.parse_status, v.parsed_object_uri,"
                    " v.language, a.available_at, d.provider, d.source_type, d.form_type,"
                    " d.document_type, d.title, d.company_id, c.slug AS company_slug"
                    " FROM source_version v"
                    " JOIN source_version_availability a ON a.source_version_id = v.id"
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
    return SourceVersionInfo(**row)


def version_sections(version: SourceVersionInfo, parsed_text: str) -> list[Section]:
    """The version's sections under the current sectioner."""
    return split_sections(
        parsed_text,
        form=version.form_type,
        primary=version.document_type is not None and version.document_type == version.form_type,
    )


def version_tags(version: SourceVersionInfo, universe: Universe) -> list[str]:
    """The tags every memory document of the version is retained with (the research scope's
    `company:`/`theme:` tags, plus the source, document type and form)."""
    tags: list[str] = []
    if version.company_id is not None:
        tags.append(f"company:{version.company_id}")
        tags += [
            f"theme:{slug}"
            for slug, theme in sorted(universe.themes.items())
            if version.company_slug in theme.companies
        ]
    tags.append(f"source:{version.provider}")
    tags.append(f"doctype:{version.source_type}")
    if version.form_type:
        tags.append(f"form:{version.form_type}")
    return tags


def retain_item(
    version: SourceVersionInfo,
    parsed: str,
    *,
    document_id: str,
    anchor: str,
    heading: str | None,
    start: int,
    end: int,
    tags: list[str],
    extractor: RetainExtractor | None = None,
) -> RetainItem:
    """One section of the version as a retain item: its parsed text, timestamped with the
    version's availability, with the metadata the provenance resolver checks.

    With an `extractor` (`ATLAS_RETAIN_EXTRACTOR`), the metadata also carries `extractor`,
    the key Hindsight's metadata routing matches to choose the chain member that extracts
    the item; a server without such a route ignores it. Without one, the item is exactly
    what it was before the setting existed, and Hindsight's primary LLM extracts it.
    """
    metadata = {
        "source_version_id": str(version.id),
        "section_anchor": anchor,
        "char_start": str(start),
        "char_end": str(end),
        "available_at": version.available_at.isoformat(),
    }
    if extractor is not None:
        metadata[EXTRACTOR_METADATA_KEY] = extractor
    return RetainItem(
        content=parsed[start:end],
        document_id=document_id,
        timestamp=version.available_at,
        context=f"{version.title}: {heading or anchor}",
        metadata=metadata,
        tags=tags,
    )


def is_retainable(version: SourceVersionInfo) -> bool:
    """A parse in a retainable language (English in the pilot)."""
    return (
        version.parse_status in RETAINABLE_PARSES
        and version.parsed_object_uri is not None
        and version.language in RETAINABLE_LANGUAGES
    )


class Retention:
    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        gateway: HindsightGateway,
        actor: Actor,
        universe: Universe,
        timings: RetainTimings,
        *,
        triage: bool = False,
        extractor: RetainExtractor | None = None,
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._gateway = gateway
        self._actor = actor
        self._universe = universe
        self._timings = timings
        self._triage = triage
        # The extractor every item submitted now asks Hindsight for (None: its primary).
        self._extractor: RetainExtractor | None = extractor
        self._queue = JobQueue(engine, actor=actor)

    @property
    def bank_id(self) -> str:
        return self._gateway.bank_id

    # --- retain --------------------------------------------------------------------------------

    def retain(
        self,
        source_version_id: uuid.UUID,
        job_id: uuid.UUID | None,
        job_class: JobClass = "interactive",
    ) -> Artifacts:
        """Retain the version's sections (see the module).

        With triage on, a version with no memory documents whose sections aren't all decided
        yet gets a `triage` job instead (in this job's class), which enqueues the retain of
        its `retain` sections once it has decided; only those are recorded and submitted.
        Sections decided `retain` later (on demand) are recorded and submitted by the next
        retain, whether or not triage is on. With triage off, a version with no memory
        documents has every section recorded, as before triage existed.
        """
        version = load_version(self._engine, source_version_id)
        base: Artifacts = {"source_version_id": str(version.id), "bank_id": self.bank_id}
        if version.parse_status not in RETAINABLE_PARSES or version.parsed_object_uri is None:
            return base | {"outcome": "not_retainable", "parse_status": version.parse_status}
        if version.language not in RETAINABLE_LANGUAGES:
            return base | {"outcome": "not_retainable", "language": version.language}

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
            decisions = effective_decisions(connection, version.id)
            if not existing and not self._triage:
                existing = self._record_sections(connection, version)
                outcome = "submitted"
            elif not existing and self._undecided(version, decisions):
                triage_job = self._queue.enqueue_within(
                    connection,
                    TRIAGE_KIND,
                    f"triage:{version.id}",
                    retain_payload(version.id),
                    job_class=job_class,
                ).job.id
                return base | {"outcome": "awaiting_triage", "triage_job": str(triage_job)}
            else:
                recorded = self._record_decided(connection, version, existing, decisions)
                if recorded:
                    outcome = "submitted"
                elif existing:
                    outcome = "already_retained"
                else:
                    return base | {"outcome": "nothing_to_retain", "documents": []}
                existing = [*existing, *recorded]

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

    def _undecided(self, version: SourceVersionInfo, decisions: dict[str, RowMapping]) -> bool:
        sections = version_sections(version, self._parsed_text(version))
        return any(section.anchor not in decisions for section in sections)

    def _record_decided(
        self,
        connection: Connection,
        version: SourceVersionInfo,
        existing: Sequence[RowMapping],
        decisions: dict[str, RowMapping],
    ) -> list[RowMapping]:
        """Record a pending memory document for each section decided `retain` without one."""
        have = {row["section_anchor"] for row in existing}
        wanted = sorted(
            (
                decision
                for anchor, decision in decisions.items()
                if decision["decision"] == "retain" and anchor not in have
            ),
            key=lambda decision: (decision["char_start"], decision["section_anchor"]),
        )
        if not wanted:
            return []
        template_version = self._template_version(connection)
        return [
            self._insert_document(
                connection,
                version.id,
                anchor=decision["section_anchor"],
                heading=decision["section_heading"],
                start=decision["char_start"],
                end=decision["char_end"],
                sectioner_version=decision["sectioner_version"],
                document_id=f"srcv:{version.id}:{decision['section_anchor']}",
                state="pending",
                template_version=template_version,
                linked_to=None,
            )
            for decision in wanted
        ]

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

    def _retained_twin(
        self, connection: Connection, version: SourceVersionInfo
    ) -> uuid.UUID | None:
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

    def _link(
        self, connection: Connection, version: SourceVersionInfo, target: uuid.UUID
    ) -> list[str]:
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

    def _record_sections(
        self, connection: Connection, version: SourceVersionInfo
    ) -> list[RowMapping]:
        template_version = self._template_version(connection)
        sections = version_sections(version, self._parsed_text(version))
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

    def _parsed_text(self, version: SourceVersionInfo) -> str:
        assert version.parsed_object_uri is not None
        return self._archive.get(version.parsed_object_uri).decode("utf-8")

    def _items(self, version: SourceVersionInfo, rows: Sequence[RowMapping]) -> list[RetainItem]:
        parsed = self._parsed_text(version)
        tags = version_tags(version, self._universe)
        return [
            retain_item(
                version,
                parsed,
                document_id=row["hindsight_document_id"],
                anchor=row["section_anchor"],
                heading=row["section_heading"],
                start=row["char_start"],
                end=row["char_end"],
                tags=tags,
                extractor=self._extractor,
            )
            for row in rows
        ]

    def _submit(
        self,
        version: SourceVersionInfo,
        rows: Sequence[RowMapping],
        *,
        kind: str,
        job_id: uuid.UUID | None,
        resubmit: bool = False,
    ) -> str:
        """Submit the sections as one batch; record the operation and point the rows at it.

        `resubmit`: the same sections again after a quota or outage failure of their last
        operation (of `kind`), so a reprocess isn't counted twice.

        The operation and each section record the extractor this submission asked for (null:
        the primary), since Hindsight stores nothing about the route: a section shows the
        extractor of its latest attempt, and the operation's decides which budget it spends.
        """
        submitted = self._gateway.retain_batch(self._items(version, rows))
        operation_id = submitted.operation_id
        document_ids = [row["hindsight_document_id"] for row in rows]
        if resubmit:
            action = "memory_document.resubmitted"
        else:
            action = f"memory_document.{'reprocess_' if kind == 'reprocess' else ''}submitted"
        bump = kind == "reprocess" and not resubmit
        with self._engine.begin() as connection:
            created = (
                connection.execute(
                    text(
                        "INSERT INTO hindsight_operation (id, bank_id, kind, status,"
                        " source_version_id, document_ids, job_id, extractor) VALUES (:id,"
                        " :bank, :kind, 'pending', :version, CAST(:documents AS jsonb), :job,"
                        " :extractor) ON CONFLICT (id) DO NOTHING RETURNING *"
                    ),
                    {
                        "id": operation_id,
                        "bank": self.bank_id,
                        "kind": kind,
                        "version": version.id,
                        "documents": json.dumps(document_ids),
                        "job": job_id,
                        "extractor": self._extractor,
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
                    "operation_id = :operation, reprocess_count = :reprocess, fact_count = NULL,"
                    " memory_ids = NULL, extractor = :extractor",
                    {
                        "operation": operation_id,
                        "reprocess": row["reprocess_count"] + bump,
                        "extractor": self._extractor,
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

    def poll(self, operation_id: str, job_id: uuid.UUID | None = None) -> Artifacts:
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
        if recorded["completed_at"] is not None and recorded["error_class"] in TRANSIENT:
            # Failed for quota or availability; the pause has lifted, so retry its sections.
            return base | self._resubmit(recorded)
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
            error_class = operation_error_class(operation)
            if error_class != "permanent":
                with self._engine.begin() as connection:
                    self._record_terminal(connection, operation, error_class)
                raise TransientFailure(
                    error_class,
                    f"Hindsight operation {operation_id} {operation.status}"
                    f" ({error_class}): {error}",
                )
            with self._engine.begin() as connection:
                self._record_terminal(connection, operation, error_class)
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
        memory_ids: dict[uuid.UUID, list[str]] = {}
        for row in rows:
            document = row["hindsight_document_id"]
            try:
                counts[row["id"]] = self._gateway.get_document(document).memory_unit_count
            except HindsightNotFound:
                counts[row["id"]] = None
                continue
            # The memories returned for the section (story 10), so provenance never depends
            # on Hindsight alone.
            memory_ids[row["id"]] = (
                [memory.id for memory in self._gateway.document_memories(document)]
                if counts[row["id"]]
                else []
            )
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
                    assignments += ", fact_count = :count, memory_ids = CAST(:memory_ids AS jsonb)"
                    params["count"] = count
                    params["memory_ids"] = json.dumps(memory_ids[row["id"]])
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
        """Enqueue the reprocess, in the class (backfill or not) of the job that submitted."""
        with self._engine.connect() as connection:
            job_class: JobClass = connection.execute(
                text(
                    "SELECT coalesce(j.job_class, 'interactive') FROM hindsight_operation o"
                    " LEFT JOIN job j ON j.id = o.job_id WHERE o.id = :id"
                ),
                {"id": operation_id},
            ).scalar_one()
        payload = OperationPayload(operation_id=operation_id).model_dump()
        return str(
            self._queue.enqueue(
                REPROCESS_KIND, f"reprocess:{operation_id}", payload, job_class=job_class
            ).job.id
        )

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

    def _resubmit(self, recorded: RowMapping) -> Artifacts:
        operation_id: str = recorded["id"]
        rows = self._pending_rows(operation_id)
        if not rows:
            return {"outcome": "already_resubmitted", "status": recorded["status"]}
        version = load_version(self._engine, recorded["source_version_id"])
        # The new operation keeps the original submitting job, whose class (backfill or
        # interactive) its follow-up reprocess inherits.
        new_operation = self._submit(
            version, rows, kind=recorded["kind"], job_id=recorded["job_id"], resubmit=True
        )
        return {
            "outcome": "resubmitted",
            "error_class": recorded["error_class"],
            "resubmitted_operation_id": new_operation,
            "documents": [row["hindsight_document_id"] for row in rows],
        }

    def _record_terminal(
        self, connection: Connection, operation: Operation, error_class: str | None = None
    ) -> None:
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
                    " error_class = :error_class,"
                    " retry_count = :retries, result_metadata = CAST(:metadata AS jsonb),"
                    " completed_at = coalesce(:completed_at, now()), last_polled_at = now(),"
                    " updated_at = now() WHERE id = :id RETURNING *"
                ),
                {
                    "id": operation.operation_id,
                    "status": operation.status,
                    "error": operation.error_message,
                    "error_class": error_class,
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
        version = load_version(self._engine, rows[0]["source_version_id"])
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


TRANSIENT: tuple[FailureClass, ...] = ("quota", "unavailable")


def operation_error_class(operation: Operation) -> FailureClass | Literal["permanent"]:
    """A failed operation's error class, from its error and its sub-batches' errors.

    `quota` (429, rate limit, insufficient quota) and `unavailable` (503, connection
    failures) are the model provider or LiteLLM failing, not the sections; anything else,
    including a failure with no message, is `permanent`.
    """
    messages = [operation.error_message, *(c.error_message for c in operation.child_operations)]
    found = {classify_error_text(message) for message in messages} - {None}
    if "quota" in found:
        return "quota"
    if "unavailable" in found:
        return "unavailable"
    return "permanent"


def _retainable(row: RowMapping) -> bool:
    return row["retain_state"] == "pending" and row["hindsight_document_id"] is not None
