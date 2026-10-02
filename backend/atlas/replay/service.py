"""Replay banks (§9.2; spec "Snapshots and replay"; ticket 22).

A replay evaluates the pipeline as of a **cutoff** in an isolated bank,
`atlas-replay-<replay id>`, on the **local** Hindsight (`ATLAS_REPLAY_HINDSIGHT_URL`; never the
shared server), and always deletes the bank afterwards.

**What it may see.** The Source Versions available at the cutoff through the corrected
availability view (`source_version_availability.available_at <= cutoff`; the
`available_at` convention of §9.2, disclosed on every replay), of the replay's companies
(default: every company), the latest version of each Source Document at the cutoff, with a
parse in a retainable language. At most `max_source_versions` of them (the latest), chosen
when the replay is requested. Nothing is exported from the research bank: a replay bank is
seeded only by re-retaining (§9.2 and the ticket 09 answer: an export could carry extraction
made after the cutoff).

**The `replay` job** (pausable; budgeted under `codex`) runs one bounded step per attempt and
raises `Requeue` after each, so no attempt outlives its lease:

1. `create_bank`: import the bank template (its manifest without the mental models, whose
   refreshes would be LLM calls the replay doesn't need) into the replay bank; this is the
   bank's first write, so it creates it. Recorded and audited like any template application.
2. `retain`: one Source Version per step, in chronological order (availability, then ID):
   every section (retention **triage is bypassed**: the replay measures the pipeline on what
   was available, not on decisions recorded later) as one batch through the same code path
   as production retention (`version_sections`, `version_tags`, `retain_item`, the items
   asking for the same extractor as production's when `ATLAS_RETAIN_EXTRACTOR` is set; the
   replay's operations stay on the `codex` budget either way), then wait for its operation,
   so a later version's extraction runs after an earlier one's. Each section is recorded in
   the replay's own ledger (`replay_document`), never in `memory_document`. Zero-fact
   sections are not reprocessed.
3. `consolidate`: ask for consolidation and wait for it, bounded (a timeout after
   `retain_poll_attempts` waits is recorded as `timed_out`, and the questions run anyway).
4. `questions`: one question of the fixed set per step: a recall and a reflect, scoped like
   production research, every memory and citation resolved by the provenance resolver
   against the replay's ledger, and leakage counted independently (`ReplayLeakage`).
5. `delete_bank`: delete the bank (a 404 counts as deleted), then finish.

A step that fails for a quota or availability reason pauses the queue, and the replay resumes
where it was. Any other failure, and a cancel, ends the replay (`failed`/`cancelled`) by
going straight to `delete_bank`, so its bank is deleted then too. Only if the deletion itself
fails on the job's last attempt does a replay finish with its bank undeleted, and it says so
(`bank_delete_error`).
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.archive import Archive
from atlas.audit import Actor, content_hash, record
from atlas.bank_template import BankTemplate, apply_template
from atlas.companies import Universe
from atlas.hindsight import (
    REPLAY_BANK_PREFIX,
    HindsightGateway,
    HindsightNotConfigured,
    HindsightNotFound,
    Memory,
    OperationTimeout,
    RecallResult,
    TagScope,
)
from atlas.jobs.budget import RetainExtractor
from atlas.jobs.pacing import Requeue, TransientFailure, classify_failure
from atlas.jobs.queue import Artifacts, Job, JobQueue, job_id_for
from atlas.replay.questions import QuestionSet, ReplayQuestion
from atlas.replay.reads import ReplayRecalledMemory
from atlas.research.provenance import Citation, ProvenanceResolver, SectionLookup
from atlas.research.service import SCOPE_MATCH, AppliedScope, recalled_memory
from atlas.retention.context import known_companies
from atlas.retention.service import (
    RETAINABLE_LANGUAGES,
    RETAINABLE_PARSES,
    load_version,
    operation_error_class,
    retain_item,
    version_sections,
    version_tags,
)
from atlas.retention.service import document_id as section_document_id

REPLAY_KIND = "replay"
AVAILABILITY_CONVENTION = "available_at"


class ReplayRefused(Exception):
    """A replay Atlas won't start: `code` is the API error code, `status` its HTTP status."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ReplayPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    replay_job_id: uuid.UUID


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cutoff: AwareDatetime = Field(
        description="only Source Versions available by then are retained; not in the future"
    )
    company_ids: list[uuid.UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=25,
        description="the companies whose Source Versions are replayed and whose tags scope the"
        " questions; default: every company, the questions scoped by every theme",
    )
    question_set: str = Field(default="default", min_length=1, description="a configured set")
    max_source_versions: int | None = Field(
        default=None,
        ge=1,
        le=25,
        description="retain at most this many (the latest eligible); default and ceiling:"
        " ATLAS_REPLAY_MAX_SOURCE_VERSIONS",
    )


def bank_id_for(replay_id: uuid.UUID) -> str:
    return f"{REPLAY_BANK_PREFIX}{replay_id}"


def request_replay(
    engine: Engine,
    queue: JobQueue,
    actor: Actor,
    request: ReplayRequest,
    *,
    question_sets: dict[str, QuestionSet],
    universe: Universe,
    max_source_versions: int,
    now: datetime | None = None,
) -> uuid.UUID:
    """Record a replay, the Source Versions it may see, and enqueue its job (audited).

    Raises `ReplayRefused`.
    """
    now = now or datetime.now(UTC)
    if request.cutoff > now:
        raise ReplayRefused(422, "cutoff_in_future", "the cutoff must not be in the future")
    question_set = question_sets.get(request.question_set)
    if question_set is None:
        known = ", ".join(sorted(question_sets)) or "none"
        raise ReplayRefused(
            422, "unknown_question_set", f"unknown question set {request.question_set!r} ({known})"
        )
    cap = request.max_source_versions or max_source_versions
    if cap > max_source_versions:
        raise ReplayRefused(
            422,
            "max_source_versions_exceeded",
            f"a replay retains at most {max_source_versions} Source Versions"
            " (ATLAS_REPLAY_MAX_SOURCE_VERSIONS)",
        )
    company_ids = list(dict.fromkeys(request.company_ids or []))
    replay_id = uuid.uuid4()
    key = f"replay:{replay_id}"
    with engine.begin() as connection:
        if company_ids:
            known_ids = set(
                connection.execute(
                    text("SELECT id FROM company WHERE id = ANY(:ids)"), {"ids": company_ids}
                ).scalars()
            )
            unknown = [str(c) for c in company_ids if c not in known_ids]
            if unknown:
                raise ReplayRefused(
                    422, "unknown_company", f"unknown company: {', '.join(unknown)}"
                )
            scope = AppliedScope(
                company_ids=company_ids,
                theme_ids=[],
                tags=[f"company:{c}" for c in company_ids],
                tags_match=SCOPE_MATCH,
            )
        else:
            themes = sorted(universe.themes)
            if not themes:
                raise ReplayRefused(
                    422, "no_scope", "the universe has no themes; name the replay's companies"
                )
            scope = AppliedScope(
                company_ids=[],
                theme_ids=themes,
                tags=[f"theme:{t}" for t in themes],
                tags_match=SCOPE_MATCH,
            )
        eligible = _eligible_versions(connection, request.cutoff, company_ids)
        if not eligible:
            raise ReplayRefused(
                422,
                "no_eligible_source_versions",
                "no retainable Source Version is available at the cutoff",
            )
        # The latest `cap` of them, retained oldest first.
        selected = sorted(eligible[:cap], key=lambda v: (v["available_at"], v["id"]))
        job_id = job_id_for(REPLAY_KIND, key)
        row = (
            connection.execute(
                text(
                    "INSERT INTO replay_job (id, bank_id, cutoff, availability_convention,"
                    " company_ids, scope, question_set, question_set_version,"
                    " question_set_sha256, questions, max_source_versions,"
                    " eligible_source_versions, job_id, requested_by) VALUES (:id, :bank,"
                    " :cutoff, :convention, CAST(:companies AS jsonb), CAST(:scope AS jsonb),"
                    " :set, :set_version, :set_sha, CAST(:questions AS jsonb), :cap, :eligible,"
                    " :job, :actor) RETURNING *"
                ),
                {
                    "id": replay_id,
                    "bank": bank_id_for(replay_id),
                    "cutoff": request.cutoff,
                    "convention": AVAILABILITY_CONVENTION,
                    "companies": _json([str(c) for c in company_ids]),
                    "scope": scope.model_dump_json(),
                    "set": request.question_set,
                    "set_version": question_set.version,
                    "set_sha": question_set.sha256,
                    "questions": _json([q.model_dump() for q in question_set.questions]),
                    "cap": cap,
                    "eligible": len(eligible),
                    "job": job_id,
                    "actor": actor.name,
                },
            )
            .mappings()
            .one()
        )
        for position, version in enumerate(selected):
            connection.execute(
                text(
                    "INSERT INTO replay_source_version (replay_job_id, position,"
                    " source_version_id, available_at, available_at_basis)"
                    " VALUES (:replay, :position, :version, :available_at, :basis)"
                ),
                {
                    "replay": replay_id,
                    "position": position,
                    "version": version["id"],
                    "available_at": version["available_at"],
                    "basis": version["available_at_basis"],
                },
            )
        record(
            connection,
            actor,
            "replay_job.requested",
            entity_type="replay_job",
            entity_id=str(replay_id),
            new_hash=content_hash(
                dict(row) | {"source_versions": [str(v["id"]) for v in selected]}
            ),
        )
        payload = ReplayPayload(replay_job_id=replay_id).model_dump(mode="json")
        queue.enqueue_within(connection, REPLAY_KIND, key, payload)
    return replay_id


def request_cancel(engine: Engine, actor: Actor, replay_id: uuid.UUID) -> bool | None:
    """Ask a replay to stop: its next step deletes its bank. None if there is no such replay;
    False if it is already finishing or finished (audited when it is asked)."""
    with engine.begin() as connection:
        old = _locked(connection, replay_id)
        if old is None:
            return None
        if old["stage"] in ("delete_bank", "done"):
            return False
        if old["cancel_requested_at"] is not None:
            return True
        new = (
            connection.execute(
                text(
                    "UPDATE replay_job SET cancel_requested_at = now(), updated_at = now()"
                    " WHERE id = :id RETURNING *"
                ),
                {"id": replay_id},
            )
            .mappings()
            .one()
        )
        record(
            connection,
            actor,
            "replay_job.cancel_requested",
            entity_type="replay_job",
            entity_id=str(replay_id),
            old_hash=content_hash(dict(old)),
            new_hash=content_hash(dict(new)),
        )
    return True


def _eligible_versions(
    connection: Connection, cutoff: datetime, company_ids: list[uuid.UUID]
) -> list[RowMapping]:
    """The retainable Source Versions available at the cutoff, newest first: each Source
    Document's latest version by then (the corrected availability view)."""
    return list(
        connection.execute(
            text(
                "SELECT id, available_at, available_at_basis FROM ("
                "  SELECT DISTINCT ON (v.source_document_id) v.id, v.parse_status, v.language,"
                "    v.parsed_object_uri, a.available_at, a.available_at_basis"
                "  FROM source_version v"
                "  JOIN source_version_availability a ON a.source_version_id = v.id"
                "  JOIN source_document d ON d.id = v.source_document_id"
                "  WHERE a.available_at <= :cutoff AND d.company_id IS NOT NULL"
                "    AND (CAST(:every AS boolean) OR d.company_id = ANY(:companies))"
                "  ORDER BY v.source_document_id, v.version_number DESC"
                ") latest WHERE parse_status = ANY(:parses) AND language = ANY(:languages)"
                " AND parsed_object_uri IS NOT NULL"
                " ORDER BY available_at DESC, id DESC"
            ),
            {
                "cutoff": cutoff,
                "every": not company_ids,
                "companies": company_ids,
                "parses": list(RETAINABLE_PARSES),
                "languages": list(RETAINABLE_LANGUAGES),
            },
        ).mappings()
    )


@dataclass(frozen=True)
class ReplayTimings:
    poll_timeout: float
    poll_interval: float
    poll_attempts: int  # waits per operation before a retain fails or consolidation times out
    consolidation_timeout: float


class ReplayStepFailed(Exception):
    """A step failed for a reason of its own (not quota or availability): the replay ends."""


class Replays:
    """Runs a replay's steps (see the module)."""

    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        actor: Actor,
        universe: Universe,
        template: BankTemplate,
        gateway_for: "GatewayFactory",
        timings: ReplayTimings,
        *,
        extractor: RetainExtractor | None = None,
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._actor = actor
        self._universe = universe
        self._template = template
        self._gateway_for = gateway_for
        self._timings = timings
        # The extractor the replay's retain items ask for, as production's do
        # (`ATLAS_RETAIN_EXTRACTOR`); a Hindsight without such a route ignores the key.
        self._extractor: RetainExtractor | None = extractor

    def run(self, replay_id: uuid.UUID, job: Job) -> Artifacts:
        """One step. Raises `Requeue` while steps remain; returns once the bank is deleted."""
        row = self._row(replay_id)
        base: Artifacts = {"replay_job_id": str(replay_id), "bank_id": row["bank_id"]}
        if row["stage"] == "done":
            return base | {"outcome": f"already_{row['status']}"}
        if row["status"] == "pending":
            row = self._update(replay_id, "status = 'running', started_at = now()")
        stage: str = row["stage"]
        try:
            if row["cancel_requested_at"] is not None and stage not in ("delete_bank", "done"):
                self._conclude(replay_id, "cancelled", "cancelled at the owner's request")
                raise Requeue(f"replay {replay_id} cancelled; deleting its bank")
            with self._gateway_for(row["bank_id"]) as gateway:
                finished = self._step(row, gateway)
        except Requeue:
            raise
        except Exception as error:
            if classify_failure(error) is not None:
                raise  # quota or outage: the queue pauses, and the replay resumes here
            message = f"{type(error).__name__}: {error}"
            if stage == "delete_bank":
                self._delete_failed(replay_id, message, last=job.attempts >= job.max_attempts)
                raise
            self._conclude(replay_id, "failed", f"{stage}: {message}")
            raise Requeue(f"replay {replay_id} failed at {stage}; deleting its bank") from None
        if finished is not None:
            return base | finished
        raise Requeue(f"replay {replay_id}: {stage} step done")

    def _step(self, row: RowMapping, gateway: HindsightGateway) -> Artifacts | None:
        stage = row["stage"]
        if stage == "create_bank":
            self._create_bank(row, gateway)
        elif stage == "retain":
            self._retain_next(row, gateway)
        elif stage == "consolidate":
            self._consolidate(row, gateway)
        elif stage == "questions":
            self._ask_next(row, gateway)
        else:
            return self._delete_bank(row, gateway)
        return None

    # --- create_bank ---------------------------------------------------------------------------

    def _create_bank(self, row: RowMapping, gateway: HindsightGateway) -> None:
        manifest = {k: v for k, v in self._template.manifest.items() if k != "mental_models"}
        template = BankTemplate(template_version=self._template.template_version, manifest=manifest)
        applied = apply_template(self._engine, gateway, template, self._actor)
        self._update(
            row["id"],
            "template_version = :version, template_manifest_sha256 = :sha, stage = 'retain',"
            " cursor = 0",
            {"version": applied.template_version, "sha": applied.manifest_sha256},
        )

    # --- retain --------------------------------------------------------------------------------

    def _retain_next(self, row: RowMapping, gateway: HindsightGateway) -> None:
        replay_id = row["id"]
        with self._engine.connect() as connection:
            selected = (
                connection.execute(
                    text(
                        "SELECT * FROM replay_source_version WHERE replay_job_id = :id"
                        " AND position = :position"
                    ),
                    {"id": replay_id, "position": row["cursor"]},
                )
                .mappings()
                .one_or_none()
            )
        if selected is None:
            self._update(replay_id, "stage = 'consolidate', cursor = 0")
            return
        operation_id: str | None = selected["operation_id"]
        if selected["retain_status"] == "pending":
            operation_id = self._submit(replay_id, selected["source_version_id"], gateway)
        assert operation_id is not None
        try:
            operation = gateway.wait_for_operation(
                operation_id,
                timeout=self._timings.poll_timeout,
                poll_interval=self._timings.poll_interval,
            )
        except OperationTimeout as timeout:
            waited = self._waited(replay_id, selected, timeout.last_status)
            if waited >= self._timings.poll_attempts:
                raise ReplayStepFailed(
                    f"the retain of Source Version {selected['source_version_id']} was still"
                    f" {timeout.last_status!r} after {waited} waits"
                ) from None
            return
        self._record_operation(operation_id, operation.status, operation.error_message)
        if not operation.succeeded:
            error = operation.error_message or f"the operation ended {operation.status}"
            error_class = operation_error_class(operation)
            if error_class != "permanent":
                # Resubmitted once the pause lifts, as a new batch under the same IDs.
                self._set_version(replay_id, selected["position"], "retain_status = 'pending'")
                raise TransientFailure(error_class, f"replay retain {operation_id}: {error}")
            self._set_version(
                replay_id,
                selected["position"],
                "retain_status = 'failed', error = :error",
                {"error": error},
            )
            raise ReplayStepFailed(
                f"the retain of Source Version {selected['source_version_id']} failed: {error}"
            )
        facts = self._count_facts(replay_id, selected["source_version_id"], gateway)
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE replay_source_version SET retain_status = 'completed', facts = :facts"
                    " WHERE replay_job_id = :id AND position = :position"
                ),
                {"facts": facts, "id": replay_id, "position": selected["position"]},
            )
            connection.execute(
                text(
                    "UPDATE replay_job SET cursor = cursor + 1, updated_at = now() WHERE id = :id"
                ),
                {"id": replay_id},
            )

    def _submit(
        self, replay_id: uuid.UUID, source_version_id: uuid.UUID, gateway: HindsightGateway
    ) -> str:
        version = load_version(self._engine, source_version_id)
        assert version.parsed_object_uri is not None
        parsed = self._archive.get(version.parsed_object_uri).decode("utf-8")
        sections = version_sections(version, parsed)
        tags = version_tags(version, self._universe)
        # The same context, entities and display metadata as a production retain.
        with self._engine.connect() as connection:
            companies = known_companies(connection)
        documents = [(section_document_id(version.id, s), s) for s in sections]
        items = [
            retain_item(
                version,
                parsed,
                document_id=document,
                anchor=section.anchor,
                heading=section.heading,
                start=section.start,
                end=section.end,
                tags=tags,
                companies=companies,
                extractor=self._extractor,
            )
            for document, section in documents
        ]
        submitted = gateway.retain_batch(items)
        with self._engine.begin() as connection:
            for document, section in documents:
                connection.execute(
                    text(
                        "INSERT INTO replay_document (replay_job_id, hindsight_document_id,"
                        " source_version_id, section_anchor, section_heading, char_start,"
                        " char_end) VALUES (:replay, :document, :version, :anchor, :heading,"
                        " :start, :end) ON CONFLICT DO NOTHING"
                    ),
                    {
                        "replay": replay_id,
                        "document": document,
                        "version": version.id,
                        "anchor": section.anchor,
                        "heading": section.heading,
                        "start": section.start,
                        "end": section.end,
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO replay_operation (operation_id, replay_job_id, kind,"
                    " source_version_id, status) VALUES (:operation, :replay, 'retain',"
                    " :version, 'pending') ON CONFLICT DO NOTHING"
                ),
                {"operation": submitted.operation_id, "replay": replay_id, "version": version.id},
            )
            connection.execute(
                text(
                    "UPDATE replay_source_version SET retain_status = 'submitted',"
                    " operation_id = :operation, polls = 0, sections = :sections, error = NULL"
                    " WHERE replay_job_id = :replay AND source_version_id = :version"
                ),
                {
                    "operation": submitted.operation_id,
                    "sections": len(documents),
                    "replay": replay_id,
                    "version": version.id,
                },
            )
        return submitted.operation_id

    def _waited(self, replay_id: uuid.UUID, selected: RowMapping, status: str) -> int:
        self._record_operation(selected["operation_id"], status, None, terminal=False)
        with self._engine.begin() as connection:
            return connection.execute(
                text(
                    "UPDATE replay_source_version SET polls = polls + 1"
                    " WHERE replay_job_id = :id AND position = :position RETURNING polls"
                ),
                {"id": replay_id, "position": selected["position"]},
            ).scalar_one()

    def _count_facts(
        self, replay_id: uuid.UUID, source_version_id: uuid.UUID, gateway: HindsightGateway
    ) -> int:
        with self._engine.connect() as connection:
            documents = list(
                connection.execute(
                    text(
                        "SELECT hindsight_document_id FROM replay_document"
                        " WHERE replay_job_id = :id AND source_version_id = :version"
                    ),
                    {"id": replay_id, "version": source_version_id},
                ).scalars()
            )
        counts: dict[str, int] = {}
        for document in documents:
            try:
                counts[document] = gateway.get_document(document).memory_unit_count
            except HindsightNotFound:
                counts[document] = 0
        with self._engine.begin() as connection:
            for document, count in counts.items():
                connection.execute(
                    text(
                        "UPDATE replay_document SET fact_count = :count"
                        " WHERE replay_job_id = :id AND hindsight_document_id = :document"
                    ),
                    {"count": count, "id": replay_id, "document": document},
                )
        return sum(counts.values())

    # --- consolidate ---------------------------------------------------------------------------

    def _consolidate(self, row: RowMapping, gateway: HindsightGateway) -> None:
        replay_id = row["id"]
        state: dict[str, Any] = dict(row["consolidation"] or {})
        if not state.get("operation_id"):
            submitted = gateway.consolidate()
            state = {"operation_id": submitted.operation_id, "status": "pending", "polls": 0}
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO replay_operation (operation_id, replay_job_id, kind, status)"
                        " VALUES (:operation, :replay, 'consolidation', 'pending')"
                        " ON CONFLICT DO NOTHING"
                    ),
                    {"operation": submitted.operation_id, "replay": replay_id},
                )
                _set_consolidation(connection, replay_id, state)
        operation_id = str(state["operation_id"])
        try:
            operation = gateway.wait_for_operation(
                operation_id,
                timeout=self._timings.consolidation_timeout,
                poll_interval=self._timings.poll_interval,
            )
        except OperationTimeout as timeout:
            state["polls"] = int(state.get("polls", 0)) + 1
            state["status"] = timeout.last_status
            self._record_operation(operation_id, timeout.last_status, None, terminal=False)
            done = state["polls"] >= self._timings.poll_attempts
            if done:
                state["status"] = "timed_out"  # bounded: the questions run on what there is
            with self._engine.begin() as connection:
                _set_consolidation(connection, replay_id, state)
                if done:
                    _advance(connection, replay_id, "questions")
            return
        self._record_operation(operation_id, operation.status, operation.error_message)
        error_class = None if operation.succeeded else operation_error_class(operation)
        if error_class is not None and error_class != "permanent":
            with self._engine.begin() as connection:
                _set_consolidation(connection, replay_id, None)  # asked again after the pause
            raise TransientFailure(
                error_class, f"replay consolidation {operation_id}: {operation.error_message}"
            )
        state["status"] = operation.status
        if operation.error_message:
            state["error"] = operation.error_message
        with self._engine.begin() as connection:
            _set_consolidation(connection, replay_id, state)
            _advance(connection, replay_id, "questions")

    # --- questions -----------------------------------------------------------------------------

    def _ask_next(self, row: RowMapping, gateway: HindsightGateway) -> None:
        replay_id = row["id"]
        questions = [ReplayQuestion.model_validate(q) for q in row["questions"]]
        position: int = row["cursor"]
        if position >= len(questions):
            self._conclude(replay_id, "completed", None)
            return
        question = questions[position]
        scope = AppliedScope.model_validate(row["scope"])
        tag_scope = TagScope(scope.tags, scope.tags_match)
        visible = self._visible(replay_id)
        resolver = ProvenanceResolver(
            self._engine, self._archive, gateway, sections=replay_sections(replay_id)
        )
        # Recency is judged from the cutoff, as a researcher then would have had it
        # (memory-quality ticket 07).
        recalled = gateway.recall(question.question, scope=tag_scope, query_timestamp=row["cutoff"])
        memories = [_recalled(memory, recalled, resolver) for memory in recalled.memories]
        # Asked as a research answer is by default (memory-quality ticket 10); the replay's
        # answer row is one `codex` unit (`atlas.jobs.budget`).
        reflected = gateway.reflect(
            question.question,
            scope=tag_scope,
            include_facts=True,
            budget="mid",
            exclude_mental_models=True,
        )
        citations = resolver.resolve_answer(
            reflected.text, reflected.memories, reflected.mental_models
        )
        leaked_recall = [m for m in memories if _named_versions(m) - visible]
        leaked_citations = [c for c in citations if _cited_versions(c) - visible]
        leaked_ids = sorted(
            {v for m in leaked_recall for v in _named_versions(m) - visible}
            | {v for c in leaked_citations for v in _cited_versions(c) - visible}
        )
        leakage = {
            "recall_memories": len(leaked_recall),
            "citations": len(leaked_citations),
            "source_version_ids": [str(v) for v in leaked_ids],
        }
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO replay_answer (replay_job_id, position, question_key, question,"
                    " recall, answer_text, citations, leakage) VALUES (:replay, :position, :key,"
                    " :question, CAST(:recall AS jsonb), :answer, CAST(:citations AS jsonb),"
                    " CAST(:leakage AS jsonb)) ON CONFLICT DO NOTHING"
                ),
                {
                    "replay": replay_id,
                    "position": position,
                    "key": question.key,
                    "question": question.question,
                    "recall": _json([m.model_dump(mode="json") for m in memories]),
                    "answer": reflected.text,
                    "citations": _json([c.model_dump(mode="json") for c in citations]),
                    "leakage": _json(leakage),
                },
            )
            connection.execute(
                text(
                    "UPDATE replay_job SET cursor = cursor + 1, updated_at = now() WHERE id = :id"
                ),
                {"id": replay_id},
            )

    def _visible(self, replay_id: uuid.UUID) -> set[uuid.UUID]:
        with self._engine.connect() as connection:
            return set(
                connection.execute(
                    text(
                        "SELECT source_version_id FROM replay_source_version"
                        " WHERE replay_job_id = :id"
                    ),
                    {"id": replay_id},
                ).scalars()
            )

    # --- the end: conclude, then delete the bank -----------------------------------------------

    def _conclude(
        self,
        replay_id: uuid.UUID,
        final_status: Literal["completed", "failed", "cancelled"],
        error: str | None,
    ) -> None:
        """Record how the replay ends (and its leakage), and move it to `delete_bank`."""
        with self._engine.begin() as connection:
            leakage = _leakage(connection, replay_id)
            connection.execute(
                text(
                    "UPDATE replay_job SET final_status = :final, error = :error,"
                    " leakage = CAST(:leakage AS jsonb), stage = 'delete_bank', cursor = 0,"
                    " updated_at = now() WHERE id = :id AND stage NOT IN ('delete_bank', 'done')"
                ),
                {
                    "final": final_status,
                    "error": error[:2000] if error else None,
                    "leakage": _json(leakage),
                    "id": replay_id,
                },
            )

    def _delete_bank(self, row: RowMapping, gateway: HindsightGateway) -> Artifacts:
        try:
            deleted = gateway.delete_bank().success
        except HindsightNotFound:
            deleted = True  # never created, or already gone
        if not deleted:
            raise ReplayStepFailed(f"Hindsight did not delete {row['bank_id']}")
        finished = self._finish(row["id"], "bank_deleted_at = now(), bank_delete_error = NULL")
        return {
            "outcome": finished["status"],
            "bank_deleted": True,
            "leakage": finished["leakage"],
        }

    def _delete_failed(self, replay_id: uuid.UUID, message: str, *, last: bool) -> None:
        if last:
            self._finish(replay_id, "bank_delete_error = :error", {"error": message[:2000]})
        else:
            self._update(replay_id, "bank_delete_error = :error", {"error": message[:2000]})

    def _finish(
        self, replay_id: uuid.UUID, assignments: str, params: dict[str, Any] | None = None
    ) -> RowMapping:
        with self._engine.begin() as connection:
            old = _locked(connection, replay_id)
            assert old is not None
            new = (
                connection.execute(
                    text(
                        f"UPDATE replay_job SET {assignments}, stage = 'done',"  # noqa: S608 (constant fragments)
                        " status = final_status, finished_at = now(), updated_at = now()"
                        " WHERE id = :id RETURNING *"
                    ),
                    {"id": replay_id, **(params or {})},
                )
                .mappings()
                .one()
            )
            record(
                connection,
                self._actor,
                "replay_job.finished",
                entity_type="replay_job",
                entity_id=str(replay_id),
                old_hash=content_hash(dict(old)),
                new_hash=content_hash(dict(new)),
            )
        return new

    # --- shared --------------------------------------------------------------------------------

    def _record_operation(
        self, operation_id: str, status: str, error: str | None, *, terminal: bool = True
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE replay_operation SET status = :status, error_message = :error,"
                    " completed_at = CASE WHEN :terminal THEN now() END"
                    " WHERE operation_id = :operation"
                ),
                {"status": status, "error": error, "terminal": terminal, "operation": operation_id},
            )

    def _set_version(
        self,
        replay_id: uuid.UUID,
        position: int,
        assignments: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE replay_source_version SET {assignments}"  # noqa: S608 (constant fragments)
                    " WHERE replay_job_id = :id AND position = :position"
                ),
                {"id": replay_id, "position": position, **(params or {})},
            )

    def _row(self, replay_id: uuid.UUID) -> RowMapping:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM replay_job WHERE id = :id"), {"id": replay_id}
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise LookupError(f"replay {replay_id} does not exist")
        return row

    def _update(
        self, replay_id: uuid.UUID, assignments: str, params: dict[str, Any] | None = None
    ) -> RowMapping:
        with self._engine.begin() as connection:
            return (
                connection.execute(
                    text(
                        f"UPDATE replay_job SET {assignments}, updated_at = now()"  # noqa: S608 (constant fragments)
                        " WHERE id = :id RETURNING *"
                    ),
                    {"id": replay_id, **(params or {})},
                )
                .mappings()
                .one()
            )


class GatewayFactory:
    """The gateway for one replay bank on the local Hindsight (`ATLAS_REPLAY_HINDSIGHT_URL`)."""

    def __init__(self, url: str | None, api_key: str | None) -> None:
        self._url = url
        self._api_key = api_key

    def __call__(self, bank_id: str) -> HindsightGateway:
        if not self._url:
            raise HindsightNotConfigured
        if not bank_id.startswith(REPLAY_BANK_PREFIX):
            raise ValueError(f"{bank_id!r} is not a replay bank")
        return HindsightGateway(self._url, bank_id, self._api_key)


def replay_sections(replay_id: uuid.UUID) -> SectionLookup:
    """The replay's own section ledger, for its provenance resolver: a document resolves only
    to a section of a Source Version the replay retained."""

    def lookup(connection: Connection, document_id: str) -> RowMapping | None:
        return (
            connection.execute(
                text(
                    "SELECT m.hindsight_document_id, m.source_version_id,"
                    " m.section_anchor, m.section_heading, m.char_start, m.char_end,"
                    " v.source_document_id, a.available_at, a.available_at_basis,"
                    " v.parsed_object_uri, d.company_id, d.form_type"
                    " FROM replay_document m"
                    " JOIN source_version v ON v.id = m.source_version_id"
                    " JOIN source_version_availability a ON a.source_version_id = v.id"
                    " JOIN source_document d ON d.id = v.source_document_id"
                    " WHERE m.hindsight_document_id = :document AND m.replay_job_id = :replay"
                ),
                {"document": document_id, "replay": replay_id},
            )
            .mappings()
            .one_or_none()
        )

    return lookup


def _recalled(
    memory: Memory, answer: RecallResult, resolver: ProvenanceResolver
) -> ReplayRecalledMemory:
    return ReplayRecalledMemory(
        **dict(recalled_memory(memory, answer, resolver)),
        document_id=memory.document_id,
        source_version_id=memory.metadata.get("source_version_id"),
    )


def _named_versions(memory: ReplayRecalledMemory) -> set[uuid.UUID]:
    """Every Source Version a recalled memory names: in its document ID, its metadata and
    its resolved provenance."""
    named = {source.source_version_id for source in memory.provenance.sources}
    for value in (_document_version(memory.document_id), memory.source_version_id):
        parsed = _uuid(value)
        if parsed is not None:
            named.add(parsed)
    return named


def _cited_versions(citation: Citation) -> set[uuid.UUID]:
    """The Source Versions a resolved citation (or quote) leads to."""
    if citation.state != "resolved":
        return set()
    cited = {source.source_version_id for source in citation.sources}
    if citation.quote is not None:
        cited.add(citation.quote.source_version_id)
    return cited


def _document_version(document_id: str | None) -> str | None:
    """`srcv:<source_version_uuid>:<anchor>` (ADR-0001) -> the UUID."""
    if not document_id or not document_id.startswith("srcv:"):
        return None
    return document_id.split(":")[1]


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def _leakage(connection: Connection, replay_id: uuid.UUID) -> dict[str, Any]:
    """`ReplayLeakage`: retained versions whose availability is after the cutoff *now* (a
    correction made later counts), plus the answers' leakage so far."""
    retained = list(
        connection.execute(
            text(
                "SELECT s.source_version_id FROM replay_source_version s"
                " JOIN replay_job r ON r.id = s.replay_job_id"
                " JOIN source_version_availability a ON a.source_version_id = s.source_version_id"
                " WHERE s.replay_job_id = :id AND s.retain_status <> 'pending'"
                " AND a.available_at > r.cutoff"
            ),
            {"id": replay_id},
        ).scalars()
    )
    answers = connection.execute(
        text("SELECT leakage FROM replay_answer WHERE replay_job_id = :id"), {"id": replay_id}
    ).scalars()
    recall_memories = citations = 0
    leaked = {str(v) for v in retained}
    for answer in answers:
        recall_memories += int(answer["recall_memories"])
        citations += int(answer["citations"])
        leaked.update(answer["source_version_ids"])
    return {
        "retained": len(retained),
        "recall_memories": recall_memories,
        "citations": citations,
        "source_version_ids": sorted(leaked),
        "future_accepted": len(retained) + recall_memories + citations,
    }


def _set_consolidation(
    connection: Connection, replay_id: uuid.UUID, state: dict[str, Any] | None
) -> None:
    connection.execute(
        text(
            "UPDATE replay_job SET consolidation = CAST(:state AS jsonb), updated_at = now()"
            " WHERE id = :id"
        ),
        {"state": None if state is None else _json(state), "id": replay_id},
    )


def _advance(connection: Connection, replay_id: uuid.UUID, stage: str) -> None:
    connection.execute(
        text("UPDATE replay_job SET stage = :stage, cursor = 0, updated_at = now() WHERE id = :id"),
        {"stage": stage, "id": replay_id},
    )


def _locked(connection: Connection, replay_id: uuid.UUID) -> RowMapping | None:
    return (
        connection.execute(
            text("SELECT * FROM replay_job WHERE id = :id FOR UPDATE"), {"id": replay_id}
        )
        .mappings()
        .one_or_none()
    )


def _json(value: object) -> str:
    return json.dumps(value)
