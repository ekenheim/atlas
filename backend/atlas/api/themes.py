"""`/api/v1/themes`: the Theme explorer (product spec §10.1 A; ticket 23).

- `GET /themes`: each theme with its coverage (company count, companies without sources,
  empty layers, Relationship and open Candidate counts)
- `GET /themes/{id}/map[?include=]`: the theme's companies by supply-chain layer (upstream to
  downstream, empty layers included), the Relationships between them, its Candidates, and
  the Bottlenecks mental model's open gaps. `include` (comma-separated, ticket 32) names the
  sections to compute and return (`INCLUDE_NAMES`); none: all of them; an unknown name is
  422 `invalid_include`. `Server-Timing` says what each computed section took.
- `GET /themes/{id}/changes?limit=`: what changed, newest first (Beliefs judged, flags and
  notices raised on them, Facts recorded; atlas-beliefs ticket 21)

The Bottlenecks model is Hindsight output, never Evidence: it comes with its citations
resolved like a reflect answer's, and with a `status` saying why it is absent
(`not_configured`, `not_in_bank`, `unavailable`) or not yet generated (`not_refreshed`). A
Hindsight failure never fails the map. Errors use the envelope: 404 `not_found`.
"""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from atlas.api.common import INVALID, NOT_FOUND, error_response, not_found
from atlas.archive import Archive
from atlas.bank_template import BankTemplate, InvalidTemplate
from atlas.companies import Universe, extend_universe
from atlas.discovery.service import GAPS_MENTAL_MODEL
from atlas.hindsight import HindsightError, HindsightGateway
from atlas.jobs.pacing import Clock, utc_now
from atlas.mental_models import MentalModelReader, MentalModelView
from atlas.theme_changes import ThemeChange, theme_changes
from atlas.themes import (
    MAP_SECTION_ALIASES,
    MAP_SECTIONS,
    ThemeMap,
    ThemeSummary,
    list_themes,
    theme_sections,
)

type BottlenecksStatus = Literal[
    "refreshed", "not_refreshed", "not_in_bank", "not_configured", "unavailable"
]


class Bottlenecks(BaseModel):
    status: BottlenecksStatus = Field(
        description="refreshed: `model.content` is the open gaps; otherwise why there are none"
    )
    message: str | None = Field(description="what went wrong, when `unavailable`")
    model: MentalModelView | None = Field(
        description="the Bottlenecks mental model, with its resolved citations"
    )


class ThemeMapView(ThemeMap):
    bottlenecks: Bottlenecks


# What `include` takes: the map's keys, and `companies` for the two that list the companies.
INCLUDE_NAMES = (*MAP_SECTIONS, "bottlenecks", *MAP_SECTION_ALIASES)


def parse_include(include: str) -> frozenset[str] | list[str]:
    """The sections `include` names (an alias expanded), or the names it gets wrong."""
    names = [name.strip() for name in include.split(",")]
    unknown = [name for name in names if name not in INCLUDE_NAMES]
    if unknown:
        return unknown
    sections: set[str] = set()
    for name in names:
        sections.update(MAP_SECTION_ALIASES.get(name, (name,)))
    return frozenset(sections)


def server_timing(timings: dict[str, float]) -> str:
    return ", ".join(f"{name};dur={seconds * 1000:.1f}" for name, seconds in timings.items())


def themes_router(
    engine: Engine,
    archive: Archive,
    gateway: HindsightGateway | None,
    template_path: Path,
    universe: Callable[[], Universe],
    clock: Clock = utc_now,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/themes", tags=["themes"])

    def bottlenecks() -> Bottlenecks:
        if gateway is None:
            return Bottlenecks(status="not_configured", message=None, model=None)
        try:
            template = BankTemplate.load(template_path)  # read per request: it's small
            model = MentalModelReader(engine, archive, gateway, template).one(GAPS_MENTAL_MODEL)
        except (InvalidTemplate, HindsightError) as error:
            return Bottlenecks(status="unavailable", message=str(error), model=None)
        if model is None or not model.in_bank:
            return Bottlenecks(status="not_in_bank", message=None, model=model)
        refreshed = model.last_refreshed_at is not None and bool((model.content or "").strip())
        return Bottlenecks(
            status="refreshed" if refreshed else "not_refreshed", message=None, model=model
        )

    @router.get("", response_model=list[ThemeSummary])
    def themes() -> list[ThemeSummary]:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            return list_themes(connection, extend_universe(connection, universe()), clock())

    @router.get("/{theme_id}/map", response_model=ThemeMapView, responses={**NOT_FOUND, **INVALID})
    def map_of_theme(  # pyright: ignore[reportUnusedFunction]
        theme_id: str,
        response: Response,
        include: Annotated[
            str | None,
            Query(
                description="comma-separated sections to compute and return, from"
                f" {', '.join(INCLUDE_NAMES)} (`companies` is `layers` and `unlayered`); the"
                " others are absent, not computed. `theme` counts the edges and the"
                " Candidates, `counterparties` are the edges' ends. None: the whole map."
            ),
        ] = None,
    ) -> ThemeMapView | JSONResponse:
        sections = frozenset((*MAP_SECTIONS, "bottlenecks"))
        if include is not None:
            parsed = parse_include(include)
            if isinstance(parsed, list):
                return error_response(
                    422,
                    "invalid_include",
                    f"unknown section {', '.join(repr(name) for name in parsed)};"
                    f" include takes {', '.join(INCLUDE_NAMES)}",
                )
            sections = parsed
        timings: dict[str, float] = {}
        with engine.connect() as connection:
            found = theme_sections(
                connection,
                extend_universe(connection, universe()),
                theme_id,
                sections - {"bottlenecks"},
                timings,
                clock(),
            )
        if found is None:
            return not_found("theme")
        if "bottlenecks" in sections:
            started = time.perf_counter()
            found["bottlenecks"] = bottlenecks()
            timings["bottlenecks"] = time.perf_counter() - started
        # Where the time goes, for whoever is looking (a browser's network panel shows it).
        timing = server_timing(timings)
        if include is None:
            response.headers["Server-Timing"] = timing
            return ThemeMapView(**found)
        return JSONResponse(jsonable_encoder(found), headers={"Server-Timing": timing})

    @router.get("/{theme_id}/changes", response_model=list[ThemeChange], responses=NOT_FOUND)
    def changes_of_theme(  # pyright: ignore[reportUnusedFunction]
        theme_id: str,
        limit: Annotated[int, Query(ge=1, le=200, description="at most this many")] = 30,
    ) -> list[ThemeChange] | JSONResponse:
        with engine.connect() as connection:
            if theme_id not in extend_universe(connection, universe()).themes:
                return not_found("theme")
            return theme_changes(connection, theme_id, limit)

    return router
