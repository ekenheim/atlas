"""The `review_relationships` job handler."""

from atlas.archive import open_archive
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources, run_recorder
from atlas.relationships.review import REVIEW_RELATIONSHIPS_KIND, RelationshipReviewer
from atlas.roles import RoleCaller, RoleCallFailed
from atlas.settings import Settings


def register_relationship_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def review_relationships(job: Job) -> Artifacts:
        # Hindsight is needed only to record the run's provenance (its version and template).
        with (
            hindsight_resources(settings) as (_, engine),
            run_recorder(settings, engine) as runs,
        ):
            caller = RoleCaller.from_settings(settings, engine)
            if caller is None:
                raise RoleCallFailed(
                    "the Reviewer needs LiteLLM: set ATLAS_LITELLM_URL and ATLAS_LITELLM_API_KEY"
                )
            with caller:
                reviewer = RelationshipReviewer(
                    engine,
                    open_archive(settings),
                    caller,
                    runs,
                    per_call=settings.reviewer_assertions_per_call,
                )
                return reviewer.review(job)

    # Pausable: an LLM quota or outage pauses the queue and requeues the job, which resumes
    # with the Assertions not yet reviewed.
    registry.register(REVIEW_RELATIONSHIPS_KIND, review_relationships, pausable=True)
