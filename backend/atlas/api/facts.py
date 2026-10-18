"""`/api/v1/facts`: record and read Facts (bottleneck-argument ticket 02).

- `POST /facts` (201): record a Fact; its quote must occur exactly at its offsets (422
  `quote_mismatch`) and a quantity's number must occur in the quote (422
  `quantity_not_in_quote`); an unknown step or status is 422 `invalid_request`; a period its
  quote's relative phrases and the document's date contradict is 422 `period_misresolved`, one
  that dates another document `period_other_document`; the resolved period and its basis
  (the version's date, the company's fiscal year end) are computed and stored (R2-02)
- a Fact recorded with a `session_id` for a span that overlaps a standing Fact of the same Source
  Version, company and step (ticket 26; `atlas.facts.reuse`) is not recorded again when that Fact
  has the same status, the same statement (equal after case, whitespace and punctuation are
  normalised; ticket 28: a statement that differs by a word is another) and a span that contains
  the new one's (a quote of more words is its own Fact): the existing Fact comes back with 200 and
  `reused: true`, no row is made, the session records the reuse (`facts_reused`) and the judge is
  not asked. Any other statement is recorded (201), judged like any session Fact and names the
  earlier Fact (`same_span_as`): a correction is always recordable beside the Fact it corrects.
  Every other check runs first, so a reuse never hides a refusal. In an **isolated** session
  (ticket 29a, the early-call scorecard) there is no reuse and no `same_span_as`: a span a standing
  Fact already holds is recorded as a new Fact, judged as usual, so the session cannot be handed
  the work of a session that chose with hindsight and leaves its own to none
- a Fact recorded with a `session_id` (every Fact, under `ATLAS_FACT_STATEMENT_JUDGE=always`)
  has its statement judged against its own quote, source title and date after those checks
  (ticket 23; `atlas.judging`): misstated is 422 `statement_beyond_quote` (the error's `detail`
  holds the judge's `beyond`, `kinds` and `reason`), supported is recorded with the verdict
  (`statement_judgement`), and a judge that cannot be reached records the Fact `unjudged`
- `GET /facts?company_id=&step=&investigation_id=&session_id=` (oldest first), `GET /facts/{id}`
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, Engine, text

from atlas.api.common import (
    INVALID,
    NOT_FOUND,
    Page,
    Pagination,
    error_response,
    not_found,
    pagination,
)
from atlas.archive import Archive
from atlas.assertions import AssertionNotFound, AssertionRefused
from atlas.audit import Actor
from atlas.facts import (
    Fact,
    FactCreate,
    FactJudgement,
    FactRecorded,
    Facts,
    FactStep,
    get_fact,
    list_facts,
)
from atlas.facts.periods import FiscalYearEnd
from atlas.financials.calendar import fiscal_year_end
from atlas.judging import Judges, fact_question, fact_refusal, judge_fact
from atlas.sessions import session_is_isolated
from atlas.settings import Settings

Paged = Annotated[Pagination, Depends(pagination)]


def document_calendar(
    connection: Connection, request: FactCreate
) -> tuple[date | None, FiscalYearEnd | None]:
    """The date the version became available (None for an unknown version, which the service
    refuses) and the fiscal year end of the company that wrote the document, else of the
    Fact's subject: the calendar its relative periods ("this quarter") are the speaker's."""
    row = connection.execute(
        text(
            "SELECT a.available_at, d.company_id FROM source_version v"
            " JOIN source_document d ON d.id = v.source_document_id"
            " JOIN source_version_availability a ON a.source_version_id = v.id"
            " WHERE v.id = :id"
        ),
        {"id": request.source_version_id},
    ).one_or_none()
    if row is None:
        return None, None
    company_id = row.company_id or request.subject_company_id
    return row.available_at.date(), fiscal_year_end(connection, company_id)


def facts_router(engine: Engine, archive: Archive, actor: Actor, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/facts", tags=["facts"])
    service = Facts(engine, archive, actor)
    judges = Judges(engine, settings)

    @router.get("", response_model=Page[Fact], responses=INVALID)
    def facts(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        company_id: uuid.UUID | None = None,
        step: FactStep | None = None,
        investigation_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> Page[Fact]:
        with engine.connect() as connection:
            items, total = list_facts(
                connection,
                company_id=company_id,
                step=step,
                investigation_id=investigation_id,
                session_id=session_id,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{fact_id}", response_model=Fact, responses={**NOT_FOUND, **INVALID})
    def fact(fact_id: uuid.UUID) -> Fact | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_fact(connection, fact_id)
        return found if found is not None else not_found("fact")

    @router.post(
        "",
        status_code=201,
        response_model=FactRecorded,
        responses={200: {"model": FactRecorded, "description": "reused"}, **INVALID},
    )
    def create(request: FactCreate, response: Response) -> FactRecorded | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            document_date, year_end = document_calendar(connection, request)
        judgement: FactJudgement | None = None
        same_span_as: uuid.UUID | None = None
        try:
            judged = judges.judges_fact(request.session_id)
            value = None
            if judged or request.session_id is not None:
                # Every other check first (nothing is recorded: a rolled-back transaction), so
                # neither the reuse nor the judge is asked about a Fact that would be refused.
                value = service.check(
                    request, document_date=document_date, fiscal_year_end=year_end
                )
            with engine.connect() as connection:
                isolated = session_is_isolated(connection, request.session_id)
            if request.session_id is not None and not isolated:
                decision = service.decide_reuse(request)
                if decision.kind == "reuse" and decision.fact_id is not None:
                    response.status_code = 200
                    return service.record_reuse(request, decision.fact_id)
                same_span_as = decision.fact_id if decision.kind == "same_span" else None
            if judged and value is not None:
                with engine.connect() as connection:
                    question = fact_question(connection, request)
                    judgement, misstated = judge_fact(
                        connection, request, value, judges.fact_judge(question)
                    )
                if misstated is not None:
                    code, message = fact_refusal(misstated)
                    return error_response(422, code, message, misstated.detail())
            return service.create(
                request,
                document_date=document_date,
                fiscal_year_end=year_end,
                judgement=judgement,
                same_span_as=same_span_as,
            )
        except AssertionNotFound:
            return not_found("fact")
        except AssertionRefused as refusal:
            return error_response(422, refusal.code, refusal.message)

    return router
