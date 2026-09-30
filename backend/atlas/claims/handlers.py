"""The `extract_claims` job handler, and the extractor it (and an investigation) runs."""

import uuid
from collections.abc import Generator
from contextlib import ExitStack, contextmanager

from sqlalchemy import Engine

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.claims.extraction import EXTRACT_CLAIMS_KIND, ClaimExtractor
from atlas.companies import load_universe
from atlas.hindsight import HindsightGateway
from atlas.identity import EntityResolver
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources, run_recorder
from atlas.research.provenance import Evidence
from atlas.research.service import RecallRequest, Research, ResearchScope
from atlas.roles import RoleCaller, RoleCallFailed
from atlas.runs import RunRecorder
from atlas.settings import Settings


@contextmanager
def claim_extractor(
    settings: Settings,
    engine: Engine,
    gateway: HindsightGateway,
    caller: RoleCaller,
    runs: RunRecorder | None,
    *,
    max_passages: int | None = None,
) -> Generator[ClaimExtractor]:
    """The Investigator's extractor over the configured archive, recalling through Hindsight.
    With `ATLAS_SEC_USER_AGENT` set it resolves a company a Claim names outside the known
    ones (a counterparty company); without it such a name is rejected as unresolved.
    `max_passages` is the passage budget (default `investigator_max_passages`)."""
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

    with ExitStack() as stack:
        resolver: EntityResolver | None = None
        ignored_ciks: frozenset[str] = frozenset()
        if settings.sec_user_agent:
            resolver = stack.enter_context(EntityResolver.from_settings(settings))
            configured = load_universe(settings.themes_config).companies.values()
            ignored_ciks = frozenset(i.cik for c in configured for i in c.ignored_ciks)
        yield ClaimExtractor(
            engine,
            archive,
            caller,
            runs,
            recall=recall,
            max_passages=max_passages or settings.investigator_max_passages,
            passages_per_call=settings.investigator_passages_per_call,
            resolver=resolver,
            ignored_ciks=ignored_ciks,
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
            with caller, claim_extractor(settings, engine, gateway, caller, runs) as extractor:
                return extractor.extract(job)

    # Pausable: an LLM quota or outage (or a Hindsight one, in the recall) pauses the queue
    # and requeues the job, which resumes at its next batch.
    registry.register(EXTRACT_CLAIMS_KIND, extract_claims, pausable=True)
