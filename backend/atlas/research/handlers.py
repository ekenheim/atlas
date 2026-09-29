"""The `reflect` job handler."""

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.companies import load_universe
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources, run_recorder
from atlas.research.service import REFLECT_KIND, ReflectPayload, Research
from atlas.settings import Settings


def register_research_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def reflect(job: Job) -> Artifacts:
        payload = ReflectPayload.model_validate(job.payload)
        with (
            hindsight_resources(settings) as (gateway, engine),
            run_recorder(settings, engine) as runs,
        ):
            research = Research(
                engine,
                open_archive(settings),
                gateway,
                Actor.from_settings(settings),
                lambda: load_universe(settings.themes_config),
            )
            return research.answer(payload.research_answer_id, job, runs)

    registry.register(REFLECT_KIND, reflect)
