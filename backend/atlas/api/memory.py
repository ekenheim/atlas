"""`/api/v1` reads of retention into memory.

- `GET /source-versions/{id}/memory`: the version's section documents in the research bank,
  with their retain states, fact counts, and the Hindsight operations that retained them.
"""

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, not_found
from atlas.retention import SourceVersionMemory, source_version_memory


def memory_router(engine: Engine, bank_id: str) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["memory"])

    @router.get(
        "/source-versions/{version_id}/memory",
        response_model=SourceVersionMemory,
        responses=NOT_FOUND,
    )
    def source_version_memory_documents(  # pyright: ignore[reportUnusedFunction]
        version_id: uuid.UUID,
    ) -> SourceVersionMemory | JSONResponse:
        with engine.connect() as connection:
            found = source_version_memory(connection, version_id, bank_id)
        return found if found is not None else not_found("source version")

    return router
