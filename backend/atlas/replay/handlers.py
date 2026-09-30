"""The `replay` job handler (pausable; budgeted under `codex`)."""

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.bank_template import BankTemplate
from atlas.companies import extend_universe, load_universe
from atlas.db import create_engine
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.replay.service import (
    REPLAY_KIND,
    GatewayFactory,
    ReplayPayload,
    Replays,
    ReplayTimings,
)
from atlas.settings import Settings


def register_replay_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def replay(job: Job) -> Artifacts:
        payload = ReplayPayload.model_validate(job.payload)
        engine = create_engine(settings)
        try:
            with engine.connect() as connection:
                # Committed Candidates' companies are tagged with their themes too.
                universe = extend_universe(connection, load_universe(settings.themes_config))
            return Replays(
                engine,
                open_archive(settings),
                Actor.from_settings(settings),
                universe,
                BankTemplate.load(settings.hindsight_template_path),
                GatewayFactory(settings.replay_hindsight_url, settings.replay_hindsight_api_key),
                ReplayTimings(
                    poll_timeout=settings.retain_poll_timeout_seconds,
                    poll_interval=settings.retain_poll_interval_seconds,
                    poll_attempts=settings.retain_poll_attempts,
                    consolidation_timeout=settings.replay_consolidation_timeout_seconds,
                ),
            ).run(payload.replay_job_id, job)
        finally:
            engine.dispose()

    # It depends on Hindsight: a quota or outage failure pauses it with the other kinds.
    registry.register(REPLAY_KIND, replay, pausable=True)
