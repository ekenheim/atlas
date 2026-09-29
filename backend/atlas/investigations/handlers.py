"""The `investigation_task` job handler (pausable: its roles call LiteLLM and Hindsight)."""

from atlas.investigations.model import INVESTIGATION_TASK_KIND
from atlas.investigations.tasks import TaskRunner
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources
from atlas.settings import Settings


def register_investigation_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def investigation_task(job: Job) -> Artifacts:
        with hindsight_resources(settings) as (gateway, engine):
            return TaskRunner(settings, engine, gateway).run(job)

    registry.register(INVESTIGATION_TASK_KIND, investigation_task, pausable=True)
