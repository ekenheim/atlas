"""Running one investigation task (an `investigation_task` job): the role's work, then the
task's outcome and the next step of the plan (atlas.investigations.service).

One attempt:

1. **Start.** Under the investigation's lock: a task that isn't queued for this job (it was
   cancelled, or the investigation stopped) does nothing. Otherwise it is marked running
   (`task_started`, or `task_resumed` after a pause). The investigation's run (kind
   `investigation`) is started by the first task that needs it.
2. **The role**, within the investigation's run and token budget:
   - **Scout:** a discovery (atlas.discovery) in the run, its EDGAR full-text searches (when
     on) over the 18 months before the investigation's `as_of`; the leads its queries
     returned are ranked for relevance to their query and its purpose (an EDGAR filing hit
     too, by the phrase it matched) (atlas.discovery.ranking), and the top-ranked ones kept
     up to the lead budget, each with its score and reasons (the rest counted as dropped; those
     ranking says not to keep, from a denied host or below the minimum score, counted as
     rejected). With entity resolution configured, its filing leads' filers are then
     proposed as Candidates by CIK (`propose_candidates` with `filers_only`: no LLM call).
     Once the discovery has its queries, the round's question and each query are asked of
     Memory across the theme, and what resolves is stored as the round's **reading
     pointers** (atlas.investigations.pointers): Memory as an index of where to read, never
     sent to a role. The Investigators' passages are chosen by them.
   - **Investigator** (one per seed company): the company's latest parsed Source Versions
     available at the investigation's as-of time, newest first, up to its share of what is
     left of the document budget (an equal share is held back for each of the round's other
     Investigators that hasn't chosen yet, so unused share passes on in plan order); then an
     extraction (atlas.claims) of them in the run, within `investigation_max_passages`
     passages chosen across those documents (atlas.claims.selection) by two channels in
     turn: the windows the round's reading pointers lead to (by rank), and the windows a term
     search ranks highest for the round's question and the Scout's queries with the
     entity-tagged ones (by score), so a document Memory doesn't hold yet is still read;
     with a floor for periodic reports, results releases and results-call transcripts and a
     ceiling per document. It makes no recall of its own. A resumed task continues its
     budget-exhausted extraction.
   - **Skeptic** (atlas.investigations.skeptic): skipped without an LLM call when the
     Investigators accepted no Claim (nothing to challenge); otherwise its own plan, SearXNG
     queries and reading of the Source Versions it chose (and, for a seed company its plan
     chose nothing of, the ones code chooses: the fallback), for counterevidence: each
     accepted item a contradiction of a named Claim or bear context about a company. An
     accepted, independent contradiction may disprove a company premise, applied when the
     task is recorded (by `atlas-skeptic`), which cancels only what depends on it.
   - **Financial Analyst:** the seed companies the accepted Claims name, with their as-of
     XBRL figures, and the Claims; with none it is skipped without an LLM call. One call
     proposes scenario inputs; code keeps only the inputs whose source or basis stands
     (atlas.scenarios.analyst) and records the assumption tables in the task's artifacts,
     for scenarios on the Hypothesis versions (atlas.scenarios).
   - **Editor:** the investigation's accepted Claims (excluding those from a task whose
     premise was disproven). When there are accepted Claims but no new independent Evidence
     (no Evidence Family that an earlier round's Claims hadn't used) it is skipped without an
     LLM call, and the earlier card stands. Otherwise one Editor call drafts the research
     card, sent the Skeptic's accepted contradictions and bear context (separately) and what
     was searched and read too; code keeps only findings citing accepted Claims and fills in
     their spans, the independent contradictions of each cited Claim (`counterevidence_ids`),
     the card's `contradictions`, its `bear_context` (by checklist item and company) and its
     `searched` and `read` sections (atlas.investigations.coverage). A finding contradicted
     by an independent contradiction needs review, and so does the investigation
     (atlas.roles.editor); bear context marks no finding and stops nothing. With no accepted
     Claim at all the card has no finding, only what was searched and read and the open
     questions for the next round, and the investigation stops
     `no_new_independent_evidence` as before.
3. **Outcome.** Under the lock, the task's outcome is recorded and the plan advanced. When
   the run's token budget runs out, the task and the investigation stop `budget_exhausted`
   (resumable). An LLM quota or outage (a pausable failure) records `task_paused` and
   re-raises, so the worker pauses the queue and requeues the job; nothing is written for
   the role. Any other failure is retried; on the job's last attempt the task fails and the
   investigation stops `needs_review`.
"""

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import JsonValue
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.candidates.proposals import PROPOSE_CANDIDATES_KIND
from atlas.claims.extraction import ExtractClaimsPayload
from atlas.claims.handlers import claim_extractor
from atlas.companies import Universe, load_universe
from atlas.discovery.edgar_fts import EdgarFullTextSearch
from atlas.discovery.leads import discovery_sightings
from atlas.discovery.ranking import (
    RankingConfig,
    load_ranking_config,
    rank_leads,
    site_host,
)
from atlas.discovery.searxng import SearXNGClient
from atlas.discovery.service import Scout
from atlas.financials import load_metric_catalog
from atlas.hindsight import HindsightGateway
from atlas.investigations.coverage import coverage
from atlas.investigations.model import (
    RUN_KIND,
    CardBearContext,
    CardContradiction,
    CardFinding,
    ResearchCard,
    SourceSpan,
    UnsupportedFinding,
    ValidityDates,
)
from atlas.investigations.pointers import (
    SCOUT_ACTOR,
    Recall,
    record_pointers,
    round_reading,
    scout_queries,
)
from atlas.investigations.service import Investigations, event, lock, round_question, stop
from atlas.investigations.skeptic import (
    SKEPTIC_ACTOR,
    Disproof,
    Skeptic,
    bear_context,
    contradictions,
    counterevidence_by_claim,
)
from atlas.jobs.pacing import classify_failure
from atlas.jobs.queue import Artifacts, Job, JobQueue
from atlas.jobs.resources import run_recorder
from atlas.research.service import RecallRequest, Research, ResearchScope
from atlas.roles import QuotedText, RoleCaller, RoleCallFailed, TokenBudgetExhausted
from atlas.roles.editor import (
    EDITOR,
    EditorBearContext,
    EditorClaim,
    EditorContradiction,
    EditorCounterevidence,
    EditorDocumentRead,
    EditorLead,
    EditorQuery,
    EditorReading,
    EditorRequest,
)
from atlas.roles.financial_analyst import FINANCIAL_ANALYST
from atlas.runs import RunRecorder
from atlas.scenarios.analyst import analyst_companies, analyst_context, keep_proposals
from atlas.settings import Settings

_ERROR_LIMIT = 500


class InvestigationNotConfigured(RuntimeError):
    """A provider an investigation needs (LiteLLM, Hindsight, SearXNG) isn't configured."""


class UnknownInvestigationTheme(LookupError):
    """The investigation's theme is no longer in the universe config."""


@dataclass
class _Outcome:
    status: Literal["succeeded", "skipped", "budget_exhausted"]
    detail: str | None = None
    artifacts: dict[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    card: ResearchCard | None = None
    disproofs: list[Disproof] = field(default_factory=list[Disproof])


class TaskRunner:
    """Runs investigation tasks with the given resources (owned by the caller)."""

    def __init__(self, settings: Settings, engine: Engine, gateway: HindsightGateway) -> None:
        self._settings = settings
        self._engine = engine
        self._gateway = gateway
        self._investigations = Investigations(engine, JobQueue(engine))

    def run(self, job: Job) -> Artifacts:
        task_id = uuid.UUID(str(job.payload["task_id"]))
        with self._engine.begin() as connection:
            task = _task(connection, task_id)
            investigation = lock(connection, task["investigation_id"])
            task = _task(connection, task_id, for_update=True)
            if (
                investigation["status"] != "running"
                or task["status"] not in ("queued", "running")
                or task["job_id"] != job.id
            ):
                return {"task_id": str(task_id), "status": task["status"], "ran": False}
            self._start(connection, investigation, task)
        try:
            run_id = self._ensure_run(investigation["id"])
            with self._engine.connect() as connection:
                investigation = (
                    connection.execute(
                        text("SELECT * FROM investigation WHERE id = :id"),
                        {"id": investigation["id"]},
                    )
                    .mappings()
                    .one()
                )
            outcome = self._role(job, investigation, task, run_id)
        except TokenBudgetExhausted as error:
            outcome = _Outcome("budget_exhausted", detail=_budget_detail(task["role"], error))
        except Exception as error:
            self._failed(job, investigation["id"], task, error)
            raise
        with self._engine.begin() as connection:
            self._finish(connection, investigation["id"], task_id, job, outcome)
        return {
            "task_id": str(task_id),
            "investigation_id": str(investigation["id"]),
            "status": outcome.status,
            "ran": True,
            **outcome.artifacts,
        }

    # --- start and finish -------------------------------------------------------------------

    def _start(self, connection: Connection, investigation: RowMapping, task: RowMapping) -> None:
        last = connection.execute(
            text(
                "SELECT type FROM investigation_event WHERE investigation_id = :id"
                " AND task_key = :key AND round = :round ORDER BY seq DESC LIMIT 1"
            ),
            {"id": investigation["id"], "key": task["key"], "round": task["round"]},
        ).scalar_one_or_none()
        connection.execute(
            text(
                "UPDATE investigation_task SET status = 'running', updated_at = now()"
                " WHERE id = :id"
            ),
            {"id": task["id"]},
        )
        event(
            connection,
            investigation["id"],
            "task_resumed" if last == "task_paused" else "task_started",
            round=task["round"],
            task_key=task["key"],
            generation=task["generation"],
        )

    def _ensure_run(self, investigation_id: uuid.UUID) -> uuid.UUID:
        with self._engine.connect() as connection:
            run_id: uuid.UUID | None = connection.execute(
                text("SELECT run_id FROM investigation WHERE id = :id"), {"id": investigation_id}
            ).scalar_one()
        if run_id is not None:
            return run_id
        with run_recorder(self._settings, self._engine) as runs:
            if runs is None:
                raise InvestigationNotConfigured(
                    "an investigation records a run: it needs LiteLLM (ATLAS_LITELLM_URL,"
                    " ATLAS_LITELLM_API_KEY) and Hindsight configured"
                )
            run = runs.start(RUN_KIND)
        with self._engine.begin() as connection:
            lock(connection, investigation_id)
            started: uuid.UUID = connection.execute(
                text(
                    "UPDATE investigation SET run_id = coalesce(run_id, :run) WHERE id = :id"
                    " RETURNING run_id"
                ),
                {"id": investigation_id, "run": run.id},
            ).scalar_one()
            if started == run.id:
                event(connection, investigation_id, "run_started", run_id=str(run.id))
        return started

    def _finish(
        self,
        connection: Connection,
        investigation_id: uuid.UUID,
        task_id: uuid.UUID,
        job: Job,
        outcome: _Outcome,
    ) -> None:
        investigation = lock(connection, investigation_id)
        task = _task(connection, task_id, for_update=True)
        if task["status"] != "running" or task["job_id"] != job.id:
            return  # recorded by an earlier attempt
        connection.execute(
            text(
                "UPDATE investigation_task SET status = :status, detail = :detail,"
                " artifacts = artifacts || CAST(:artifacts AS jsonb), updated_at = now()"
                " WHERE id = :id"
            ),
            {
                "id": task_id,
                "status": outcome.status,
                "detail": outcome.detail,
                "artifacts": _json(outcome.artifacts),
            },
        )
        detail: dict[str, JsonValue] = {"generation": task["generation"], **outcome.artifacts}
        if outcome.detail:
            detail["reason"] = outcome.detail
        event(
            connection,
            investigation_id,
            f"task_{outcome.status}",
            round=task["round"],
            task_key=task["key"],
            **detail,
        )
        if outcome.card is not None:
            connection.execute(
                text(
                    "UPDATE investigation SET research_card = CAST(:card AS jsonb) WHERE id = :id"
                ),
                {"id": investigation_id, "card": outcome.card.model_dump_json()},
            )
        if investigation["status"] != "running":
            return
        for disproof in outcome.disproofs:
            premise = connection.execute(
                text(
                    "SELECT status FROM investigation_premise"
                    " WHERE investigation_id = :id AND key = :key"
                ),
                {"id": investigation_id, "key": disproof.premise_key},
            ).scalar_one_or_none()
            if premise == "open":
                self._investigations.disprove_within(
                    connection,
                    SKEPTIC_ACTOR,
                    investigation_id,
                    disproof.premise_key,
                    disproof.reason,
                    counterevidence_ids=[str(each) for each in disproof.counterevidence_ids],
                )
        if outcome.status == "budget_exhausted":
            stop(connection, investigation_id, "budget_exhausted", outcome.detail or "")
        else:
            self._investigations.advance(connection, investigation_id)

    def _failed(
        self, job: Job, investigation_id: uuid.UUID, task: RowMapping, error: Exception
    ) -> None:
        message = f"{type(error).__name__}: {error}"[:_ERROR_LIMIT]
        failure_class = classify_failure(error)
        with self._engine.begin() as connection:
            lock(connection, investigation_id)
            where = {"round": task["round"], "task_key": task["key"]}
            if failure_class is not None:
                # The worker pauses the queue and requeues the job without using the attempt.
                _set_status(connection, task["id"], "queued")
                event(
                    connection,
                    investigation_id,
                    "task_paused",
                    **where,
                    error_class=failure_class,
                    error=message,
                )
                return
            if job.attempts < job.max_attempts:
                _set_status(connection, task["id"], "queued")
                event(
                    connection,
                    investigation_id,
                    "task_attempt_failed",
                    **where,
                    attempt=job.attempts,
                    error=message,
                )
                return
            _set_status(connection, task["id"], "failed", detail=message)
            event(connection, investigation_id, "task_failed", **where, error=message)
            stop(
                connection,
                investigation_id,
                "needs_review",
                f"the {task['key']} task failed after {job.attempts} attempts: {message}",
            )

    # --- the roles --------------------------------------------------------------------------

    def _role(
        self, job: Job, investigation: RowMapping, task: RowMapping, run_id: uuid.UUID
    ) -> _Outcome:
        role: str = task["role"]
        if role == "scout":
            return self._scout(job, investigation, task, run_id)
        if role == "investigator":
            return self._investigator(job, investigation, task, run_id)
        if role == "skeptic":
            return self._skeptic(investigation, task, run_id)
        if role == "financial_analyst":
            return self._financial_analyst(investigation, run_id)
        if role == "editor":
            return self._editor(investigation, task, run_id)
        raise RoleCallFailed(f"the {role} role is not built yet")

    def _caller(self, investigation: RowMapping) -> RoleCaller:
        settings = self._settings.model_copy(
            update={"run_token_budget": investigation["token_budget"]}
        )
        caller = RoleCaller.from_settings(settings, self._engine)
        if caller is None:
            raise InvestigationNotConfigured(
                "an investigation's roles need LiteLLM: set ATLAS_LITELLM_URL and"
                " ATLAS_LITELLM_API_KEY"
            )
        return caller

    def _runs(self) -> RunRecorder:
        runs = RunRecorder.from_settings(self._settings, self._engine)
        if runs is None:
            raise InvestigationNotConfigured("an investigation needs LiteLLM and Hindsight")
        return runs

    def _question(self, investigation: RowMapping, task: RowMapping) -> str:
        """The question the task's round pursues (a follow-up round's open question)."""
        with self._engine.connect() as connection:
            return round_question(connection, investigation, task["round"])

    def _scout(
        self, job: Job, investigation: RowMapping, task: RowMapping, run_id: uuid.UUID
    ) -> _Outcome:
        theme_id: str = investigation["theme"]
        universe = load_universe(self._settings.themes_config)
        ranking = load_ranking_config(self._settings.lead_ranking_config)
        theme = universe.themes.get(theme_id)
        if theme is None:
            raise UnknownInvestigationTheme(f"no theme {theme_id!r} in the universe config")
        searxng = SearXNGClient.from_settings(self._settings)
        if searxng is None:
            raise InvestigationNotConfigured("the Scout needs SearXNG: set ATLAS_SEARXNG_URL")
        runs = self._runs()
        edgar = EdgarFullTextSearch.from_settings(self._settings)
        question = self._question(investigation, task)
        with searxng, self._caller(investigation) as caller:
            try:
                scout = Scout(
                    self._engine,
                    runs,
                    caller,
                    self._gateway,
                    searxng,
                    max_queries=self._settings.discovery_max_queries,
                    edgar=edgar,
                )
                found = scout.discover(
                    job,
                    theme_id,
                    theme,
                    question,
                    run_id=run_id,
                    as_of=investigation["as_of"],
                )
            finally:
                runs.close()
        discovery_id = uuid.UUID(str(found["discovery_id"]))
        # Before the leads are taken: a Hindsight outage here pauses the task, and the
        # attempt that resumes it takes the leads once.
        with self._engine.connect() as connection:
            queries = scout_queries(connection, discovery_id, question)
        pointers = record_pointers(
            self._engine, self._theme_recall(theme_id, universe), investigation, task, queries
        )
        with self._engine.begin() as connection:
            lock(connection, investigation["id"])
            taken, dropped, rejected, total = _take_leads(
                connection,
                investigation["id"],
                discovery_id,
                investigation["max_leads"],
                companies=_company_names(universe),
                company_sites=_company_sites(universe),
                ranking=ranking,
            )
            if dropped:
                event(
                    connection,
                    investigation["id"],
                    "lead_budget_reached",
                    round=investigation["round"],
                    task_key="scout",
                    max_leads=investigation["max_leads"],
                    dropped=dropped,
                )
        artifacts: dict[str, JsonValue] = dict(pointers)
        if edgar is not None and self._settings.sec_user_agent:
            # The filing leads' filers, by CIK (no mention extractor): Candidates for the
            # ones outside the universe (atlas.candidates).
            enqueued = JobQueue(self._engine, actor=Actor.from_settings(self._settings)).enqueue(
                PROPOSE_CANDIDATES_KIND,
                f"discovery:{discovery_id}",
                {"discovery_id": str(discovery_id), "filers_only": True},
                job_class=job.job_class,
            )
            artifacts["propose_candidates_job_id"] = str(enqueued.job.id)
        return _Outcome(
            "succeeded",
            artifacts=artifacts
            | {
                "discovery_id": str(discovery_id),
                "queries": found["queries"],
                "filing_searches": found["filing_searches"],
                "filing_searches_skipped": found["filing_searches_skipped"],
                "leads_found": total,
                "leads_taken": taken,
                "leads_dropped": dropped,
                "leads_rejected": rejected,
                "ranking_version": ranking.version,
            },
        )

    def _theme_recall(self, theme_id: str, universe: Universe) -> Recall:
        """Recall across the theme: every memory tagged with it, whichever company's."""
        research = Research(
            self._engine, open_archive(self._settings), self._gateway, SCOUT_ACTOR, lambda: universe
        )
        scope = ResearchScope(theme_ids=[theme_id])
        return lambda query: research.recall(RecallRequest(query=query, scope=scope))

    def _investigator(
        self, job: Job, investigation: RowMapping, task: RowMapping, run_id: uuid.UUID
    ) -> _Outcome:
        documents, dropped = self._documents(investigation, task)
        if not documents:
            return _Outcome(
                "succeeded",
                detail=(
                    "the document budget is spent"
                    if dropped
                    else "no parsed Source Version of the company is available as of"
                    f" {investigation['as_of'].isoformat()}"
                    + (" that an earlier round hasn't read" if task["round"] > 1 else "")
                ),
                artifacts={"documents": 0, "documents_dropped": dropped},
            )
        artifacts: dict[str, Any] = task["artifacts"]
        continues = (
            uuid.UUID(str(artifacts["extraction_id"]))
            if task["generation"] > 0 and artifacts.get("extraction_status") == "budget_exhausted"
            else None
        )
        payload = ExtractClaimsPayload(
            source_version_ids=documents,
            question=self._question(investigation, task),
            run_id=run_id,
            continues=continues,
        )
        # Where Memory pointed in these documents, and the Scout's queries: they choose the
        # passages (atlas.claims.selection); neither is sent to the Investigator.
        with self._engine.connect() as connection:
            reading = round_reading(connection, investigation["id"], task["round"], documents)
        with (
            self._caller(investigation) as caller,
            # The run is the investigation's, so the extractor never starts or finishes one.
            claim_extractor(
                self._settings,
                self._engine,
                caller,
                None,
                max_passages=self._settings.investigation_max_passages,
            ) as extractor,
        ):
            extracted = extractor.extract(job, payload, reading)
        result: dict[str, JsonValue] = {
            "documents": len(documents),
            "documents_dropped": dropped,
            "extraction_id": extracted["extraction_id"],
            "extraction_status": extracted["status"],
            "passages": extracted["passages"],
            "passages_by_document": extracted["passages_by_document"],
            "passages_by_selection": extracted["passages_by_selection"],
            "accepted": extracted["accepted"],
            "rejected": extracted["rejected"],
        }
        if extracted["status"] == "budget_exhausted":
            return _Outcome(
                "budget_exhausted",
                detail="the run's token budget ran out during the Investigator's extraction",
                artifacts=result,
            )
        return _Outcome("succeeded", artifacts=result)

    def _documents(
        self, investigation: RowMapping, task: RowMapping
    ) -> tuple[list[uuid.UUID], int]:
        """The task's Source Versions (chosen once, within the document budget); and how many
        available ones the budget left out."""
        with self._engine.begin() as connection:
            lock(connection, investigation["id"])
            chosen = list(
                connection.execute(
                    text("SELECT source_version_id FROM investigation_document WHERE task_id = :t"),
                    {"t": task["id"]},
                ).scalars()
            )
            if chosen or task["artifacts"].get("documents") is not None:
                return chosen, int(task["artifacts"].get("documents_dropped") or 0)
            used = connection.execute(
                text("SELECT count(*) FROM investigation_document WHERE investigation_id = :id"),
                {"id": investigation["id"]},
            ).scalar_one()
            available = list(
                connection.execute(
                    text(
                        "SELECT id FROM (SELECT DISTINCT ON (v.source_document_id) v.id,"
                        " v.available_at FROM source_version v"
                        " JOIN source_document d ON d.id = v.source_document_id"
                        " WHERE d.company_id = :company AND v.available_at <= :as_of"
                        " AND v.parse_status IN ('parsed', 'incomplete')"
                        " AND v.parsed_object_uri IS NOT NULL"
                        " ORDER BY v.source_document_id, v.available_at DESC, v.id) latest"
                        # An earlier round's (or another task's) reading isn't repeated.
                        " WHERE NOT EXISTS (SELECT FROM investigation_document r"
                        "  WHERE r.investigation_id = :id AND r.source_version_id = latest.id)"
                        " ORDER BY available_at DESC, id"
                    ),
                    {
                        "company": task["company_id"],
                        "as_of": investigation["as_of"],
                        "id": investigation["id"],
                    },
                ).scalars()
            )
            room = _document_share(
                connection, investigation, task, max(investigation["max_documents"] - int(used), 0)
            )
            chosen, dropped = available[:room], max(len(available) - room, 0)
            for version_id in chosen:
                connection.execute(
                    text(
                        "INSERT INTO investigation_document (investigation_id, source_version_id,"
                        " task_id) VALUES (:id, :version, :task)"
                    ),
                    {"id": investigation["id"], "version": version_id, "task": task["id"]},
                )
            # Recorded now, so a sibling Investigator choosing later sees this task has chosen.
            connection.execute(
                text(
                    "UPDATE investigation_task SET artifacts = artifacts"
                    " || jsonb_build_object('documents', CAST(:n AS integer),"
                    " 'documents_dropped', CAST(:dropped AS integer)) WHERE id = :id"
                ),
                {"id": task["id"], "n": len(chosen), "dropped": dropped},
            )
            if dropped:
                event(
                    connection,
                    investigation["id"],
                    "document_budget_reached",
                    round=task["round"],
                    task_key=task["key"],
                    max_documents=investigation["max_documents"],
                    dropped=dropped,
                )
            return chosen, dropped

    def _skeptic(self, investigation: RowMapping, task: RowMapping, run_id: uuid.UUID) -> _Outcome:
        theme = load_universe(self._settings.themes_config).themes.get(investigation["theme"])
        with self._engine.connect() as connection:
            claims = accepted_claims(connection, investigation["id"], run_id)
            theme_companies = list(
                connection.execute(
                    text("SELECT id FROM company WHERE slug = ANY(:slugs) ORDER BY slug"),
                    {"slugs": list(theme.companies) if theme else []},
                ).scalars()
            )
        if not claims:
            return _Outcome(
                "skipped",
                detail="nothing to challenge: the Investigators accepted no Claim",
                artifacts={"supporting_claims": 0},
            )
        company_ids = list(
            dict.fromkeys(
                [
                    *investigation["seed_company_ids"],
                    *(c["object_company_id"] for c in claims if c["object_company_id"]),
                    *theme_companies,
                ]
            )
        )
        searxng = SearXNGClient.from_settings(self._settings)
        if searxng is None:
            raise InvestigationNotConfigured("the Skeptic needs SearXNG: set ATLAS_SEARXNG_URL")
        with searxng, self._caller(investigation) as caller:
            skeptic = Skeptic(
                self._engine,
                open_archive(self._settings),
                caller,
                searxng,
                max_queries=self._settings.discovery_max_queries,
                max_passages=self._settings.investigator_max_passages,
                passages_per_call=self._settings.investigator_passages_per_call,
                edgar=EdgarFullTextSearch.from_settings(self._settings),
            )
            found = skeptic.run(
                investigation,
                task,
                run_id,
                theme_title=theme.title if theme else investigation["theme"],
                company_ids=company_ids,
                theme_company_ids=theme_companies,
                claims=claims,
                supporting_families={_family(c) for c in claims},
            )
        return _Outcome(
            found.status,
            detail=found.detail,
            artifacts={"supporting_claims": len(claims), **found.artifacts},
            disproofs=found.disproofs,
        )

    def _financial_analyst(self, investigation: RowMapping, run_id: uuid.UUID) -> _Outcome:
        with self._engine.connect() as connection:
            claims = accepted_claims(connection, investigation["id"], run_id)
            companies = analyst_companies(connection, investigation["seed_company_ids"], claims)
            if not companies:
                return _Outcome(
                    "skipped",
                    detail=(
                        "nothing to quantify: the Investigators accepted no Claims"
                        if not claims
                        else "nothing to quantify: no accepted Claim names a seed company"
                    ),
                    artifacts={"claims": len(claims), "companies": 0},
                )
            context = analyst_context(
                connection,
                theme_id=investigation["theme"],
                question=investigation["question"],
                as_of=investigation["as_of"],
                companies=companies,
                claims=claims,
                catalog=load_metric_catalog(self._settings.financial_metrics_config),
            )
        with self._caller(investigation) as caller:
            proposal, role_call_id = caller.call_recorded(
                FINANCIAL_ANALYST, context.request, run_id=run_id, retrieved=context.retrieved
            )
        with self._engine.connect() as connection:
            kept = keep_proposals(connection, context, proposal, investigation["as_of"])
        return _Outcome(
            "succeeded",
            artifacts={
                "role_call_id": str(role_call_id),
                "claims": len(claims),
                "companies": len(companies),
                "scenario_proposals": [table.canonical() for table in kept.tables],
                "rejected_inputs": list[JsonValue](kept.rejected),
            },
        )

    def _editor(self, investigation: RowMapping, task: RowMapping, run_id: uuid.UUID) -> _Outcome:
        with self._engine.connect() as connection:
            claims = accepted_claims(connection, investigation["id"], run_id)
            against = contradictions(connection, investigation["id"])
            context = bear_context(connection, investigation["id"])
            sent, quoted = counterevidence_for_editors(connection, against)
            context_sent, context_quoted = bear_context_for_editor(connection, context)
            leads = connection.execute(
                text(
                    "SELECT l.id, l.url, l.title, l.snippet FROM investigation_lead il"
                    " JOIN lead l ON l.id = il.lead_id WHERE il.investigation_id = :id"
                    " ORDER BY il.rank"
                ),
                {"id": investigation["id"]},
            ).all()
            disproven = list(
                connection.execute(
                    text(
                        "SELECT statement FROM investigation_premise"
                        " WHERE investigation_id = :id AND status = 'disproven' ORDER BY key"
                    ),
                    {"id": investigation["id"]},
                ).scalars()
            )
            searched, read = coverage(connection, investigation["id"])
        round_ = task["round"]
        earlier = {_family(c) for c in claims if c["round"] < round_}
        new_families = sorted({_family(c) for c in claims if c["round"] == round_} - earlier)
        if claims and not new_families:
            # A follow-up round that found nothing new: the earlier round's card stands.
            return _Outcome(
                "skipped",
                detail="no new independent Evidence: every accepted Claim's Evidence Family"
                " was already used",
                artifacts={"claims": len(claims), "new_evidence_families": 0},
            )
        theme = load_universe(self._settings.themes_config).themes.get(investigation["theme"])
        request = EditorRequest(
            theme_id=investigation["theme"],
            theme_title=theme.title if theme else investigation["theme"],
            research_question=investigation["question"],
            claims=[
                EditorClaim(
                    claim_id=str(c["id"]),
                    subject=c["subject_name"],
                    predicate=c["predicate"],
                    object=c["object_name"] or c["object_text"] or "",
                    product=c["product"],
                    layer=c["layer"],
                    epistemic_type=c["epistemic_type"],
                    source_title=c["source_title"],
                    source_version_id=str(c["source_version_id"]),
                )
                for c in claims
            ],
            leads=[
                EditorLead(lead_id=str(lead.id), title=lead.title, url=lead.url) for lead in leads
            ],
            contradictions=[
                EditorContradiction(**each.model_dump(), how=found.how)
                for each, found in zip(sent, against, strict=True)
            ],
            bear_context=context_sent,
            disproven_premises=disproven,
            queries=[
                EditorQuery(query=query.query, purpose=query.purpose)
                for search in searched
                for query in search.queries
            ],
            read=[
                EditorReading(
                    company=reading.company_name or reading.task_key,
                    documents=[
                        EditorDocumentRead(title=document.title, sections=document.sections)
                        for document in reading.documents
                    ],
                    documents_dropped=reading.documents_dropped,
                    passages=reading.passages,
                    claims_proposed=reading.claims_proposed,
                    claims_accepted=reading.claims_accepted,
                    rejected=reading.rejected,
                    detail=reading.detail,
                )
                for reading in read
                # The Skeptic's reading reaches the Editor as its contradictions and bear
                # context.
                if reading.role == "investigator"
            ],
        )
        retrieved = (
            [
                QuotedText(
                    id=str(c["id"]),
                    source=f"{c['source_version_id']}#{c['span_start']}-{c['span_end']}",
                    text=c["quote"],
                )
                for c in claims
            ]
            + [
                QuotedText(id=str(lead.id), source=lead.url, text=f"{lead.title}\n{lead.snippet}")
                for lead in leads
            ]
            + quoted
            + context_quoted
        )
        by_claim = counterevidence_by_claim(against)
        with self._caller(investigation) as caller:
            draft, role_call_id = caller.call_recorded(
                EDITOR, request, run_id=run_id, retrieved=retrieved
            )
        by_id = {str(c["id"]): c for c in claims}
        findings: list[CardFinding] = []
        unsupported: list[UnsupportedFinding] = []
        for finding in draft.findings:
            cited = list(dict.fromkeys(finding.claim_ids))
            unknown = [each for each in cited if each not in by_id]
            if not cited or unknown:
                reason = (
                    "cites no Claim"
                    if not cited
                    else "cites what isn't an accepted Claim of this investigation: "
                    + ", ".join(unknown)
                )
                unsupported.append(
                    UnsupportedFinding(
                        statement=finding.statement, claim_ids=finding.claim_ids, reason=reason
                    )
                )
                continue
            findings.append(
                card_finding(finding.statement, [by_id[each] for each in cited], finding, by_claim)
            )
        contradicted = sum(1 for f in findings if f.counterevidence_ids)
        if not claims:
            # The card reports what was searched and read; the stop reason is as before.
            stop_reason = "no_new_independent_evidence"
            stop_detail = "no new independent Evidence: the Investigator accepted no Claims"
        elif draft.verdict == "answered" and findings and not unsupported and not contradicted:
            stop_reason = "answered"
            stop_detail = f"the Editor judged the question answered by {len(findings)} findings"
        else:
            stop_reason = "needs_review"
            problems: list[str] = []
            if unsupported:
                problems.append(f"{len(unsupported)} unsupported findings were dropped")
            if contradicted:
                problems.append(
                    f"{contradicted} findings are contradicted by independent counterevidence"
                )
            if not findings:
                problems.append("no finding cites an accepted Claim")
            if draft.verdict != "answered":
                problems.append("the Editor asks for review")
            stop_detail = "; ".join(problems)
        card = ResearchCard(
            status="draft",
            question=investigation["question"],
            findings=findings,
            open_questions=draft.open_questions,
            unsupported_findings=unsupported,
            editor_verdict=draft.verdict,
            claims_considered=len(claims),
            lead_ids=[lead.id for lead in leads],
            disproven_premises=disproven,
            editor_role_call_id=role_call_id,
            contradictions=against,
            bear_context=context,
            searched=searched,
            read=read,
        )
        return _Outcome(
            "succeeded",
            artifacts={
                "role_call_id": str(role_call_id),
                "claims": len(claims),
                "new_evidence_families": len(new_families),
                "findings": len(findings),
                "unsupported_findings": len(unsupported),
                "contradictions": len(against),
                "bear_context": sum(len(group.items) for group in context),
                "contradicted_findings": contradicted,
                "stop_reason": stop_reason,
                "stop_detail": stop_detail,
            },
            card=card,
        )


# --- helpers ------------------------------------------------------------------------------------


def _document_share(
    connection: Connection, investigation: RowMapping, task: RowMapping, left: int
) -> int:
    """How many of the `left` documents of the budget this Investigator task may read: an
    equal share is held back for each of the round's other Investigator tasks that hasn't
    chosen its documents yet (the remainder of the split going to the earlier ones in plan
    order), so a task's unused share passes on to the tasks that choose after it."""
    waiting = connection.execute(
        text(
            "SELECT count(*) FROM investigation_task WHERE investigation_id = :id"
            " AND round = :round AND role = 'investigator' AND id <> :task"
            " AND status IN ('pending', 'queued', 'running')"
            " AND artifacts -> 'documents' IS NULL"
        ),
        {"id": investigation["id"], "round": task["round"], "task": task["id"]},
    ).scalar_one()
    return left - int(waiting) * (left // (int(waiting) + 1))


def _task(connection: Connection, task_id: uuid.UUID, *, for_update: bool = False) -> RowMapping:
    suffix = " FOR UPDATE" if for_update else ""
    return (
        connection.execute(
            text(f"SELECT * FROM investigation_task WHERE id = :id{suffix}"),  # noqa: S608 (constant)
            {"id": task_id},
        )
        .mappings()
        .one()
    )


def _set_status(
    connection: Connection, task_id: uuid.UUID, status: str, *, detail: str | None = None
) -> None:
    connection.execute(
        text(
            "UPDATE investigation_task SET status = :status, detail = coalesce(:detail, detail),"
            " updated_at = now() WHERE id = :id"
        ),
        {"id": task_id, "status": status, "detail": detail},
    )


def _company_names(universe: Universe) -> list[str]:
    """The universe's company names, display and legal, that ranking looks for in a lead."""
    return sorted(
        {
            name
            for each in universe.companies.values()
            for name in (each.display_name, each.legal_name)
        }
    )


def _company_sites(universe: Universe) -> list[str]:
    """The hosts of the universe companies' websites, which ranking demotes: a company's own
    pages tell a researcher less than an article about it."""
    return sorted(
        {site_host(each.website) for each in universe.companies.values() if each.website} - {""}
    )


def _take_leads(
    connection: Connection,
    investigation_id: uuid.UUID,
    discovery_id: uuid.UUID,
    max_leads: int,
    *,
    companies: Sequence[str],
    company_sites: Sequence[str],
    ranking: RankingConfig,
) -> tuple[int, int, int, int]:
    """Keep the discovery's top-ranked leads up to the budget, each with its score and
    reasons; (taken, dropped over the budget, rejected by ranking, found)."""
    sightings = discovery_sightings(connection, discovery_id)
    ranked = rank_leads(sightings, companies=companies, config=ranking, company_sites=company_sites)
    held = set(
        connection.execute(
            text("SELECT lead_id FROM investigation_lead WHERE investigation_id = :id"),
            {"id": investigation_id},
        ).scalars()
    )
    fresh = [lead for lead in ranked if lead.lead_id not in held]
    kept = [lead for lead in fresh if lead.score.kept]
    room = max(max_leads - len(held), 0)
    for rank, lead in enumerate(kept[:room], start=len(held) + 1):
        connection.execute(
            text(
                "INSERT INTO investigation_lead (investigation_id, lead_id, rank, discovery_id,"
                " score, reasons, query, ranking_version) VALUES (:id, :lead, :rank,"
                " :discovery, :score, CAST(:reasons AS jsonb), :query, :version)"
            ),
            {
                "id": investigation_id,
                "lead": lead.lead_id,
                "rank": rank,
                "discovery": discovery_id,
                "score": lead.score.score,
                "reasons": json.dumps(lead.score.reasons),
                "query": lead.query,
                "version": ranking.version,
            },
        )
    taken = min(len(kept), room)
    return taken, len(kept) - taken, len(fresh) - len(kept), len(ranked)


def accepted_claims(
    connection: Connection, investigation_id: uuid.UUID, run_id: uuid.UUID
) -> list[RowMapping]:
    """The run's accepted Claims on the investigation's documents, excluding those read by a
    task whose premise was disproven; oldest first."""
    return list(
        connection.execute(
            text(
                "SELECT c.id, c.assertion_id, c.source_version_id, c.quote, c.span_start,"
                " c.span_end, c.predicate, c.product, c.layer, c.epistemic_type, c.object_text,"
                " c.subject_company_id, c.object_company_id, s.display_name AS subject_name,"
                " o.display_name AS object_name, a.verification_status, d.title AS source_title,"
                " v.available_at, m.evidence_family_id, t.round"
                " FROM claim c"
                " JOIN investigation_document doc ON doc.investigation_id = :id"
                "  AND doc.source_version_id = c.source_version_id"
                " JOIN investigation_task t ON t.id = doc.task_id"
                " JOIN assertion a ON a.id = c.assertion_id"
                " JOIN source_version v ON v.id = c.source_version_id"
                " JOIN source_document d ON d.id = v.source_document_id"
                " JOIN company s ON s.id = c.subject_company_id"
                " LEFT JOIN company o ON o.id = c.object_company_id"
                " LEFT JOIN evidence_family_member m ON m.source_version_id = c.source_version_id"
                " WHERE c.run_id = :run AND c.outcome = 'accepted'"
                " AND NOT EXISTS (SELECT FROM investigation_premise p"
                "  WHERE p.investigation_id = :id AND p.status = 'disproven'"
                "  AND p.key = ANY(t.premise_keys))"
                " ORDER BY c.created_at, c.id"
            ),
            {"id": investigation_id, "run": run_id},
        ).mappings()
    )


def _family(claim: RowMapping) -> str:
    """The claim's Evidence Family (a Source Version outside any family is its own)."""
    family = claim["evidence_family_id"]
    return f"family:{family}" if family is not None else f"version:{claim['source_version_id']}"


def card_finding(
    statement: str,
    cited: list[RowMapping],
    finding: Any,
    counterevidence: Mapping[uuid.UUID, list[uuid.UUID]] | None = None,
) -> CardFinding:
    """A finding citing `cited` accepted Claims, with the independent contradictions
    (`counterevidence`: claim ID -> counterevidence IDs, atlas.investigations.skeptic) of any
    of them."""
    available: list[datetime] = [c["available_at"] for c in cited]
    against = list(
        dict.fromkeys(each for c in cited for each in (counterevidence or {}).get(c["id"], []))
    )
    entities = dict.fromkeys(
        each
        for c in cited
        for each in (c["subject_company_id"], c["object_company_id"])
        if each is not None
    )
    return CardFinding(
        claim_text=statement,
        epistemic_type="agent_inference",
        cited_epistemic_types=list(dict.fromkeys(c["epistemic_type"] for c in cited)),
        claim_ids=[c["id"] for c in cited],
        original_source_version_ids=list(dict.fromkeys(c["source_version_id"] for c in cited)),
        source_spans=[
            SourceSpan(
                claim_id=c["id"],
                assertion_id=c["assertion_id"],
                source_version_id=c["source_version_id"],
                span_start=c["span_start"],
                span_end=c["span_end"],
                quote=c["quote"],
                verification_status=c["verification_status"],
            )
            for c in cited
        ],
        independent_evidence_families=sorted({_family(c) for c in cited}),
        entity_ids=list(entities),
        validity_dates=ValidityDates(evidence_available_at=max(available), valid_until=None),
        limitations=finding.limitations,
        counterevidence_ids=against,
        needs_review=bool(against)
        or any(c["verification_status"] != "corroborated" for c in cited),
        open_questions=finding.open_questions,
    )


def counterevidence_for_editors(
    connection: Connection, found: Sequence[CardContradiction]
) -> tuple[list[EditorCounterevidence], list[QuotedText]]:
    """Accepted contradictions as the Editors are sent them: the request's items, and each
    item's quote as low-trust retrieved data (`id` its counterevidence ID)."""
    names = {
        row.id: row.display_name
        for row in connection.execute(text("SELECT id, display_name FROM company"))
    }
    titles = {
        row.id: row.title
        for row in connection.execute(
            text(
                "SELECT v.id, d.title FROM source_version v"
                " JOIN source_document d ON d.id = v.source_document_id WHERE v.id = ANY(:ids)"
            ),
            {"ids": [each.source_span.source_version_id for each in found]},
        )
    }
    sent = [
        EditorCounterevidence(
            counterevidence_id=str(each.counterevidence_id),
            checklist_item=each.checklist_item,
            subject=names.get(each.subject_company_id, str(each.subject_company_id)),
            statement=each.statement,
            contradicts_claim_ids=[str(claim) for claim in each.contradicts_claim_ids],
            independent=each.independent,
            source_title=titles.get(each.source_span.source_version_id, ""),
        )
        for each in found
    ]
    quoted = [
        QuotedText(
            id=str(each.counterevidence_id),
            source=f"{span.source_version_id}#{span.span_start}-{span.span_end}",
            text=span.quote,
        )
        for each in found
        for span in (each.source_span,)
    ]
    return sent, quoted


def bear_context_for_editor(
    connection: Connection, found: Sequence[CardBearContext]
) -> tuple[list[EditorBearContext], list[QuotedText]]:
    """Accepted bear context as the research card's Editor is sent it, in the card's order:
    the request's items, and each item's quote as low-trust retrieved data (`id` its
    counterevidence ID)."""
    items = [(group, item) for group in found for item in group.items]
    titles = {
        row.id: row.title
        for row in connection.execute(
            text(
                "SELECT v.id, d.title FROM source_version v"
                " JOIN source_document d ON d.id = v.source_document_id WHERE v.id = ANY(:ids)"
            ),
            {"ids": [item.source_span.source_version_id for _, item in items]},
        )
    }
    sent = [
        EditorBearContext(
            counterevidence_id=str(item.counterevidence_id),
            checklist_item=group.checklist_item,
            company=group.company_name,
            statement=item.statement,
            figure_name=item.figure_name,
            figure_period=item.figure_period,
            source_title=titles.get(item.source_span.source_version_id, ""),
        )
        for group, item in items
    ]
    quoted = [
        QuotedText(
            id=str(item.counterevidence_id),
            source=f"{span.source_version_id}#{span.span_start}-{span.span_end}",
            text=span.quote,
        )
        for _, item in items
        for span in (item.source_span,)
    ]
    return sent, quoted


def _budget_detail(role: str, error: TokenBudgetExhausted) -> str:
    return (
        f"the run's token budget ran out before the {role}'s call"
        f" ({error.spent} of {error.budget} tokens spent)"
    )


def _json(value: dict[str, JsonValue]) -> str:
    return json.dumps(value)
