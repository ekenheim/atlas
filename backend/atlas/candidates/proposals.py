"""Proposing Candidates: the companies a discovery's leads name, resolved against the universe.

One `propose_candidates` job (payload `{"discovery_id", "filers_only"?}`; enqueued by each
`discover` job when entity resolution is configured, and with `filers_only` by an
investigation's Scout) examines the discovery's leads not examined before:

0. **Filings.** An `edgar_fts` lead (an EDGAR full-text search hit; pilot fix 12) names its
   company exactly: its filer's CIK. It is examined without the mention extractor (method
   `filer_cik`, no role call): the CIK goes through `resolve_mention`, and the filer is
   `in_universe`, `unresolved` or, outside the universe, a Candidate keyed by its CIK, as in
   steps 2-3. With `filers_only` the other leads are left for another job.

   **A filer outside the universe needs a kept hit** (memory-directed reading, ticket 04): at
   least one of its filing leads must score at or above the lead ranking's keep threshold
   (atlas.discovery.ranking: the lead scored against the query that found it and that
   query's purpose in this discovery, as a web lead is; a hit of a bare vocabulary term
   demoted). Otherwise the filer is not resolved (no registry is asked), nothing is proposed,
   and its leads stay unexamined, so a later discovery whose query they answer better can
   still propose it; the job's artifacts list each such filer with its best score and the
   reasons (`filers_below_threshold`). A filer in the universe is recorded whatever its
   leads score. A filer that is a counterparty company is outside the universe: with a kept
   hit it is proposed like any other, once per theme (the Candidate is keyed by its CIK),
   and the Candidate's `counterparty_company_id` names the counterparty its commit promotes.

1. **Mentions.** The mention extractor role (atlas.roles.mentions) reads the leads' titles
   and snippets, `LEADS_PER_CALL` leads per call, as quoted low-trust data, and lists the
   companies each names (name, ticker?, exchange?). Code, not the model, maps an exchange
   name to its MIC (`exchange_mic`; an unknown one is dropped, leaving a ticker without a
   venue) and ignores answers for leads it wasn't sent.
2. **Resolution.** Each mention goes through `resolve_mention` (the universe first, then
   SEC, GLEIF and OpenFIGI), with every configured company's ignored (unsponsored-ADR)
   CIKs. A mention of a universe company is recorded as `in_universe`; one no source
   identifies as `unresolved`; any other is an unseeded match and proposes a Candidate. A
   counterparty company is not in the universe: a lead naming one proposes a Candidate like
   any unseeded company, and committing it promotes the counterparty.
3. **Candidates.** A Candidate is a (theme, company) pair keyed by what identified the
   company: `cik:` its CIK, else `lei:` its LEI, else `name:` the normalized name (several
   or conflicting matches). A second lead naming the same company joins the same Candidate.
   Its proposed source path is `sec` when a CIK was resolved, else none (no automated source
   yet). Nothing is committed: only the owner commits a Candidate (atlas.candidates.service).

Each batch's leads, mentions and new Candidates are stored in one transaction (audited), so
a retried job re-reads only the leads not yet examined. The role calls belong to one run
(kind `candidates`), finished when the attempt ends.
"""

import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Connection, Engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.expression import bindparam

from atlas.audit import Actor, content_hash, record
from atlas.discovery.leads import discovery_sightings
from atlas.discovery.ranking import RankedLead, RankingConfig, rank_leads
from atlas.identity import EntityResolver, Mention, Resolution
from atlas.identity.normalize import MIC_CURRENCY, OPERATING_MIC, US_STATES, normalize_name
from atlas.identity.service import find_in_universe, resolve_mention
from atlas.jobs.queue import Artifacts, Job
from atlas.roles import QuotedText, RoleCaller, run_usage
from atlas.roles.mentions import MENTION_EXTRACTOR, CompanyMention, MentionRequest
from atlas.runs import RunRecorder

PROPOSE_CANDIDATES_KIND = "propose_candidates"
RUN_KIND = "candidates"
LEADS_PER_CALL = 10

_SPACE = re.compile(r"\s+")
# Exchange names as news text writes them → ISO 10383 operating MIC (a segment MIC or an
# operating MIC given as such is accepted too). Anything else is dropped, not guessed.
_EXCHANGE_MIC = {
    "NASDAQ": "XNAS",
    "NASDAQ GS": "XNAS",
    "NASDAQGS": "XNAS",
    "NASDAQ GM": "XNAS",
    "NASDAQGM": "XNAS",
    "NASDAQ CM": "XNAS",
    "NASDAQ GLOBAL SELECT": "XNAS",
    "NASDAQ GLOBAL SELECT MARKET": "XNAS",
    "NYSE": "XNYS",
    "NEW YORK STOCK EXCHANGE": "XNYS",
    "NYSE AMERICAN": "XASE",
    "AMEX": "XASE",
    "NYSE ARCA": "ARCX",
    "HKEX": "XHKG",
    "SEHK": "XHKG",
    "HONG KONG STOCK EXCHANGE": "XHKG",
    "LSE": "XLON",
    "LONDON STOCK EXCHANGE": "XLON",
    "AIM": "AIMX",
    "EURONEXT PARIS": "XPAR",
    "EPA": "XPAR",
    "EURONEXT AMSTERDAM": "XAMS",
    "EURONEXT MILAN": "XMIL",
    "BORSA ITALIANA": "XMIL",
    "XETRA": "XETR",
    "TWSE": "XTAI",
    "TAIWAN STOCK EXCHANGE": "XTAI",
    "TSE": "XTKS",
    "TYO": "XTKS",
    "TOKYO STOCK EXCHANGE": "XTKS",
    "SZSE": "XSHE",
    "SHENZHEN STOCK EXCHANGE": "XSHE",
    "SSE": "XSHG",
    "SHANGHAI STOCK EXCHANGE": "XSHG",
}
_KNOWN_MICS = frozenset(MIC_CURRENCY) | frozenset(OPERATING_MIC)


def exchange_mic(exchange: str | None) -> str | None:
    """The MIC of an exchange as text names it, or None when it isn't one Atlas knows."""
    if exchange is None:
        return None
    key = _SPACE.sub(" ", exchange.replace(".", "")).strip().upper()
    if key in _KNOWN_MICS:
        return key
    return _EXCHANGE_MIC.get(key)


class ProposePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    discovery_id: uuid.UUID
    # Only the discovery's filing leads (by their filer's CIK): no mention extractor call.
    filers_only: bool = False


class MentionExtractorNotConfigured(RuntimeError):
    """Leads need the mention extractor, but LiteLLM isn't configured."""


class UnknownDiscovery(LookupError):
    """The payload names no discovery."""


@dataclass(frozen=True)
class _Lead:
    id: uuid.UUID
    canonical_url: str
    title: str
    snippet: str
    filer_cik: str | None  # an `edgar_fts` lead's filer
    filer: str | None
    ticker: str | None


@dataclass(frozen=True)
class _Identity:
    key: str
    name: str
    cik: str | None
    lei: str | None
    country: str | None


def _identity(resolution: Resolution, mention: Mention) -> _Identity:
    """What identifies an unseeded match (see the module)."""
    entity = resolution.entity if resolution.tier != "conflict" else None
    if entity is not None and not entity.name:
        entity = None
    if entity is None and resolution.tier != "conflict" and len(resolution.candidates) == 1:
        entity = resolution.candidates[0]
    name = (entity.name if entity else None) or mention.name or mention.ticker or "?"
    if entity is None:
        return _Identity(f"name:{normalize_name(name)}", name, None, None, None)
    country: str | None = None
    if entity.jurisdiction:
        country = entity.jurisdiction.split("-", 1)[0]
    elif entity.state_of_incorporation in US_STATES:
        country = "US"
    if country is not None and not re.fullmatch(r"[A-Z]{2}", country):
        country = None
    if entity.cik:
        # The LEI a CIK-identified entity was linked to by name is the owner's to confirm
        # (ticket 02), so a Candidate keyed by CIK doesn't carry it.
        return _Identity(f"cik:{entity.cik}", name, entity.cik, None, country)
    if entity.lei:
        return _Identity(f"lei:{entity.lei}", name, None, entity.lei, country)
    return _Identity(f"name:{normalize_name(name)}", name, None, None, country)


class CandidateProposer:
    """Examines a discovery's leads and proposes Candidates (see the module)."""

    def __init__(
        self,
        engine: Engine,
        runs: RunRecorder | None,
        caller: RoleCaller | None,
        resolver: EntityResolver,
        actor: Actor,
        *,
        theme_title: Callable[[str], str],
        ranking: RankingConfig,
        companies: Sequence[str] = (),
        company_sites: Sequence[str] = (),
        ignored_ciks: frozenset[str] = frozenset(),
        leads_per_call: int = LEADS_PER_CALL,
    ) -> None:
        """`ranking`, with the universe's company names and website hosts, scores a filing
        lead as an investigation's Scout does (atlas.discovery.ranking)."""
        self._engine = engine
        self._runs = runs
        self._caller = caller
        self._resolver = resolver
        self._actor = actor
        self._theme_title = theme_title
        self._ranking = ranking
        self._companies = tuple(companies)
        self._company_sites = tuple(company_sites)
        self._ignored = ignored_ciks
        self._per_call = leads_per_call
        self._resolved: dict[tuple[str, str | None, str | None], Resolution] = {}

    def propose(self, job: Job) -> Artifacts:
        payload = ProposePayload.model_validate(job.payload)
        with self._engine.connect() as connection:
            theme = connection.execute(
                text("SELECT theme FROM discovery WHERE id = :id"), {"id": payload.discovery_id}
            ).scalar_one_or_none()
            if theme is None:
                raise UnknownDiscovery(f"no discovery {payload.discovery_id}")
            found = [
                _Lead(
                    row.id,
                    row.canonical_url,
                    row.title,
                    row.snippet,
                    row.cik,
                    row.filer,
                    row.ticker,
                )
                for row in connection.execute(
                    text(
                        "SELECT DISTINCT lead.id, lead.canonical_url, lead.title, lead.snippet,"
                        " lead.first_seen_at, f.cik, f.filer, f.ticker FROM lead"
                        " JOIN lead_sighting s ON s.lead_id = lead.id"
                        " JOIN discovery_query q ON q.id = s.discovery_query_id"
                        " LEFT JOIN edgar_filing f ON f.lead_id = lead.id"
                        " WHERE q.discovery_id = :discovery AND NOT EXISTS ("
                        "  SELECT 1 FROM lead_examination e WHERE e.lead_id = lead.id)"
                        " ORDER BY lead.first_seen_at, lead.id"
                    ),
                    {"discovery": payload.discovery_id},
                )
            ]
        filings = [lead for lead in found if lead.filer_cik is not None]
        leads = [] if payload.filers_only else [lead for lead in found if lead.filer_cik is None]
        counts = {"leads": 0, "mentions": 0, "in_universe": 0, "unresolved": 0, "filings": 0}
        candidates: set[uuid.UUID] = set()
        created: set[uuid.UUID] = set()
        below: list[JsonValue] = []
        if filings:
            below = self._filings(payload.discovery_id, theme, filings, counts, candidates, created)
        run_id: uuid.UUID | None = None
        if leads:
            if self._runs is None or self._caller is None:
                raise MentionExtractorNotConfigured(
                    "the mention extractor needs LiteLLM: set ATLAS_LITELLM_URL and"
                    " ATLAS_LITELLM_API_KEY"
                )
            run_id = self._runs.start(RUN_KIND).id
            try:
                for start in range(0, len(leads), self._per_call):
                    batch = leads[start : start + self._per_call]
                    self._batch(
                        payload.discovery_id, theme, run_id, batch, counts, candidates, created
                    )
            finally:
                with self._engine.connect() as connection:
                    usage = run_usage(connection, run_id)
                self._runs.finish(run_id, tokens_in=usage.tokens_in, tokens_out=usage.tokens_out)
        return {
            "discovery_id": str(payload.discovery_id),
            "run_id": str(run_id) if run_id else None,
            **counts,
            # Filers outside the universe none of whose filing leads ranking keeps: not
            # resolved, not proposed, their leads left unexamined.
            "filers_below_threshold": below,
            "candidates": list[JsonValue](sorted(str(each) for each in candidates)),
            "new_candidates": len(created),
        }

    def _filings(
        self,
        discovery_id: uuid.UUID,
        theme: str,
        filings: Sequence[_Lead],
        counts: dict[str, int],
        candidates: set[uuid.UUID],
        created: set[uuid.UUID],
    ) -> list[JsonValue]:
        """Examine filing leads by their filer's CIK (step 0), one transaction each. Returns
        the filers outside the universe that have no kept hit (their leads not examined)."""
        by_filer: dict[str, list[_Lead]] = {}
        for lead in filings:
            assert lead.filer_cik is not None
            by_filer.setdefault(lead.filer_cik, []).append(lead)
        wanted = {lead.id for lead in filings}
        with self._engine.connect() as connection:
            sightings = discovery_sightings(connection, discovery_id)
            in_universe = {
                cik
                for cik in by_filer
                if find_in_universe(connection, Mention(cik=cik), researched_only=True) is not None
            }
        scores = {
            ranked.lead_id: ranked
            for ranked in rank_leads(
                [each for each in sightings if each.lead_id in wanted],
                companies=self._companies,
                config=self._ranking,
                company_sites=self._company_sites,
            )
        }
        below: list[JsonValue] = []
        for cik, leads in by_filer.items():
            best = max(
                (scores[lead.id] for lead in leads),
                key=lambda ranked: (ranked.score.kept, ranked.score.score),
            )
            if cik not in in_universe and not best.score.kept:
                below.append(_below_threshold(cik, leads, best, self._ranking))
                continue
            mention, resolution = self._resolve_cik(cik)
            for lead in leads:
                with self._engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO lead_examination (lead_id, discovery_id, role_call_id,"
                            " mentions, method) VALUES (:lead, :discovery, NULL, 1, 'filer_cik')"
                        ),
                        {"lead": lead.id, "discovery": discovery_id},
                    )
                    counts["leads"] += 1
                    counts["filings"] += 1
                    counts["mentions"] += 1
                    self._record_mention(
                        connection,
                        theme,
                        lead,
                        1,
                        CompanyMention(name=lead.filer or cik, ticker=lead.ticker, exchange=None),
                        mention,
                        resolution,
                        counts,
                        candidates,
                        created,
                    )
        return below

    def _resolve_cik(self, cik: str) -> tuple[Mention, Resolution]:
        mention = Mention(cik=cik)
        key = (f"cik:{cik}", None, None)
        if key not in self._resolved:
            with self._engine.connect() as connection:
                self._resolved[key] = resolve_mention(
                    connection,
                    self._resolver,
                    mention,
                    ignored_ciks=self._ignored,
                    researched_only=True,
                )
        return mention, self._resolved[key]

    def _batch(
        self,
        discovery_id: uuid.UUID,
        theme: str,
        run_id: uuid.UUID,
        batch: Sequence[_Lead],
        counts: dict[str, int],
        candidates: set[uuid.UUID],
        created: set[uuid.UUID],
    ) -> None:
        ids = [f"lead-{n}" for n in range(1, len(batch) + 1)]
        retrieved = [
            QuotedText(
                id=lead_id, source=lead.canonical_url, text=f"{lead.title}\n\n{lead.snippet}"
            )
            for lead_id, lead in zip(ids, batch, strict=True)
        ]
        request = MentionRequest(theme_id=theme, theme_title=self._theme_title(theme), lead_ids=ids)
        assert self._caller is not None
        answer, role_call_id = self._caller.call_recorded(
            MENTION_EXTRACTOR, request, run_id=run_id, retrieved=retrieved
        )
        by_id: dict[str, list[CompanyMention]] = {}
        for each in answer.leads:
            if each.lead in ids and each.lead not in by_id:  # other ids are ignored
                by_id[each.lead] = list(each.companies)
        # Resolve outside the transaction: the network calls may be slow.
        resolved: list[tuple[_Lead, list[tuple[CompanyMention, Mention, Resolution]]]] = []
        for lead_id, lead in zip(ids, batch, strict=True):
            mentions = _distinct(by_id.get(lead_id, []))
            resolved.append((lead, [(m, *self._resolve(m)) for m in mentions]))
        with self._engine.begin() as connection:
            for lead, mentions in resolved:
                connection.execute(
                    text(
                        "INSERT INTO lead_examination (lead_id, discovery_id, role_call_id,"
                        " mentions) VALUES (:lead, :discovery, :role_call, :mentions)"
                    ),
                    {
                        "lead": lead.id,
                        "discovery": discovery_id,
                        "role_call": role_call_id,
                        "mentions": len(mentions),
                    },
                )
                counts["leads"] += 1
                for position, (said, mention, resolution) in enumerate(mentions, start=1):
                    counts["mentions"] += 1
                    self._record_mention(
                        connection,
                        theme,
                        lead,
                        position,
                        said,
                        mention,
                        resolution,
                        counts,
                        candidates,
                        created,
                    )

    def _record_mention(
        self,
        connection: Connection,
        theme: str,
        lead: _Lead,
        position: int,
        said: CompanyMention,
        mention: Mention,
        resolution: Resolution,
        counts: dict[str, int],
        candidates: set[uuid.UUID],
        created: set[uuid.UUID],
    ) -> None:
        """Record a mention's outcome (steps 2-3), proposing or joining its Candidate."""
        company_id: str | None = resolution.company_id
        candidate_id: uuid.UUID | None = None
        if company_id is not None:
            outcome = "in_universe"
            counts["in_universe"] += 1
        elif resolution.tier == "unresolved":
            outcome = "unresolved"
            counts["unresolved"] += 1
        else:
            outcome = "candidate"
            candidate_id, new = self._candidate(connection, theme, mention, resolution)
            candidates.add(candidate_id)
            if new:
                created.add(candidate_id)
        connection.execute(
            text(
                "INSERT INTO lead_mention (id, lead_id, position, name, ticker,"
                " exchange, mic, outcome, tier, company_id, candidate_id)"
                " VALUES (:id, :lead, :position, :name, :ticker, :exchange, :mic,"
                " :outcome, :tier, :company, :candidate)"
            ),
            {
                "id": uuid.uuid4(),
                "lead": lead.id,
                "position": position,
                "name": said.name,
                "ticker": said.ticker,
                "exchange": said.exchange,
                "mic": mention.mic,
                "outcome": outcome,
                "tier": resolution.tier,
                "company": company_id,
                "candidate": candidate_id,
            },
        )

    def _resolve(self, said: CompanyMention) -> tuple[Mention, Resolution]:
        ticker = (said.ticker or "").strip() or None
        mic = exchange_mic(said.exchange) if ticker else None
        mention = Mention(name=said.name.strip() or None, ticker=ticker, mic=mic)
        key = (normalize_name(said.name), ticker, mic)
        if key not in self._resolved:
            with self._engine.connect() as connection:
                self._resolved[key] = resolve_mention(
                    connection,
                    self._resolver,
                    mention,
                    ignored_ciks=self._ignored,
                    researched_only=True,
                )
        return mention, self._resolved[key]

    def _candidate(
        self, connection: Connection, theme: str, mention: Mention, resolution: Resolution
    ) -> tuple[uuid.UUID, bool]:
        """The Candidate for this unseeded match in `theme`, and whether it is new."""
        identity = _identity(resolution, mention)
        fields: dict[str, Any] = {
            "id": uuid.uuid4(),
            "theme": theme,
            "key": identity.key,
            "name": identity.name,
            "cik": identity.cik,
            "lei": identity.lei,
            "country": identity.country,
            "tier": resolution.tier,
            "source_path": "sec" if identity.cik else None,
            "resolution": resolution.model_dump(mode="json"),
        }
        row = connection.execute(
            text(
                "INSERT INTO candidate (id, theme, identity_key, name, cik, lei, country, tier,"
                " source_path, resolution) VALUES (:id, :theme, :key, :name, :cik, :lei,"
                " :country, :tier, :source_path, :resolution)"
                " ON CONFLICT (theme, identity_key) DO NOTHING RETURNING id"
            ).bindparams(bindparam("resolution", type_=JSONB)),
            fields,
        ).one_or_none()
        if row is None:
            existing = connection.execute(
                text("SELECT id FROM candidate WHERE theme = :theme AND identity_key = :key"),
                {"theme": theme, "key": identity.key},
            ).scalar_one()
            return existing, False
        record(
            connection,
            self._actor,
            "candidate.proposed",
            entity_type="candidate",
            entity_id=str(row.id),
            new_hash=content_hash({k: v for k, v in fields.items() if k != "resolution"}),
        )
        return row.id, True


def _below_threshold(
    cik: str, leads: Sequence[_Lead], best: RankedLead, ranking: RankingConfig
) -> JsonValue:
    """A filer with no kept hit, for the job's artifacts: its best-scoring filing lead."""
    return {
        "cik": cik,
        "filer": next((lead.filer for lead in leads if lead.filer), None),
        "leads": len(leads),
        "score": best.score.score,
        "min_score": ranking.min_score,
        "query": best.query,
        "reasons": list[JsonValue](best.score.reasons),
    }


def _distinct(mentions: list[CompanyMention]) -> list[CompanyMention]:
    """Each company once per lead (by normalized name and ticker), blank names dropped."""
    seen: set[tuple[str, str | None]] = set()
    kept: list[CompanyMention] = []
    for each in mentions:
        key = (normalize_name(each.name), (each.ticker or "").strip().upper() or None)
        if key[0] and key not in seen:
            seen.add(key)
            kept.append(each)
    return kept
