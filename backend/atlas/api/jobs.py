"""`/api/v1/jobs`: job status, attempts, failures and produced artifacts."""

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from atlas.api.common import NOT_FOUND, not_found
from atlas.jobs import Job, JobQueue


def jobs_router(queue: JobQueue) -> APIRouter:
    router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

    @router.get("/{job_id}", response_model=Job, responses=NOT_FOUND)
    def get_job(job_id: uuid.UUID) -> Job | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        job = queue.get(job_id)
        return job if job is not None else not_found("job")

    return router
