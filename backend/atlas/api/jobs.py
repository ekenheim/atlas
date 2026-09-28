"""`/api/v1/jobs`: job status, attempts, failures and produced artifacts."""

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from atlas.jobs import Job, JobQueue


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorEnvelope(error=ErrorDetail(code=code, message=message))
    return JSONResponse(body.model_dump(), status_code=status_code)


def jobs_router(queue: JobQueue) -> APIRouter:
    router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

    @router.get("/{job_id}", response_model=Job, responses={404: {"model": ErrorEnvelope}})
    def get_job(job_id: uuid.UUID) -> Job | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        job = queue.get(job_id)
        if job is None:
            return error_response(404, "not_found", "job not found")
        return job

    return router
