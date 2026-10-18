"""`/api/v1/beliefs`: Beliefs (beliefs ticket 02).

- `POST /beliefs` (201): propose; refused 422 `no_load_bearing_citation` without a load-bearing
  citation of positive valence; born `unproven`. Proposed from a research session (every
  proposal under `ATLAS_FACT_STATEMENT_JUDGE=always`) it is also held to one claim, one period
  and one actor (`atlas.beliefs.atomicity`: 422 `belief_compound`, the `detail` holds the
  reasons) and its statement judged against its load-bearing positive Facts' quotes (422
  `belief_beyond_quotes`, the `detail` holds the judge's `beyond`, `kinds` and `reason`; 503
  `judge_unavailable` when no verdict could be given: call again later) (ticket 23)
- `POST /beliefs/{id}/cite`, `/judge` (an author's judgement; clears open flags and notices),
  `/supersede`. An **isolated** session (ticket 29a) cannot examine a Belief (422
  `isolated_session`), and cites (`?session_id=`) or supersedes (`session_id` in the body) only
  Beliefs it proposed (422 `belief_not_in_session`); a Belief of an isolated session cites only
  Facts that session recorded (422 `fact_not_in_session`). A Belief proposed by an isolated
  session (ticket 29a, the early-call scorecard) is never judged: `/judge` is 409
  `isolated_session_belief`, so it makes no call and never reaches the conclusions bank
- `POST /beliefs/{id}/examine` (`{session_id, outcome, note?, actor?}`; ticket 26): a session tested
  the Belief against what was public by its as-of time (`confirmed`, `qualified`, `contradicted`,
  `nothing_new`); insert-only history and the Belief's `last_examined_*`; no judgement. 422
  `unknown_session` / `session_not_claude` / `belief_after_as_of`
- `GET /beliefs?theme=&step=&company_id=&judgement=&status=&flagged=&as_of=&sort=created|stalest`,
  `GET /beliefs/{id}[?as_of=]` (citations with their quotes, spans and dates)

Errors use the envelope: 404 `not_found`, 409 `belief_not_active` / `already_cited` /
`isolated_session_belief`, 422.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text

from atlas.api.common import (
    CONFLICT,
    INVALID,
    NOT_FOUND,
    Page,
    Pagination,
    error_response,
    not_found,
    pagination,
)
from atlas.audit import Actor
from atlas.beliefs.atomicity import compound_reasons
from atlas.beliefs.service import (
    Belief,
    BeliefExamine,
    BeliefJudge,
    BeliefNotActive,
    BeliefNotFound,
    BeliefPropose,
    BeliefRefused,
    Beliefs,
    BeliefSummary,
    BeliefSupersede,
    CitationIn,
    Sort,
    get_belief,
    list_beliefs,
)
from atlas.investigations.argument import fact_rows
from atlas.judging import Judges, JudgeUnavailable

MAX_JUDGED_FACTS = 12  # the load-bearing Facts a proposal's statement is judged against

Paged = Annotated[Pagination, Depends(pagination)]


def _refused(refusal: BeliefRefused) -> JSONResponse:
    status = 409 if refusal.code in ("already_cited", "isolated_session_belief") else 422
    return error_response(status, refusal.code, refusal.message)


def judged_proposal(engine: Engine, judges: Judges, request: BeliefPropose) -> JSONResponse | None:
    """The refusal of a proposal that is compound or whose statement says more than its
    load-bearing positive Facts' quotes, else None (ticket 23). A proposal the Belief rules
    refuse anyway (no load-bearing citation, an unknown Fact) is left to them."""
    loaded = [
        each for each in request.citations if each.weight == "load_bearing" and each.signed() > 0
    ]
    if not loaded:
        return None
    reasons = compound_reasons(request.statement)
    if reasons:
        return error_response(
            422,
            "belief_compound",
            "a Belief is one proposition (one claim, one period, one actor): "
            + "; ".join(reasons)
            + ". Split it into Beliefs, each with its own citations.",
            {"reasons": reasons},
        )
    fact_ids = list(dict.fromkeys(each.ref_id for each in loaded if each.kind == "fact"))
    if not fact_ids:
        return None  # Assertions only: there are no Facts' quotes to judge against
    judged_ids = fact_ids[:MAX_JUDGED_FACTS]
    with engine.connect() as connection:
        rows = fact_rows(connection, judged_ids)
        question = (
            connection.execute(
                text("SELECT question FROM research_session WHERE id = :id"),
                {"id": request.session_id},
            ).scalar()
            if request.session_id is not None
            else None
        )
    if len(rows) != len(judged_ids):
        return None  # an unknown Fact: `unknown_citation` is the service's to say
    try:
        verdict = judges.judge(
            "belief_judge", question=question or "", statement=request.statement, rows=rows
        )
    except JudgeUnavailable as unavailable:
        return error_response(
            503,
            "judge_unavailable",
            f"the statement could not be judged ({unavailable.reason}); call again later",
        )
    if verdict.supported:
        return None
    beyond = "; ".join(f'"{each}"' for each in verdict.beyond) or verdict.reason
    return error_response(
        422,
        "belief_beyond_quotes",
        f"the statement says more than its load-bearing quotes: {beyond} ({verdict.reason})."
        " Rewrite it to what they say, or cite the Fact that carries the rest.",
        verdict.detail(),
    )


def beliefs_router(
    engine: Engine, actor: Actor, judges: Judges | None = None, themes_config: Path | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/beliefs", tags=["beliefs"])
    service = Beliefs(engine, actor, themes_config)

    @router.get("", response_model=Page[BeliefSummary], responses=INVALID)
    def beliefs(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        theme: str | None = None,
        step: str | None = None,
        company_id: uuid.UUID | None = None,
        judgement: str | None = None,
        status: str | None = None,
        flagged: bool | None = None,
        as_of: datetime | None = None,
        sort: Sort = "created",
    ) -> Page[BeliefSummary]:
        with engine.connect() as connection:
            items, total = list_beliefs(
                connection,
                theme=theme,
                step=step,
                company_id=company_id,
                judgement=judgement,
                status=status,
                flagged=flagged,
                as_of=as_of,
                sort=sort,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{belief_id}", response_model=Belief, responses={**NOT_FOUND, **INVALID})
    def belief(belief_id: uuid.UUID, as_of: datetime | None = None) -> Belief | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_belief(connection, belief_id, as_of=as_of)
        return found if found is not None else not_found("belief")

    @router.post("", status_code=201, response_model=Belief, responses=INVALID)
    def propose(request: BeliefPropose) -> Belief | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if judges is not None and judges.judges_belief(request.session_id):
            refused = judged_proposal(engine, judges, request)
            if refused is not None:
                return refused
        try:
            return service.propose(request)
        except BeliefRefused as refusal:
            return _refused(refusal)

    @router.post(
        "/{belief_id}/cite", response_model=Belief, responses={**NOT_FOUND, **CONFLICT, **INVALID}
    )
    def cite(  # pyright: ignore[reportUnusedFunction]
        belief_id: uuid.UUID, request: CitationIn, session_id: uuid.UUID | None = None
    ) -> Belief | JSONResponse:
        return _run(lambda: service.cite(belief_id, request, session_id))

    @router.post(
        "/{belief_id}/judge", response_model=Belief, responses={**NOT_FOUND, **CONFLICT, **INVALID}
    )
    def judge(belief_id: uuid.UUID, request: BeliefJudge) -> Belief | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _run(lambda: service.judge(belief_id, request))

    @router.post(
        "/{belief_id}/examine",
        response_model=Belief,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def examine(belief_id: uuid.UUID, request: BeliefExamine) -> Belief | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _run(lambda: service.examine(belief_id, request))

    @router.post(
        "/{belief_id}/supersede",
        response_model=Belief,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def supersede(belief_id: uuid.UUID, request: BeliefSupersede) -> Belief | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _run(lambda: service.supersede(belief_id, request))

    return router


def _run(action: Callable[[], Belief]) -> Belief | JSONResponse:
    try:
        return action()
    except BeliefNotFound:
        return not_found("belief")
    except BeliefNotActive:
        return error_response(409, "belief_not_active", "the Belief is superseded or withdrawn")
    except BeliefRefused as refusal:
        return _refused(refusal)
