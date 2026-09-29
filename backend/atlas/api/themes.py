"""`/api/v1/themes`: the Theme explorer (product spec §10.1 A; ticket 23).

- `GET /themes`: each theme with its coverage (company count, companies without sources,
  empty layers, Relationship and open Candidate counts)
- `GET /themes/{id}/map`: the theme's companies by supply-chain layer (upstream to
  downstream, empty layers included), the Relationships between them, its Candidates, and
  the Bottlenecks mental model's open gaps

The Bottlenecks model is Hindsight output, never Evidence: it comes with its citations
resolved like a reflect answer's, and with a `status` saying why it is absent
(`not_configured`, `not_in_bank`, `unavailable`) or not yet generated (`not_refreshed`). A
Hindsight failure never fails the map. Errors use the envelope: 404 `not_found`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, not_found
from atlas.archive import Archive
from atlas.bank_template import BankTemplate, InvalidTemplate
from atlas.companies import Universe, extend_universe
from atlas.discovery.service import GAPS_MENTAL_MODEL
from atlas.hindsight import HindsightError, HindsightGateway
from atlas.mental_models import MentalModelReader, MentalModelView
from atlas.themes import ThemeMap, ThemeSummary, list_themes, theme_map

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


def themes_router(
    engine: Engine,
    archive: Archive,
    gateway: HindsightGateway | None,
    template_path: Path,
    universe: Callable[[], Universe],
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
            return list_themes(connection, extend_universe(connection, universe()))

    @router.get("/{theme_id}/map", response_model=ThemeMapView, responses=NOT_FOUND)
    def map_of_theme(theme_id: str) -> ThemeMapView | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = theme_map(connection, extend_universe(connection, universe()), theme_id)
        if found is None:
            return not_found("theme")
        return ThemeMapView(**dict(found), bottlenecks=bottlenecks())

    return router
