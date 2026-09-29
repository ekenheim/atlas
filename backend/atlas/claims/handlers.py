"""The `extract_claims` job handler, and the extractor it (and an investigation) runs."""

import uuid

from sqlalchemy import Engine

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.claims.extraction import EXTRACT_CLAIMS_KIND, ClaimExtractor
from atlas.companies import load_universe
from atlas.hindsight import HindsightGateway
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources, run_recorder
from atlas.research.provenance import Evidence
from atlas.research.service import RecallRequest, Research, ResearchScope
from atlas.roles import RoleCaller, RoleCallFailed
from atlas.runs import RunRecorder
from atlas.settings import Settings


def claim_extractor(
    settings: Settings,
    engine: Engine,
    gateway: HindsightGateway,
    caller: RoleCaller,
    runs: RunRecorder | None,
) -> ClaimExtractor:
    """The Investigator's extractor over the configured archive, recalling through Hindsight."""
    archive = open_archive(settings)
    research = Research(
        engine,
        archive,
        gateway,
        Actor.from_settings(settings),
        lambda: load_universe(settings.themes_config),
    )

    def recall(question: str, company_ids: list[uuid.UUID]) -> list[Evidence]:
        scope = ResearchScope(company_ids=company_ids)
        return research.recall(RecallRequest(query=question, scope=scope)).evidence

    return ClaimExtractor(
        engine,
        archive,
        caller,
        runs,
        recall=recall,
        max_passages=settings.investigator_max_passages,
        passages_per_call=settings.investigator_passages_per_call,
    )


def register_claim_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def extract_claims(job: Job) -> Artifacts:
        with (
            hindsight_resources(settings) as (gateway, engine),
            run_recorder(settings, engine) as runs,
        ):
            caller = RoleCaller.from_settings(settings, engine)
            if caller is None:
                raise RoleCallFailed(
                    "the Investigator needs LiteLLM: set ATLAS_LITELLM_URL and"
                    " ATLAS_LITELLM_API_KEY"
                )
            with caller:
                return claim_extractor(settings, engine, gateway, caller, runs).extract(job)

    # Pausable: an LLM quota or outage (or a Hindsight one, in the recall) pauses the queue
    # and requeues the job, which resumes at its next batch.
    registry.register(EXTRACT_CLAIMS_KIND, extract_claims, pausable=True)
