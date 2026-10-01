"""`/api/v1/investigations`: start an investigation from a theme question and follow it.

- `POST /investigations` (202): records the investigation, its premises and its fixed plan
  (Scout -> one Investigator per seed company -> Skeptic || Financial Analyst -> Editor; the
  Skeptic proposes counterevidence, the Financial Analyst scenario inputs) and enqueues the
  Scout's task. Budgets default to ≤ 2 rounds, `ATLAS_INVESTIGATION_MAX_LEADS` (≤ 10) leads,
  `ATLAS_INVESTIGATION_MAX_DOCUMENTS` (≤ 25) documents and `ATLAS_RUN_TOKEN_BUDGET` tokens;
  a request may lower them. Seed companies default to the theme's companies in the database.
  503 when LiteLLM, Hindsight or SearXNG isn't configured.
- `GET /investigations/{id}`: the §7.2 request, budgets and usage, status (`paused` while the
  queue pause holds its task back), the stop reason and detail, premises, tasks, leads,
  reading pointers (`pointers`: what Memory returned to the question and each Scout query,
  resolved to Source Version sections; Memory as an index, never Evidence), documents, the
  Skeptic's counterevidence (each item a contradiction of a named Claim or
  bear context about a company) and the Editor's draft research card.
- `GET /investigations` (newest first): each investigation's theme, question, round and
  status, for the research workbench.
- `GET /investigations/{id}/events`: what happened, in order.
- `POST /investigations/{id}/resume`: continue an investigation stopped `budget_exhausted`
  with a larger token budget, in the same run (409 otherwise).
- `POST /investigations/{id}/premises/{key}/disprove`: the researcher marks a premise
  disproven; only the unstarted tasks that depend on it are cancelled (audited).
- `POST /investigations/{id}/follow-up` (`{"question"}`): one bounded follow-up round on one
  of the research card's open questions: the fixed plan again, as round 2, in the same run
  and within what is left of its budgets (≤ `max_rounds` rounds; audited). 409 while it
  runs, after a budget or premise stop, when the rounds or tokens are spent or once it is
  saved as a Hypothesis; 422 for a question that isn't one of the card's open questions.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
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
from atlas.companies import UniverseConfigError, load_universe
from atlas.investigations import (
    INVESTIGATION_TASK_KIND,
    Budgets,
    Investigation,
    InvestigationError,
    InvestigationEvent,
    Investigations,
    InvestigationSummary,
    get_investigation,
    list_events,
    list_investigations,
)
from atlas.jobs import JobQueue
from atlas.settings import Settings

Paged = Annotated[Pagination, Depends(pagination)]
NOT_CONFIGURED = error_responses(503)


class BudgetRequest(BaseModel):
    """Per-run budgets (spec §7.4); unset ones take the configured defaults."""

    model_config = ConfigDict(extra="forbid")

    max_rounds: int = Field(default=2, ge=1, le=2)
    max_leads: int | None = Field(default=None, ge=1, le=10)
    max_documents: int | None = Field(default=None, ge=1, le=25)
    token_budget: int | None = Field(default=None, gt=0)


class InvestigationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: str = Field(min_length=1, description="a theme in the universe config")
    question: str = Field(
        min_length=1, max_length=4000, pattern=r"\S", description="the research question"
    )
    seed_company_ids: list[uuid.UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=25,
        description="the companies to investigate; default: the theme's companies",
    )
    as_of: AwareDatetime | None = Field(
        default=None, description="only Source Versions available by then are read; default now"
    )
    budgets: BudgetRequest = Field(default_factory=BudgetRequest)


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token_budget: int = Field(gt=0, description="the new token budget; larger than the old one")


class FollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        min_length=1,
        max_length=4000,
        pattern=r"\S",
        description="one of the research card's open questions",
    )


class DisproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


def investigations_router(
    engine: Engine, queue: JobQueue, actor: Actor, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/investigations", tags=["investigations"])
    investigations = Investigations(engine, queue)

    def read(investigation_id: uuid.UUID) -> Investigation | None:
        pause = queue.pause_state()
        held = pause.paused and INVESTIGATION_TASK_KIND in pause.kinds
        with engine.connect() as connection:
            return get_investigation(connection, investigation_id, queue_paused=held)

    def found(investigation_id: uuid.UUID) -> Investigation | JSONResponse:
        investigation = read(investigation_id)
        return investigation if investigation is not None else not_found("investigation")

    @router.post(
        "",
        status_code=202,
        response_model=Investigation,
        responses={**INVALID, **NOT_CONFIGURED},
    )
    def create(request: InvestigationCreate) -> Investigation | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        missing = [
            name
            for name, value in (
                ("ATLAS_LITELLM_URL", settings.litellm_url),
                ("ATLAS_LITELLM_API_KEY", settings.litellm_api_key),
                ("ATLAS_HINDSIGHT_URL", settings.hindsight_url),
                ("ATLAS_SEARXNG_URL", settings.searxng_url),
            )
            if not value
        ]
        if missing:
            return error_response(
                503,
                "investigations_not_configured",
                f"an investigation needs {', '.join(missing)}",
            )
        now = datetime.now(UTC)
        if request.as_of is not None and request.as_of > now:
            return error_response(422, "invalid_as_of", "as_of can't be in the future")
        try:
            universe = load_universe(settings.themes_config)
        except UniverseConfigError as error:
            return error_response(503, "universe_config_invalid", str(error))
        budgets = Budgets(
            max_rounds=request.budgets.max_rounds,
            max_leads=request.budgets.max_leads or settings.investigation_max_leads,
            max_documents=request.budgets.max_documents or settings.investigation_max_documents,
            token_budget=request.budgets.token_budget or settings.run_token_budget,
        )
        try:
            investigation_id = investigations.create(
                actor,
                universe,
                theme=request.theme,
                question=request.question.strip(),
                seed_company_ids=request.seed_company_ids,
                as_of=request.as_of or now,
                budgets=budgets,
                bank_id=settings.hindsight_bank_id,
            )
        except InvestigationError as error:
            return error_response(error.status, error.code, error.message)
        created = read(investigation_id)
        assert created is not None
        return created

    @router.get("", response_model=Page[InvestigationSummary])
    def investigations_list(page: Paged) -> Page[InvestigationSummary]:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            items, total = list_investigations(connection, limit=page.limit, offset=page.offset)
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{investigation_id}", response_model=Investigation, responses=NOT_FOUND)
    def investigation(investigation_id: uuid.UUID) -> Investigation | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return found(investigation_id)

    @router.get(
        "/{investigation_id}/events",
        response_model=Page[InvestigationEvent],
        responses=NOT_FOUND,
    )
    def events(  # pyright: ignore[reportUnusedFunction]
        investigation_id: uuid.UUID, page: Paged
    ) -> Page[InvestigationEvent] | JSONResponse:
        with engine.connect() as connection:
            listed = list_events(connection, investigation_id, limit=page.limit, offset=page.offset)
        if listed is None:
            return not_found("investigation")
        items, total = listed
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.post(
        "/{investigation_id}/resume",
        response_model=Investigation,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def resume(  # pyright: ignore[reportUnusedFunction]
        investigation_id: uuid.UUID, request: ResumeRequest
    ) -> Investigation | JSONResponse:
        try:
            investigations.resume(actor, investigation_id, request.token_budget)
        except InvestigationError as error:
            return error_response(error.status, error.code, error.message)
        return found(investigation_id)

    @router.post(
        "/{investigation_id}/premises/{premise_key}/disprove",
        response_model=Investigation,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def disprove(  # pyright: ignore[reportUnusedFunction]
        investigation_id: uuid.UUID, premise_key: str, request: DisproveRequest
    ) -> Investigation | JSONResponse:
        try:
            investigations.disprove(actor, investigation_id, premise_key, request.reason.strip())
        except InvestigationError as error:
            return error_response(error.status, error.code, error.message)
        return found(investigation_id)

    @router.post(
        "/{investigation_id}/follow-up",
        response_model=Investigation,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def follow_up(  # pyright: ignore[reportUnusedFunction]
        investigation_id: uuid.UUID, request: FollowUpRequest
    ) -> Investigation | JSONResponse:
        try:
            investigations.follow_up(actor, investigation_id, request.question.strip())
        except InvestigationError as error:
            return error_response(error.status, error.code, error.message)
        return found(investigation_id)

    return router
