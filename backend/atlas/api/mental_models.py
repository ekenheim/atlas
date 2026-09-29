"""`/api/v1/mental-models`: the bank template's mental models (spec Part B stories 26-29).

- `GET /mental-models`: every mental model the bank template defines (Theme status,
  Bottlenecks), each with its content, its history, and its citations resolved like a
  reflect answer's (resolved, unverified or broken; only resolved ones are `evidence`), plus
  Atlas's records of its refreshes
- `GET /mental-models/{id}`: one of them

A model the template defines but the bank doesn't hold yet (the template isn't applied) is
listed with `in_bank: false`. Errors use the envelope: 404 `not_found` (no such model in the
template), 503 `hindsight_not_configured`, 502 `hindsight_unavailable` / `hindsight_error`,
500 `invalid_template`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, ErrorEnvelope, error_response, not_found
from atlas.archive import Archive
from atlas.bank_template import BankTemplate, InvalidTemplate
from atlas.hindsight import HindsightError, HindsightGateway, HindsightUnavailable
from atlas.mental_models import MentalModelList, MentalModelReader, MentalModelView

_ERRORS: dict[int | str, dict[str, Any]] = {
    500: {"model": ErrorEnvelope},
    502: {"model": ErrorEnvelope},
    503: {"model": ErrorEnvelope},
}


def mental_models_router(
    engine: Engine, archive: Archive, gateway: HindsightGateway | None, template_path: Path
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/mental-models", tags=["mental-models"])

    def read[T](use: Callable[[MentalModelReader], T]) -> T | JSONResponse:
        if gateway is None:
            return error_response(
                503, "hindsight_not_configured", "Hindsight is not configured (ATLAS_HINDSIGHT_URL)"
            )
        try:
            template = BankTemplate.load(template_path)  # read per request: it's small
            return use(MentalModelReader(engine, archive, gateway, template))
        except InvalidTemplate as error:
            return error_response(500, "invalid_template", str(error))
        except HindsightUnavailable as error:
            return error_response(502, "hindsight_unavailable", str(error))
        except HindsightError as error:
            return error_response(502, "hindsight_error", str(error))

    @router.get("", response_model=MentalModelList, responses=_ERRORS)
    def list_mental_models() -> MentalModelList | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return read(lambda reader: reader.all())

    @router.get(
        "/{mental_model_id}", response_model=MentalModelView, responses={**NOT_FOUND, **_ERRORS}
    )
    def get_mental_model(mental_model_id: str) -> MentalModelView | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        found = read(lambda reader: reader.one(mental_model_id))
        return not_found("mental model") if found is None else found

    return router
