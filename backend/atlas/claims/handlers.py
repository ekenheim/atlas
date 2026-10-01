"""The `extract_claims` job handler, and the extractor it (and an investigation) runs."""

from collections.abc import Generator
from contextlib import ExitStack, contextmanager

from sqlalchemy import Engine

from atlas.archive import open_archive
from atlas.claims.extraction import EXTRACT_CLAIMS_KIND, ClaimExtractor
from atlas.companies import load_universe
from atlas.identity import EntityResolver
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources, run_recorder
from atlas.roles import RoleCaller, RoleCallFailed
from atlas.runs import RunRecorder
from atlas.settings import Settings


@contextmanager
def claim_extractor(
    settings: Settings,
    engine: Engine,
    caller: RoleCaller,
    runs: RunRecorder | None,
    *,
    max_passages: int | None = None,
) -> Generator[ClaimExtractor]:
    """The Investigator's extractor over the configured archive. It asks Memory nothing: its
    passages are chosen by search, entity tags and, inside an investigation, the reading
    pointers the caller passes to `extract` (atlas.claims.selection).
    With `ATLAS_SEC_USER_AGENT` set it resolves a company a Claim names outside the known
    ones (a counterparty company); without it such a name is rejected as unresolved.
    `max_passages` is the passage budget (default `investigator_max_passages`), of which one
    document takes at most `investigator_max_passage_share_per_document` while others have
    candidates."""
    with ExitStack() as stack:
        resolver: EntityResolver | None = None
        ignored_ciks: frozenset[str] = frozenset()
        if settings.sec_user_agent:
            resolver = stack.enter_context(EntityResolver.from_settings(settings))
            configured = load_universe(settings.themes_config).companies.values()
            ignored_ciks = frozenset(i.cik for c in configured for i in c.ignored_ciks)
        yield ClaimExtractor(
            engine,
            open_archive(settings),
            caller,
            runs,
            max_passages=max_passages or settings.investigator_max_passages,
            passages_per_call=settings.investigator_passages_per_call,
            max_document_share=settings.investigator_max_passage_share_per_document,
            resolver=resolver,
            ignored_ciks=ignored_ciks,
        )


def register_claim_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def extract_claims(job: Job) -> Artifacts:
        with (
            # Hindsight is needed for the run record only (the bank's template version).
            hindsight_resources(settings) as (_, engine),
            run_recorder(settings, engine) as runs,
        ):
            caller = RoleCaller.from_settings(settings, engine)
            if caller is None:
                raise RoleCallFailed(
                    "the Investigator needs LiteLLM: set ATLAS_LITELLM_URL and"
                    " ATLAS_LITELLM_API_KEY"
                )
            with caller, claim_extractor(settings, engine, caller, runs) as extractor:
                return extractor.extract(job)

    # Pausable: an LLM quota or outage pauses the queue and requeues the job, which resumes
    # at its next batch.
    registry.register(EXTRACT_CLAIMS_KIND, extract_claims, pausable=True)
