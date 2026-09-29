"""The `discover` job handler (pausable: the Scout calls LiteLLM)."""

from atlas.companies import load_universe
from atlas.discovery.searxng import SearXNGClient
from atlas.discovery.service import DISCOVER_KIND, DiscoverPayload, Scout
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources, run_recorder
from atlas.roles import RoleCaller
from atlas.settings import Settings


class UnknownTheme(LookupError):
    """The payload names a theme the universe config doesn't define."""


class DiscoveryNotConfigured(RuntimeError):
    """A provider discovery needs (SearXNG, LiteLLM) isn't configured."""


def register_discovery_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def discover(job: Job) -> Artifacts:
        payload = DiscoverPayload.model_validate(job.payload)
        universe = load_universe(settings.themes_config)
        theme = universe.themes.get(payload.theme)
        if theme is None:
            raise UnknownTheme(f"no theme {payload.theme!r} in {settings.themes_config}")
        searxng = SearXNGClient.from_settings(settings)
        if searxng is None:
            raise DiscoveryNotConfigured("discovery needs SearXNG: set ATLAS_SEARXNG_URL")
        with (
            searxng,
            hindsight_resources(settings) as (gateway, engine),
            run_recorder(settings, engine) as runs,
        ):
            caller = RoleCaller.from_settings(settings, engine)
            if runs is None or caller is None:
                raise DiscoveryNotConfigured(
                    "discovery needs LiteLLM: set ATLAS_LITELLM_URL and ATLAS_LITELLM_API_KEY"
                )
            with caller:
                scout = Scout(
                    engine,
                    runs,
                    caller,
                    gateway,
                    searxng,
                    max_queries=settings.discovery_max_queries,
                )
                return scout.discover(
                    job, payload.theme, theme, payload.question, run_id=payload.run_id
                )

    registry.register(DISCOVER_KIND, discover, pausable=True)
