"""The research query service: scoped recall, and reflect as a job (spec Part B stories 16-25).

- **Scope.** A question is scoped by company IDs and theme IDs (the theme slugs of the
  company universe config). They become the retain tags `company:<uuid>` and `theme:<slug>`,
  matched `any_strict`: a memory must carry at least one of them, and untagged memories never
  match. Several companies and themes widen the scope (a union), never narrow it.
- **Recall** is synchronous: Hindsight's strictly scoped recall, each memory resolved to its
  Source Version section by the provenance resolver.
- **Reflect** is a job. The request records a `pending` research answer (audited) and
  enqueues a `reflect` job for it; the job asks Hindsight, resolves every citation and quote,
  validates any structured output against its schema, and stores the answer (audited). The
  job starts a run when LiteLLM and Hindsight are both configured, so the answer records the
  models, template and versions that produced it.
"""

import json
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Self

from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.archive import Archive
from atlas.audit import Actor, AuditEvent, content_hash, record
from atlas.companies import Universe
from atlas.hindsight import (
    Budget,
    HindsightGateway,
    HindsightRuleViolation,
    ReflectAnswer,
    TagMatch,
    TagScope,
)
from atlas.hindsight.models import check_response_schema
from atlas.jobs.queue import Artifacts, Job, JobQueue, job_id_for
from atlas.research.provenance import (
    Citation,
    CitationState,
    Evidence,
    ProvenanceResolver,
    evidence_from,
    state_counts,
)
from atlas.research.quotes import QUOTE_RULE
from atlas.runs import RunRecorder

REFLECT_KIND = "reflect"
SCOPE_MATCH: TagMatch = "any_strict"


class ResearchRefused(Exception):
    """A request Atlas won't run: `code` is the API error code (422)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ResearchScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID], max_length=100)
    theme_ids: list[str] = Field(
        default_factory=list[str], max_length=100, description="theme slugs, e.g. photonics"
    )

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not self.company_ids and not self.theme_ids:
            raise ValueError("a scope needs at least one company or theme")
        return self


class AppliedScope(BaseModel):
    """The scope as sent to Hindsight: the tags and their strict match mode."""

    company_ids: list[uuid.UUID]
    theme_ids: list[str]
    tags: list[str]
    tags_match: TagMatch


class RecallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    scope: ResearchScope
    budget: Budget = "mid"


class RecalledMemory(BaseModel):
    memory_id: str
    type: str
    text: str
    context: str | None
    tags: list[str]
    occurred_start: datetime | None
    occurred_end: datetime | None
    mentioned_at: datetime | None
    provenance: Citation


class RecallResponse(BaseModel):
    query: str
    scope: AppliedScope
    memories: list[RecalledMemory]
    counts: dict[CitationState, int]  # memories by provenance state
    evidence: list[Evidence]  # the sections behind resolved memories only


class ReflectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    scope: ResearchScope
    response_schema: dict[str, JsonValue] | None = Field(
        default=None,
        description="a JSON Schema object for structured output; union types are refused",
    )


class ReflectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research_answer_id: uuid.UUID


class Research:
    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        gateway: HindsightGateway,
        actor: Actor,
        universe: Callable[[], Universe],
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._gateway = gateway
        self._actor = actor
        self._universe = universe

    @property
    def bank_id(self) -> str:
        return self._gateway.bank_id

    # --- scope ---------------------------------------------------------------------------------

    def apply_scope(self, scope: ResearchScope) -> AppliedScope:
        """Check the scope's companies and themes exist; raises `ResearchRefused`."""
        company_ids = list(dict.fromkeys(scope.company_ids))
        theme_ids = list(dict.fromkeys(scope.theme_ids))
        if company_ids:
            with self._engine.connect() as connection:
                known = set(
                    connection.execute(
                        text("SELECT id FROM company WHERE id = ANY(:ids)"), {"ids": company_ids}
                    ).scalars()
                )
            unknown = [str(c) for c in company_ids if c not in known]
            if unknown:
                raise ResearchRefused("unknown_company", f"unknown company: {', '.join(unknown)}")
        if theme_ids:
            themes = self._universe().themes
            unknown = [t for t in theme_ids if t not in themes]
            if unknown:
                raise ResearchRefused("unknown_theme", f"unknown theme: {', '.join(unknown)}")
        tags = [f"company:{c}" for c in company_ids] + [f"theme:{t}" for t in theme_ids]
        return AppliedScope(
            company_ids=company_ids, theme_ids=theme_ids, tags=tags, tags_match=SCOPE_MATCH
        )

    # --- recall --------------------------------------------------------------------------------

    def recall(self, request: RecallRequest) -> RecallResponse:
        scope = self.apply_scope(request.scope)
        result = self._gateway.recall(
            request.query, scope=TagScope(scope.tags, scope.tags_match), budget=request.budget
        )
        resolver = ProvenanceResolver(self._engine, self._archive, self._gateway)
        memories = [
            RecalledMemory(
                memory_id=memory.id,
                type=memory.type,
                text=memory.text,
                context=memory.context,
                tags=memory.tags,
                occurred_start=memory.occurred_start,
                occurred_end=memory.occurred_end,
                mentioned_at=memory.mentioned_at,
                provenance=resolver.resolve_recalled(memory),
            )
            for memory in result.memories
        ]
        provenance = [memory.provenance for memory in memories]
        return RecallResponse(
            query=request.query,
            scope=scope,
            memories=memories,
            counts=state_counts(provenance),
            evidence=evidence_from(provenance),
        )

    # --- reflect -------------------------------------------------------------------------------

    def request_reflect(self, request: ReflectRequest) -> tuple[uuid.UUID, uuid.UUID, AuditEvent]:
        """Record a pending research answer and enqueue its reflect job.

        Returns (research answer ID, job ID, the audit event). Raises `ResearchRefused`.
        """
        if request.response_schema is not None:
            check_schema(request.response_schema)
        scope = self.apply_scope(request.scope)
        answer_id = uuid.uuid4()
        key = f"reflect:{answer_id}"
        job_id = job_id_for(REFLECT_KIND, key)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "INSERT INTO research_answer (id, bank_id, question, scope,"
                        " response_schema, status, job_id) VALUES (:id, :bank, :question,"
                        " CAST(:scope AS jsonb), CAST(:schema AS jsonb), 'pending', :job)"
                        " RETURNING *"
                    ),
                    {
                        "id": answer_id,
                        "bank": self.bank_id,
                        "question": request.question,
                        "scope": scope.model_dump_json(),
                        "schema": _json_or_null(request.response_schema),
                        "job": job_id,
                    },
                )
                .mappings()
                .one()
            )
            event = record(
                connection,
                self._actor,
                "research_answer.requested",
                entity_type="research_answer",
                entity_id=str(answer_id),
                new_hash=content_hash(dict(row)),
            )
        payload = ReflectPayload(research_answer_id=answer_id).model_dump(mode="json")
        JobQueue(self._engine).enqueue(REFLECT_KIND, key, payload)
        return answer_id, job_id, event

    def answer(self, answer_id: uuid.UUID, job: Job, runs: RunRecorder | None) -> Artifacts:
        """The reflect job: ask Hindsight, resolve the citations, store the answer."""
        row = self._row(answer_id)
        base: Artifacts = {"research_answer_id": str(answer_id)}
        if row["status"] != "pending":
            return base | {"outcome": f"already_{row['status']}"}
        try:
            return base | self._answer(row, runs)
        except Exception as error:
            if job.attempts >= job.max_attempts:
                self._fail(answer_id, f"{type(error).__name__}: {error}")
            raise

    def _answer(self, row: RowMapping, runs: RunRecorder | None) -> Artifacts:
        scope = AppliedScope.model_validate(row["scope"])
        schema: dict[str, Any] | None = row["response_schema"]
        run = runs.start(REFLECT_KIND) if runs is not None else None
        tokens = (0, 0)
        try:
            reflected = self._gateway.reflect(
                row["question"],
                scope=TagScope(scope.tags, scope.tags_match),
                response_schema=schema,
                include_facts=True,
            )
            if reflected.usage is not None:
                tokens = (reflected.usage.input_tokens, reflected.usage.output_tokens)
        finally:
            if runs is not None and run is not None:
                runs.finish(run.id, tokens_in=tokens[0], tokens_out=tokens[1])
        resolver = ProvenanceResolver(self._engine, self._archive, self._gateway)
        citations = resolver.resolve_answer(reflected.text, reflected.memories)
        structured_error = structured_output_error(schema, reflected)
        raw = [memory.model_dump(mode="json") for memory in reflected.memories]
        with self._engine.begin() as connection:
            old = self._locked(connection, row["id"])
            if old["status"] != "pending":
                return {"outcome": f"already_{old['status']}"}
            new = (
                connection.execute(
                    text(
                        "UPDATE research_answer SET status = 'completed', answer_text = :answer,"
                        " structured_output = CAST(:output AS jsonb),"
                        " structured_output_error = :output_error,"
                        " raw_citations = CAST(:raw AS jsonb),"
                        " citations = CAST(:citations AS jsonb), quote_rule = :rule,"
                        " run_id = :run, answered_at = now() WHERE id = :id RETURNING *"
                    ),
                    {
                        "id": row["id"],
                        "answer": reflected.text,
                        "output": _json_or_null(reflected.structured_output),
                        "output_error": structured_error,
                        "raw": json.dumps(raw),
                        "citations": json.dumps(
                            [citation.model_dump(mode="json") for citation in citations]
                        ),
                        "rule": QUOTE_RULE,
                        "run": run.id if run is not None else None,
                    },
                )
                .mappings()
                .one()
            )
            record(
                connection,
                self._actor,
                "research_answer.answered",
                entity_type="research_answer",
                entity_id=str(row["id"]),
                old_hash=content_hash(dict(old)),
                new_hash=content_hash(dict(new)),
            )
        counts = state_counts(citations)
        return {
            "outcome": "answered",
            "citations": {state: count for state, count in counts.items()},
            "run_id": str(run.id) if run is not None else None,
        }

    def _fail(self, answer_id: uuid.UUID, error: str) -> None:
        with self._engine.begin() as connection:
            old = self._locked(connection, answer_id)
            if old["status"] != "pending":
                return
            new = (
                connection.execute(
                    text(
                        "UPDATE research_answer SET status = 'failed', error = :error"
                        " WHERE id = :id RETURNING *"
                    ),
                    {"id": answer_id, "error": error[:2000]},
                )
                .mappings()
                .one()
            )
            record(
                connection,
                self._actor,
                "research_answer.failed",
                entity_type="research_answer",
                entity_id=str(answer_id),
                old_hash=content_hash(dict(old)),
                new_hash=content_hash(dict(new)),
            )

    def _row(self, answer_id: uuid.UUID) -> RowMapping:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM research_answer WHERE id = :id"), {"id": answer_id}
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise LookupError(f"research answer {answer_id} does not exist")
        return row

    def _locked(self, connection: Connection, answer_id: uuid.UUID) -> RowMapping:
        return (
            connection.execute(
                text("SELECT * FROM research_answer WHERE id = :id FOR UPDATE"), {"id": answer_id}
            )
            .mappings()
            .one()
        )


def check_schema(schema: Mapping[str, Any]) -> None:
    """A response schema Atlas can send: a valid JSON Schema object with no union types."""
    try:
        check_response_schema(schema)
    except HindsightRuleViolation as error:
        raise ResearchRefused("invalid_response_schema", str(error)) from error
    try:
        validator_for(schema).check_schema(dict(schema))
    except SchemaError as error:
        raise ResearchRefused(
            "invalid_response_schema", f"not a valid JSON Schema: {error.message}"
        ) from error
    if schema.get("type") != "object":
        raise ResearchRefused(
            "invalid_response_schema", 'the response schema must have "type": "object"'
        )


def structured_output_error(schema: Mapping[str, Any] | None, answer: ReflectAnswer) -> str | None:
    """Why the structured output can't be used, or None (always None without a schema).

    Hindsight's own `structured_output_error` wins; a missing output, or one that doesn't
    validate against the schema, is an error too, so a 200 never hides a malformed answer.
    """
    if schema is None:
        return None
    if answer.structured_output_error:
        return f"Hindsight: {answer.structured_output_error}"
    if answer.structured_output is None:
        return "Hindsight returned no structured output for the response schema"
    validator = validator_for(schema)(dict(schema))
    first: ValidationError | None = next(
        iter(validator.iter_errors(answer.structured_output)), None
    )
    if first is not None:
        where = "/".join(str(part) for part in first.absolute_path) or "(root)"
        return (
            f"the structured output does not match the response schema at {where}: {first.message}"
        )
    return None


def _json_or_null(value: object) -> str | None:
    return None if value is None else json.dumps(value)
