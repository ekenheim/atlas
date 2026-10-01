"""The `propose_candidates` job handler (pausable: the mention extractor calls LiteLLM). A
`filers_only` job (an investigation's filing leads, by CIK) needs no LiteLLM."""

from atlas.audit import Actor
from atlas.candidates.proposals import PROPOSE_CANDIDATES_KIND, CandidateProposer, ProposePayload
from atlas.companies import load_universe
from atlas.discovery.ranking import load_ranking_config, site_host
from atlas.identity import EntityResolver
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources, run_recorder
from atlas.roles import RoleCaller
from atlas.settings import Settings


class CandidatesNotConfigured(RuntimeError):
    """A provider proposing Candidates needs (LiteLLM, SEC's user agent) isn't configured."""


def register_candidate_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def propose_candidates(job: Job) -> Artifacts:
        if not settings.sec_user_agent:
            raise CandidatesNotConfigured("entity resolution calls SEC: set ATLAS_SEC_USER_AGENT")
        universe = load_universe(settings.themes_config)
        ignored = frozenset(i.cik for c in universe.companies.values() for i in c.ignored_ciks)
        # What lead ranking knows of the universe, as an investigation's Scout gives it: the
        # companies' names and the hosts of their websites.
        names = sorted(
            {n for c in universe.companies.values() for n in (c.display_name, c.legal_name)}
        )
        sites = sorted(
            {site_host(c.website) for c in universe.companies.values() if c.website} - {""}
        )

        def theme_title(theme: str) -> str:
            config = universe.themes.get(theme)
            return config.title if config is not None else theme

        with (
            hindsight_resources(settings) as (_, engine),
            run_recorder(settings, engine) as runs,
            EntityResolver.from_settings(settings) as resolver,
        ):
            caller = RoleCaller.from_settings(settings, engine)
            filers_only = ProposePayload.model_validate(job.payload).filers_only
            if (runs is None or caller is None) and not filers_only:
                raise CandidatesNotConfigured(
                    "the mention extractor needs LiteLLM: set ATLAS_LITELLM_URL and"
                    " ATLAS_LITELLM_API_KEY"
                )
            proposer = CandidateProposer(
                engine,
                runs,
                caller,
                resolver,
                Actor.from_settings(settings),
                theme_title=theme_title,
                ranking=load_ranking_config(settings.lead_ranking_config),
                companies=names,
                company_sites=sites,
                ignored_ciks=ignored,
            )
            if caller is None:
                return proposer.propose(job)
            with caller:
                return proposer.propose(job)

    # Pausable: a LiteLLM quota or outage pauses the queue and requeues the job, which
    # resumes with the leads not yet examined.
    registry.register(PROPOSE_CANDIDATES_KIND, propose_candidates, pausable=True)
