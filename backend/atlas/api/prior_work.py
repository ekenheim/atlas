"""`GET /api/v1/research/prior-work`: what Atlas already holds for a question, as of a time
(atlas-beliefs ticket 26; `atlas.prior_work`).

`?theme=&as_of=&company_ids=&steps=&question=&exclude_session_id=&limit=`: the existing Facts for
the companies and steps (newest document first, with the count beyond the cap), the Beliefs of any
judgement that name them (stalest first, with who judged them and when they were last examined;
the judgement is the current one, and the open flags and notices leave out those raised by a
document public after `as_of`),
the documents earlier sessions read (with those sessions' as-of times), the earlier sessions and
the open Issues that touch them. Nothing public after `as_of` is shown. With no `company_ids` the
theme's researched companies are asked about. 422 `unknown_theme` (checked whether or not
companies are named) / `unknown_company`.
"""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
from sqlalchemy import Engine, text

from atlas.api.common import INVALID, error_response
from atlas.companies import Universe, company_id_for, extend_universe
from atlas.facts import FactStep
from atlas.prior_work import DEFAULT_LIMIT, MAX_LIMIT, PriorWork, prior_work


def prior_work_router(engine: Engine, universe: Callable[[], Universe]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/research", tags=["research"])

    @router.get("/prior-work", response_model=PriorWork, responses=INVALID)
    def get_prior_work(  # pyright: ignore[reportUnusedFunction]
        theme: str,
        as_of: AwareDatetime,
        company_ids: Annotated[list[uuid.UUID] | None, Query()] = None,
        steps: Annotated[list[FactStep] | None, Query()] = None,
        question: str | None = None,
        exclude_session_id: uuid.UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    ) -> PriorWork | JSONResponse:
        asked = list(dict.fromkeys(company_ids or []))
        with engine.connect() as connection:
            config = extend_universe(connection, universe())  # committed Candidates too
        if theme not in config.themes:
            return error_response(422, "unknown_theme", f"no such theme: {theme}")
        if asked:
            with engine.connect() as connection:
                known = connection.execute(
                    text("SELECT count(*) FROM company WHERE id = ANY(:ids)"), {"ids": asked}
                ).scalar_one()
            if known != len(asked):
                return error_response(422, "unknown_company", "a company is not in the universe")
        else:
            asked = [
                company_id_for(slug, config.companies[slug])
                for slug in config.themes[theme].companies
            ]
        with engine.connect() as connection:
            return prior_work(
                connection,
                theme=theme,
                company_ids=asked,
                explicit_companies=bool(company_ids),
                steps=list(dict.fromkeys(steps or [])),
                question=question,
                as_of=as_of,
                exclude_session_id=exclude_session_id,
                limit=limit,
            )

    return router
