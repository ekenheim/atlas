"""The `investigation_task` job handler (pausable: its roles call LiteLLM and Hindsight), and
the standalone Reader's `read_step` (pausable too; bottleneck-argument ticket 03)."""

from atlas.investigations.model import INVESTIGATION_TASK_KIND
from atlas.investigations.reader import READ_STEP_KIND, run_read_step
from atlas.investigations.tasks import InvestigationNotConfigured, TaskRunner
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources, run_recorder
from atlas.roles import RoleCaller
from atlas.settings import Settings


def register_investigation_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def investigation_task(job: Job) -> Artifacts:
        with hindsight_resources(settings) as (gateway, engine):
            return TaskRunner(settings, engine, gateway).run(job)

    def read_step(job: Job) -> Artifacts:
        with (
            hindsight_resources(settings) as (gateway, engine),
            run_recorder(settings, engine) as runs,
        ):
            caller = RoleCaller.from_settings(settings, engine)
            if runs is None or caller is None:
                raise InvestigationNotConfigured(
                    "the Reader needs LiteLLM (ATLAS_LITELLM_URL, ATLAS_LITELLM_API_KEY) and"
                    " Hindsight configured"
                )
            with caller:
                return run_read_step(settings, engine, gateway, runs, caller, job)

    registry.register(INVESTIGATION_TASK_KIND, investigation_task, pausable=True)
    # Pausable: an LLM quota or outage pauses the queue and requeues the job, which continues
    # its session where it stopped.
    registry.register(READ_STEP_KIND, read_step, pausable=True)
