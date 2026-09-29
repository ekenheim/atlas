"""`/api/v1/hypotheses`: save an investigation's result as a Hypothesis and work with it.

- `POST /hypotheses` (202, `{"investigation_id"}`): a `draft` Hypothesis for a stopped
  investigation with a research card (one per investigation), and the `draft_hypothesis` job
  in which the Editor drafts version 1. 503 when LiteLLM or Hindsight isn't configured.
- `GET /hypotheses[?theme_id=&status=]`, `GET /hypotheses/{id}`: status and allowed
  transitions, the drafting's state, every version (content, content hash, provenance,
  publication) and the transitions.
- `POST /hypotheses/{id}/transitions` (`{"to", "note"?}`): a §5.6 lifecycle change (409
  `invalid_transition` otherwise; `reviewed` only by publishing).
- `POST /hypotheses/{id}/versions`: a correction: a new version from the latest one with the
  changed fields and a note. Findings must cite accepted Claims of the investigation (422
  `unsupported_finding`).
- `POST /hypotheses/{id}/publish-version` (`{"version", "note"?}`): publish the latest version
  behind the publish gate (422 `publish_gate_failed` with every failed check); a published
  version is immutable.
- `GET /hypotheses/{id}/diff?from_version=&to_version=`: claims new, contradicted, unchanged
  or removed between two versions (default: the latest and the one before it).
- `GET /hypotheses/{id}/export?format=json|markdown&version=`: the dossier of a version
  (default the latest) with citations and run metadata.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from atlas.api.common import (
    CONFLICT,
    INVALID,
    NOT_FOUND,
    Page,
    Pagination,
    error_response,
    error_responses,
    not_found,
    pagination,
)
from atlas.audit import Actor
from atlas.hypotheses import (
    Correction,
    Hypotheses,
    Hypothesis,
    HypothesisDiff,
    HypothesisError,
    HypothesisExport,
    HypothesisStatus,
    Mechanism,
    build_export,
    diff_versions,
    get_hypothesis,
    get_version,
    list_hypotheses,
    render_markdown,
)
from atlas.hypotheses.findings import ProposedFinding
from atlas.jobs import JobQueue
from atlas.settings import Settings

Paged = Annotated[Pagination, Depends(pagination)]
NOT_CONFIGURED = error_responses(503)
_Text = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


class HypothesisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investigation_id: uuid.UUID = Field(description="a stopped investigation with a research card")


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: HypothesisStatus
    note: str | None = Field(default=None, max_length=2000)


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, description="the latest version, which must be unpublished")
    note: str | None = Field(default=None, max_length=2000)


class FindingEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_text: _Text
    claim_ids: list[uuid.UUID] = Field(
        min_length=1, description="accepted Claims of the investigation"
    )
    limitations: list[_Text] = Field(default_factory=list[str])
    open_questions: list[_Text] = Field(default_factory=list[str])


class VersionCreate(BaseModel):
    """A correction: the fields given replace the latest version's; the rest are kept."""

    model_config = ConfigDict(extra="forbid")

    based_on_version: int = Field(ge=1, description="the latest version")
    note: _Text = Field(description="why this version corrects the last")
    thesis_statement: _Text | None = None
    mechanism: Mechanism | None = None
    measurable_predictions: list[_Text] | None = None
    catalysts: list[_Text] | None = None
    falsifiers: list[_Text] | None = None
    required_evidence: list[_Text] | None = None
    alternative_explanations: list[_Text] | None = None
    unresolved_questions: list[_Text] | None = None
    findings: list[FindingEdit] | None = None


def hypotheses_router(
    engine: Engine, queue: JobQueue, actor: Actor, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/hypotheses", tags=["hypotheses"])
    hypotheses = Hypotheses(engine, queue)

    def found(hypothesis_id: uuid.UUID) -> Hypothesis | JSONResponse:
        with engine.connect() as connection:
            hypothesis = get_hypothesis(connection, hypothesis_id)
        return hypothesis if hypothesis is not None else not_found("hypothesis")

    def failed(error: HypothesisError) -> JSONResponse:
        return error_response(error.status, error.code, error.message)

    @router.post(
        "",
        status_code=202,
        response_model=Hypothesis,
        responses={**NOT_FOUND, **CONFLICT, **INVALID, **NOT_CONFIGURED},
    )
    def create(request: HypothesisCreate) -> Hypothesis | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        missing = [
            name
            for name, value in (
                ("ATLAS_LITELLM_URL", settings.litellm_url),
                ("ATLAS_LITELLM_API_KEY", settings.litellm_api_key),
                ("ATLAS_HINDSIGHT_URL", settings.hindsight_url),
            )
            if not value
        ]
        if missing:
            return error_response(
                503, "hypotheses_not_configured", f"the Editor's draft needs {', '.join(missing)}"
            )
        try:
            hypothesis_id = hypotheses.create(actor, request.investigation_id)
        except HypothesisError as error:
            return failed(error)
        return found(hypothesis_id)

    @router.get("", response_model=Page[Hypothesis])
    def listing(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        theme_id: str | None = None,
        status: HypothesisStatus | None = None,
    ) -> Page[Hypothesis]:
        with engine.connect() as connection:
            items, total = list_hypotheses(
                connection,
                theme_id=theme_id,
                status=status,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{hypothesis_id}", response_model=Hypothesis, responses=NOT_FOUND)
    def hypothesis(hypothesis_id: uuid.UUID) -> Hypothesis | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return found(hypothesis_id)

    @router.post(
        "/{hypothesis_id}/transitions",
        response_model=Hypothesis,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def transition(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID, request: TransitionRequest
    ) -> Hypothesis | JSONResponse:
        try:
            hypotheses.transition(actor, hypothesis_id, request.to, _note(request.note))
        except HypothesisError as error:
            return failed(error)
        return found(hypothesis_id)

    @router.post(
        "/{hypothesis_id}/versions",
        status_code=201,
        response_model=Hypothesis,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def correct(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID, request: VersionCreate
    ) -> Hypothesis | JSONResponse:
        correction = Correction(
            based_on_version=request.based_on_version,
            note=request.note.strip(),
            thesis_statement=request.thesis_statement,
            mechanism=request.mechanism,
            measurable_predictions=request.measurable_predictions,
            catalysts=request.catalysts,
            falsifiers=request.falsifiers,
            required_evidence=request.required_evidence,
            alternative_explanations=request.alternative_explanations,
            unresolved_questions=request.unresolved_questions,
            findings=None
            if request.findings is None
            else [
                ProposedFinding(
                    statement=each.claim_text,
                    claim_ids=[str(claim_id) for claim_id in each.claim_ids],
                    limitations=each.limitations,
                    open_questions=each.open_questions,
                )
                for each in request.findings
            ],
        )
        try:
            hypotheses.correct(actor, hypothesis_id, correction)
        except HypothesisError as error:
            return failed(error)
        return found(hypothesis_id)

    @router.post(
        "/{hypothesis_id}/publish-version",
        response_model=Hypothesis,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def publish(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID, request: PublishRequest
    ) -> Hypothesis | JSONResponse:
        try:
            hypotheses.publish(actor, hypothesis_id, request.version, _note(request.note))
        except HypothesisError as error:
            return failed(error)
        return found(hypothesis_id)

    @router.get(
        "/{hypothesis_id}/diff",
        response_model=HypothesisDiff,
        responses={**NOT_FOUND, **INVALID},
    )
    def diff(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID,
        from_version: int | None = Query(default=None, ge=1),
        to_version: int | None = Query(default=None, ge=1),
    ) -> HypothesisDiff | JSONResponse:
        with engine.connect() as connection:
            hypothesis = get_hypothesis(connection, hypothesis_id)
            if hypothesis is None:
                return not_found("hypothesis")
            later_number = to_version or hypothesis.latest_version
            if later_number is None:
                return error_response(422, "invalid_diff", "the Hypothesis has no version yet")
            earlier_number = from_version or later_number - 1
            if earlier_number >= later_number:
                return error_response(
                    422, "invalid_diff", "from_version must be earlier than to_version"
                )
            earlier = get_version(connection, hypothesis_id, earlier_number)
            later = get_version(connection, hypothesis_id, later_number)
            if earlier is None or later is None:
                return not_found("version")
            return diff_versions(connection, hypothesis_id, earlier, later)

    @router.get(
        "/{hypothesis_id}/export",
        response_model=HypothesisExport,
        responses={
            **NOT_FOUND,
            200: {"content": {"text/markdown": {"schema": {"type": "string"}}}},
        },
    )
    def export(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID,
        format: Literal["json", "markdown"] = "json",
        version: int | None = Query(default=None, ge=1),
    ) -> HypothesisExport | PlainTextResponse | JSONResponse:
        with engine.connect() as connection:
            hypothesis = get_hypothesis(connection, hypothesis_id)
            if hypothesis is None:
                return not_found("hypothesis")
            number = version or hypothesis.latest_version
            chosen = None if number is None else get_version(connection, hypothesis_id, number)
            if chosen is None:
                return not_found("version")
            dossier = build_export(connection, hypothesis, chosen, datetime.now(UTC))
        if format == "markdown":
            return PlainTextResponse(render_markdown(dossier), media_type="text/markdown")
        return dossier

    return router


def _note(note: str | None) -> str | None:
    return note.strip() or None if note is not None else None
