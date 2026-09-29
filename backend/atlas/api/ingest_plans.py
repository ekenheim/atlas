"""`/api/v1/ingest-plans`: what each first backfill ingest of a company discovered, before it
fetched or retained anything (`atlas.ledger.plans`), newest first."""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import Engine

from atlas.ledger.plans import IngestPlan, list_plans


class IngestPlans(BaseModel):
    items: list[IngestPlan]


def ingest_plans_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1/ingest-plans", tags=["ingest"])

    @router.get("", response_model=IngestPlans)
    def get_plans(company: str | None = None) -> IngestPlans:  # pyright: ignore[reportUnusedFunction]
        return IngestPlans(items=list_plans(engine, company))

    return router
