"""The `review_relationships` job: machine-review Assertions into Relationships.

The payload names Assertions (`assertion_ids`, at most `MAX_ASSERTIONS`) or, when it names
none, sweeps every open Assertion (unreviewed, corroborated or disputed) with a whitelisted
predicate that has no machine review yet, oldest first, up to `MAX_ASSERTIONS`. An Assertion
already reviewed is never reviewed again. One attempt:

1. **Eligibility.** An Assertion forms a Relationship only when its predicate is
   whitelisted (`predicate_not_whitelisted`), it is open (`assertion_rejected`,
   `assertion_superseded`), its `value_json.layer` is a known layer (`unknown_layer`), its
   object is present (a company, or `value_json.object_text` for a product predicate:
   `missing_object`) and differs from the subject (`self_relationship`), and its quote has
   directional language for the predicate (`no_directional_language`: co-mention is never a
   Relationship), for a product object in a clause that names the object
   (`cue_in_other_clause`, pilot-fixes ticket 09: "we expand InP capacity, while also
   operating VCSEL facilities" expands nothing for the VCSEL facilities). Otherwise it is
   recorded `not_eligible` with that reason and no edge.
2. **Deterministic checks** (`atlas.relationships.checks`): verbatim span, Tier A, explicit
   (unhedged) language. An Assertion that fails one joins its edge `needs_human_review`
   without asking the Reviewer.
3. **The Reviewer** is asked about the rest, `per_call` Assertions a call, within the job's
   run (its own `relationship_review` run, or the payload's unfinished `run_id`, kept across
   retries). Each Assertion is recorded in its own transaction as soon as its batch is
   answered, so a job requeued by an LLM quota or outage (the kind is pausable) resumes with
   the Assertions not yet reviewed. A quarantined answer sends its batch's edges to humans
   (`reviewer_quarantined`), as does an item the answer left out (`reviewer_no_answer`).
   When the run's token budget is spent, the job stops `budget_exhausted` and the rest stay
   unreviewed for a later job.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Engine, text

from atlas.archive import Archive, ArchiveIntegrityError, InvalidArchiveUri, ObjectNotFound
from atlas.audit import Actor
from atlas.claims.predicates import (
    LAYER_NAMES,
    LAYERS,
    PREDICATES,
    company_names,
    object_clause_cue,
)
from atlas.jobs.queue import Artifacts, Job
from atlas.relationships.checks import (
    DeterministicChecks,
    ReviewerAnswer,
    deterministic_checks,
    directional_language,
    review_outcome,
)
from atlas.relationships.reads import MachineOutcome, ReviewerStatus
from atlas.relationships.service import Edge, MachineReviewRecord, record_machine_review
from atlas.roles import (
    QuotedText,
    RoleCaller,
    RoleCallFailed,
    RoleOutputQuarantined,
    TokenBudgetExhausted,
    run_usage,
)
from atlas.roles.investigator import LayerOption
from atlas.roles.reviewer import (
    REVIEWER,
    EdgeParty,
    EdgeReview,
    EdgeSource,
    EdgeToReview,
    ReviewerRequest,
)
from atlas.runs import RunNotFound, RunRecorder

REVIEW_RELATIONSHIPS_KIND = "review_relationships"
REVIEWER_ACTOR = Actor("atlas-reviewer")
RUN_KIND = "relationship_review"
MAX_ASSERTIONS = 100
CONTEXT_CHARS = 600  # of parsed text each side of the quote, sent as its context
_OPEN = ("unreviewed", "corroborated", "disputed")


class ReviewRelationshipsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assertion_ids: list[uuid.UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_ASSERTIONS,
        description="the Assertions to review; omitted: every open one not yet reviewed",
    )
    run_id: uuid.UUID | None = Field(
        default=None, description="an unfinished run to call within; else the job starts one"
    )


@dataclass(frozen=True)
class _Candidate:
    """An Assertion under review, with its source."""

    id: uuid.UUID
    subject_company_id: uuid.UUID
    predicate: str
    object_company_id: uuid.UUID | None
    value_json: Any
    source_version_id: uuid.UUID
    quote: str
    span_start: int
    span_end: int
    verification_status: str
    parser_version: str  # the parse the span is in: its text is `parsed_object_uri`'s
    parsed_object_uri: str | None
    source_tier: str
    title: str
    publisher: str
    form_type: str | None
    filer_company_id: uuid.UUID | None


@dataclass(frozen=True)
class _Pending:
    """An eligible Assertion that passed the deterministic checks: for the Reviewer."""

    candidate: _Candidate
    edge: Edge
    checks: DeterministicChecks
    context: str


class RelationshipReviewer:
    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        caller: RoleCaller,
        runs: RunRecorder | None,
        *,
        per_call: int,
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._caller = caller
        self._runs = runs
        self._per_call = per_call
        self._texts: dict[tuple[uuid.UUID, str], str | None] = {}

    def review(self, job: Job) -> Artifacts:
        payload = ReviewRelationshipsPayload.model_validate(job.payload)
        candidates, not_found = self._candidates(payload)
        pending: list[_Pending] = []
        for candidate in candidates:
            refusal, edge = _eligibility(candidate)
            if edge is None:
                self._record(
                    job,
                    MachineReviewRecord(
                        assertion_id=candidate.id,
                        outcome="not_eligible",
                        reasons=[refusal or "not_eligible"],
                        reviewer_status="skipped",
                    ),
                    None,
                )
                continue
            parsed = self._parsed(candidate)
            checks = deterministic_checks(
                predicate=candidate.predicate,
                quote=candidate.quote,
                span_start=candidate.span_start,
                span_end=candidate.span_end,
                parsed_text=parsed,
                source_tier=candidate.source_tier,
            )
            if not checks.passed:
                outcome, reasons = review_outcome(checks, None)
                self._record(job, _record(candidate, checks, outcome, reasons, "skipped"), edge)
                continue
            assert parsed is not None
            start = max(0, candidate.span_start - CONTEXT_CHARS)
            context = parsed[start : candidate.span_end + CONTEXT_CHARS]
            pending.append(_Pending(candidate, edge, checks, context))

        status = "completed"
        if pending:
            run_id, owned = self._run_for(job, payload)
            companies = self._companies()
            for start in range(0, len(pending), self._per_call):
                batch = pending[start : start + self._per_call]
                if not self._ask(job, run_id, batch, companies):
                    status = "budget_exhausted"
                    break
            if owned:
                self._finish_run(run_id)
        return self._artifacts(job, status, not_found)

    # --- the Reviewer -------------------------------------------------------------------------

    def _ask(
        self,
        job: Job,
        run_id: uuid.UUID,
        batch: Sequence[_Pending],
        companies: dict[uuid.UUID, list[str]],
    ) -> bool:
        """Ask the Reviewer about `batch` and record each answer; False if the budget is spent."""
        items = {f"a{index + 1}": pending for index, pending in enumerate(batch)}
        request = ReviewerRequest(
            layers=[LayerOption(name=layer.name, covers=layer.covers) for layer in LAYERS],
            items=[_item(item_id, p, companies) for item_id, p in items.items()],
        )
        retrieved = [
            quoted
            for item_id, p in items.items()
            for quoted in (
                QuotedText(
                    id=f"{item_id}:quote", source=_span(p.candidate), text=p.candidate.quote
                ),
                QuotedText(id=f"{item_id}:context", source=_span(p.candidate), text=p.context),
            )
        ]
        answers: dict[str, EdgeReview] = {}
        missing = "reviewer_no_answer"
        role_call_id: uuid.UUID | None = None
        try:
            output, role_call_id = self._caller.call_recorded(
                REVIEWER, request, run_id=run_id, retrieved=retrieved
            )
            for answer in output.reviews:
                answers.setdefault(answer.item_id, answer)
        except TokenBudgetExhausted:
            return False
        except RoleOutputQuarantined as quarantined:
            role_call_id, missing = quarantined.role_call_id, "reviewer_quarantined"
        for item_id, p in items.items():
            answer = answers.get(item_id)
            if answer is None:
                outcome, reasons = review_outcome(p.checks, None, missing=missing)
                status: ReviewerStatus = (
                    "quarantined" if missing == "reviewer_quarantined" else "no_answer"
                )
                record = _record(p.candidate, p.checks, outcome, reasons, status)
            else:
                verdict = ReviewerAnswer(answer.verdict, answer.direction, answer.layer)
                outcome, reasons = review_outcome(p.checks, verdict)
                record = _record(p.candidate, p.checks, outcome, reasons, "answered", answer)
            self._record(job, replace(record, run_id=run_id, role_call_id=role_call_id), p.edge)
        return True

    # --- runs ---------------------------------------------------------------------------------

    def _run_for(self, job: Job, payload: ReviewRelationshipsPayload) -> tuple[uuid.UUID, bool]:
        with self._engine.connect() as connection:
            existing = connection.execute(
                text("SELECT run_id, owns_run FROM relationship_review_job WHERE job_id = :job"),
                {"job": job.id},
            ).one_or_none()
        if existing is not None:
            return existing.run_id, existing.owns_run
        if payload.run_id is not None:
            with self._engine.connect() as connection:
                open_run = connection.execute(
                    text("SELECT 1 FROM run WHERE id = :id AND finished_at IS NULL"),
                    {"id": payload.run_id},
                ).one_or_none()
            if open_run is None:
                raise RoleCallFailed(f"no unfinished run {payload.run_id} to review within")
            run_id, owned = payload.run_id, False
        else:
            if self._runs is None:
                raise RoleCallFailed(
                    "relationship review records a run: it needs LiteLLM and Hindsight configured"
                )
            run_id, owned = self._runs.start(RUN_KIND).id, True
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO relationship_review_job (job_id, run_id, owns_run)"
                    " VALUES (:job, :run, :owned)"
                ),
                {"job": job.id, "run": run_id, "owned": owned},
            )
        return run_id, owned

    def _finish_run(self, run_id: uuid.UUID) -> None:
        assert self._runs is not None
        with self._engine.connect() as connection:
            usage = run_usage(connection, run_id)
        try:
            self._runs.finish(run_id, tokens_in=usage.tokens_in, tokens_out=usage.tokens_out)
        except RunNotFound:
            pass  # finished by an earlier attempt

    # --- records ------------------------------------------------------------------------------

    def _record(self, job: Job, review: MachineReviewRecord, edge: Edge | None) -> None:
        with self._engine.begin() as connection:
            record_machine_review(
                connection,
                REVIEWER_ACTOR,
                replace(review, job_id=job.id),
                edge,
            )

    def _artifacts(self, job: Job, status: str, not_found: list[uuid.UUID]) -> Artifacts:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT assertion_id, relationship_id, outcome, reasons"
                    " FROM relationship_review WHERE job_id = :job ORDER BY created_at, id"
                ),
                {"job": job.id},
            ).all()
            run_id = connection.execute(
                text("SELECT run_id FROM relationship_review_job WHERE job_id = :job"),
                {"job": job.id},
            ).scalar_one_or_none()
        counts = {"machine_reviewed": 0, "needs_human_review": 0, "not_eligible": 0}
        for row in rows:
            counts[row.outcome] += 1
        relationship_ids: list[JsonValue] = list(
            dict.fromkeys(str(row.relationship_id) for row in rows if row.relationship_id)
        )
        not_eligible: list[JsonValue] = [
            {"assertion_id": str(row.assertion_id), "reason": row.reasons[0]}
            for row in rows
            if row.outcome == "not_eligible"
        ]
        return {
            "status": status,
            "run_id": None if run_id is None else str(run_id),
            "considered": len(rows),
            **counts,
            "relationship_ids": relationship_ids,
            "not_eligible_assertions": not_eligible,
            "not_found": [str(each) for each in not_found],
        }

    # --- reads --------------------------------------------------------------------------------

    def _candidates(
        self, payload: ReviewRelationshipsPayload
    ) -> tuple[list[_Candidate], list[uuid.UUID]]:
        select = (
            "SELECT a.id, a.subject_company_id, a.predicate, a.object_company_id, a.value_json,"
            " a.source_version_id, a.quote, a.span_start, a.span_end, a.verification_status,"
            " a.parser_version, p.parsed_object_uri, d.source_tier, d.title, d.publisher,"
            " d.form_type, d.company_id AS filer_company_id FROM assertion a"
            " JOIN source_version v ON v.id = a.source_version_id"
            " JOIN source_document d ON d.id = v.source_document_id"
            # The parse the Assertion was made on (pilot-fixes ticket 11), and only that one.
            " LEFT JOIN source_version_parse p ON p.source_version_id = a.source_version_id"
            "  AND p.parser_version = a.parser_version"
            " WHERE NOT EXISTS (SELECT FROM relationship_review r WHERE r.assertion_id = a.id)"
        )
        with self._engine.connect() as connection:
            if payload.assertion_ids is None:
                rows = connection.execute(
                    text(
                        f"{select} AND a.verification_status = ANY(:open)"
                        " AND a.predicate = ANY(:whitelist)"
                        " ORDER BY a.extracted_at, a.id LIMIT :max"
                    ),
                    {"open": list(_OPEN), "whitelist": list(PREDICATES), "max": MAX_ASSERTIONS},
                ).mappings()
                return [_Candidate(**dict(row)) for row in rows], []
            requested = list(dict.fromkeys(payload.assertion_ids))
            found = {
                row["id"]: _Candidate(**dict(row))
                for row in connection.execute(
                    text(f"{select} AND a.id = ANY(:ids)"), {"ids": requested}
                ).mappings()
            }
            known = set(
                connection.execute(
                    text("SELECT id FROM assertion WHERE id = ANY(:ids)"), {"ids": requested}
                ).scalars()
            )
        ordered = [found[each] for each in requested if each in found]
        return ordered, [each for each in requested if each not in known]

    def _companies(self) -> dict[uuid.UUID, list[str]]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id, display_name, legal_name FROM company")
            ).all()
        return {row.id: company_names(row.display_name, row.legal_name) for row in rows}

    def _parsed(self, candidate: _Candidate) -> str | None:
        """The archived parse the Assertion was made on, or None if it can't be read."""
        version = (candidate.source_version_id, candidate.parser_version)
        if version not in self._texts:
            text_: str | None = None
            if candidate.parsed_object_uri is not None:
                try:
                    text_ = self._archive.get(candidate.parsed_object_uri).decode("utf-8")
                except (ObjectNotFound, ArchiveIntegrityError, InvalidArchiveUri):
                    text_ = None
            self._texts[version] = text_
        return self._texts[version]


def _eligibility(candidate: _Candidate) -> tuple[str | None, Edge | None]:
    """(None, the edge) for an eligible Assertion, else (the reason, None)."""
    rule = PREDICATES.get(candidate.predicate)
    if rule is None:
        return "predicate_not_whitelisted", None
    if candidate.verification_status not in _OPEN:
        return f"assertion_{candidate.verification_status}", None
    value = _value(candidate.value_json)
    layer = value.get("layer")
    if not isinstance(layer, str) or layer not in LAYER_NAMES:
        return "unknown_layer", None
    object_text: str | None = None
    if rule.object_kind == "company":
        if candidate.object_company_id is None:
            return "missing_object", None
        if candidate.object_company_id == candidate.subject_company_id:
            return "self_relationship", None
    else:
        named = value.get("object_text")
        if not isinstance(named, str) or not named.strip():
            return "missing_object", None
        object_text = named.strip()
    if directional_language(rule.name, candidate.quote).verdict == "absent":
        return "no_directional_language", None
    if (
        object_text is not None
        and object_clause_cue(rule.name, candidate.quote, object_text) is None
    ):
        return "cue_in_other_clause", None
    return None, Edge(
        subject_company_id=candidate.subject_company_id,
        predicate=rule.name,
        object_company_id=candidate.object_company_id if rule.object_kind == "company" else None,
        object_text=object_text,
        layer=layer,
    )


def _record(
    candidate: _Candidate,
    checks: DeterministicChecks,
    outcome: MachineOutcome,
    reasons: list[str],
    reviewer_status: ReviewerStatus,
    answer: EdgeReview | None = None,
) -> MachineReviewRecord:
    return MachineReviewRecord(
        assertion_id=candidate.id,
        outcome=outcome,
        reasons=reasons,
        reviewer_status=reviewer_status,
        verbatim_span=checks.verbatim_span,
        tier_a=checks.tier_a,
        directional_language=checks.language.verdict,
        directional_cue=checks.language.cue,
        hedge=checks.language.hedge,
        reviewer_verdict=None if answer is None else answer.verdict,
        reviewer_direction=None if answer is None else answer.direction,
        reviewer_layer=None if answer is None else answer.layer,
        reviewer_suggested_layer=None if answer is None else answer.suggested_layer,
        reviewer_reasoning=None if answer is None else answer.reasoning,
    )


def _value(value_json: object) -> dict[str, Any]:
    """An Assertion's `value_json` as an object (empty if it is anything else)."""
    return cast(dict[str, Any], value_json) if isinstance(value_json, dict) else {}


def _item(item_id: str, pending: _Pending, companies: dict[uuid.UUID, list[str]]) -> EdgeToReview:
    candidate, edge = pending.candidate, pending.edge
    value = _value(candidate.value_json)
    product = value.get("product")
    return EdgeToReview(
        item_id=item_id,
        subject=EdgeParty(
            company_id=str(edge.subject_company_id),
            names=companies.get(edge.subject_company_id, []),
        ),
        predicate=edge.predicate,
        reads=PREDICATES[edge.predicate].reads,
        object_company=None
        if edge.object_company_id is None
        else EdgeParty(
            company_id=str(edge.object_company_id),
            names=companies.get(edge.object_company_id, []),
        ),
        object_text=edge.object_text,
        product=product if isinstance(product, str) else None,
        layer=edge.layer,
        source=EdgeSource(
            source_version_id=str(candidate.source_version_id),
            title=candidate.title,
            publisher=candidate.publisher,
            form_type=candidate.form_type,
            source_tier=candidate.source_tier,
            filer_company_id=None
            if candidate.filer_company_id is None
            else str(candidate.filer_company_id),
        ),
    )


def _span(candidate: _Candidate) -> str:
    return f"{candidate.source_version_id}#{candidate.span_start}-{candidate.span_end}"
