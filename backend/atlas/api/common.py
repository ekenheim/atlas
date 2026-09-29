"""Shared API shapes: the error envelope (its responses and OpenAPI maps) and paginated lists."""

from typing import Any

from fastapi import Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from atlas.hindsight import HINDSIGHT_NOT_CONFIGURED, HindsightError, HindsightUnavailable


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorEnvelope(error=ErrorDetail(code=code, message=message))
    return JSONResponse(body.model_dump(), status_code=status_code)


def not_found(what: str) -> JSONResponse:
    return error_response(404, "not_found", f"{what} not found")


def hindsight_not_configured() -> JSONResponse:
    return error_response(503, "hindsight_not_configured", HINDSIGHT_NOT_CONFIGURED)


def hindsight_failed(error: HindsightError) -> JSONResponse:
    """502: `hindsight_unavailable` (unreachable, timed out) or `hindsight_error`."""
    code = "hindsight_unavailable" if isinstance(error, HindsightUnavailable) else "hindsight_error"
    return error_response(502, code, str(error))


type ErrorResponses = dict[int | str, dict[str, Any]]


def error_responses(*status_codes: int) -> ErrorResponses:
    """OpenAPI `responses` documenting the error envelope for each status code."""
    return {status_code: {"model": ErrorEnvelope} for status_code in status_codes}


NOT_FOUND = error_responses(404)
INVALID = error_responses(422)
CONFLICT = error_responses(409)
# The Hindsight failures: 502 (unavailable or an error) and 503 (not configured).
HINDSIGHT_FAILURES = error_responses(502, 503)


def invalid_request(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's request validation errors, in the error envelope (code `invalid_request`)."""
    if not isinstance(exc, RequestValidationError):
        raise exc
    problems = [
        f"{'.'.join(str(part) for part in error.get('loc', ()))}: {error.get('msg', 'invalid')}"
        for error in exc.errors()
    ]
    return error_response(422, "invalid_request", "; ".join(problems) or "invalid request")


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class Pagination(BaseModel):
    limit: int
    offset: int


def pagination(
    limit: int = Query(50, ge=1, le=500, description="page size"),
    offset: int = Query(0, ge=0, description="items to skip"),
) -> Pagination:
    return Pagination(limit=limit, offset=offset)
