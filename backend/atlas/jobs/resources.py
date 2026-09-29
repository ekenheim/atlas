"""What a Hindsight job handler holds for one attempt: the gateway, a database engine and,
for an LLM run, the run recorder."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import NamedTuple

from sqlalchemy import Engine

from atlas.db import create_engine
from atlas.hindsight import HindsightGateway, HindsightNotConfigured
from atlas.runs import RunRecorder
from atlas.settings import Settings


class HindsightResources(NamedTuple):
    gateway: HindsightGateway
    engine: Engine


@contextmanager
def hindsight_resources(settings: Settings) -> Generator[HindsightResources]:
    """The gateway and an engine, closed and disposed on exit.

    Raises `HindsightNotConfigured` (a failed attempt) when ATLAS_HINDSIGHT_URL is not set.
    """
    gateway = HindsightGateway.from_settings(settings)
    if gateway is None:
        raise HindsightNotConfigured
    engine = create_engine(settings)
    try:
        yield HindsightResources(gateway, engine)
    finally:
        gateway.close()
        engine.dispose()


@contextmanager
def run_recorder(settings: Settings, engine: Engine) -> Generator[RunRecorder | None]:
    """The run recorder (None when LiteLLM or Hindsight is not configured), closed on exit."""
    runs = RunRecorder.from_settings(settings, engine)
    try:
        yield runs
    finally:
        if runs is not None:
            runs.close()
