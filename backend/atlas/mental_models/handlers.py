"""The `refresh_mental_model` job handler and the daily refresh schedule."""

import logging
from datetime import time

from sqlalchemy import Engine, create_engine

from atlas.audit import Actor
from atlas.bank_template import BankTemplate, InvalidTemplate
from atlas.hindsight import HindsightGateway
from atlas.jobs.handlers import HandlerRegistry, Schedule
from atlas.jobs.pacing import Clock
from atlas.jobs.queue import Artifacts, Job
from atlas.mental_models.refresh import (
    REFRESH_KIND,
    MentalModelRefresher,
    RefreshPayload,
    RefreshSchedule,
    RefreshTimings,
)
from atlas.runs import RunRecorder
from atlas.settings import Settings

log = logging.getLogger("atlas.mental_models")


class HindsightNotConfigured(Exception):
    """A refresh job ran without ATLAS_HINDSIGHT_URL."""


def register_mental_model_handlers(
    registry: HandlerRegistry, settings: Settings, clock: Clock
) -> None:
    def refresh(job: Job) -> Artifacts:
        payload = RefreshPayload.model_validate(job.payload)
        gateway = HindsightGateway.from_settings(settings)
        if gateway is None:
            raise HindsightNotConfigured("Hindsight is not configured (ATLAS_HINDSIGHT_URL)")
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        runs = RunRecorder.from_settings(settings, engine)
        try:
            refresher = MentalModelRefresher(
                engine,
                gateway,
                BankTemplate.load(settings.hindsight_template_path),
                Actor.from_settings(settings),
                clock=clock,
                timings=RefreshTimings(
                    poll_timeout=settings.mental_model_poll_timeout_seconds,
                    poll_interval=settings.mental_model_poll_interval_seconds,
                ),
                runs=runs,
            )
            return refresher.refresh(payload, job)
        finally:
            if runs is not None:
                runs.close()
            gateway.close()
            engine.dispose()

    # Pausable: a refresh is an LLM run, so quota and outages pause it like a retain.
    registry.register(REFRESH_KIND, refresh, pausable=True)


def refresh_schedules(settings: Settings, engine: Engine) -> list[Schedule]:
    """The daily refresh schedule, or none when Hindsight or the schedule is off."""
    if not settings.hindsight_url or not settings.mental_model_refresh_at:
        return []
    try:
        template = BankTemplate.load(settings.hindsight_template_path)
    except InvalidTemplate as error:
        log.error(f"mental model refreshes not scheduled: invalid bank template ({error})")
        return []
    hour, minute = (int(part) for part in settings.mental_model_refresh_at.split(":"))
    return [RefreshSchedule(engine, settings.hindsight_bank_id, template, time(hour, minute))]
