"""The `reflect` job handler."""

from sqlalchemy import create_engine

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.companies import load_universe
from atlas.hindsight import HindsightGateway
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.research.service import REFLECT_KIND, ReflectPayload, Research
from atlas.runs import RunRecorder
from atlas.settings import Settings


class HindsightNotConfigured(Exception):
    """A reflect job ran without ATLAS_HINDSIGHT_URL."""


def register_research_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def reflect(job: Job) -> Artifacts:
        payload = ReflectPayload.model_validate(job.payload)
        gateway = HindsightGateway.from_settings(settings)
        if gateway is None:
            raise HindsightNotConfigured("Hindsight is not configured (ATLAS_HINDSIGHT_URL)")
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        runs = RunRecorder.from_settings(settings, engine)
        try:
            research = Research(
                engine,
                open_archive(settings),
                gateway,
                Actor.from_settings(settings),
                lambda: load_universe(settings.themes_config),
            )
            return research.answer(payload.research_answer_id, job, runs)
        finally:
            if runs is not None:
                runs.close()
            gateway.close()
            engine.dispose()

    registry.register(REFLECT_KIND, reflect)
