"""The `draft_hypothesis` job handler (pausable: the Editor calls LiteLLM)."""

from atlas.hypotheses.drafting import HypothesisDrafter
from atlas.hypotheses.model import DRAFT_HYPOTHESIS_KIND
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources, run_recorder
from atlas.roles import RoleCaller, RoleCallFailed
from atlas.settings import Settings


def register_hypothesis_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def draft_hypothesis(job: Job) -> Artifacts:
        # Hindsight is needed only to record the run's provenance (its version and template).
        with (
            hindsight_resources(settings) as (_, engine),
            run_recorder(settings, engine) as runs,
        ):
            caller = RoleCaller.from_settings(settings, engine)
            if caller is None:
                raise RoleCallFailed(
                    "the Editor needs LiteLLM: set ATLAS_LITELLM_URL and ATLAS_LITELLM_API_KEY"
                )
            with caller:
                return HypothesisDrafter(settings, engine, caller, runs).draft(job)

    registry.register(DRAFT_HYPOTHESIS_KIND, draft_hypothesis, pausable=True)
