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
     sent to a role. The Investigators' passages are chosen by them, and so are the
     companies read beside the seeds: when the task is recorded, the plan gains an
     Investigator for each other researched company the pointers name, in rank order, while
     the company budget has room (atlas.investigations.companies; the plan's advance).
   - **Investigator** (one per seed company, and one per company added for its pointers):
     its company's document floor (the latest periodic report and results release; pilot
     fix 24), then the Source Versions the round's pointers into its company name, best
     pointer first
     (one per Source Document: the latest a pointer names), then the latest parsed Source
     Versions of its other documents
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
     Investigators accepted no Claim (nothing to challenge); otherwise it asks Memory each
     bear-checklist item for each company the accepted Claims name, across the theme (its
     own reading pointers; no Memory is sent to it), plans and runs its own SearXNG queries,
     and reads the Source Versions its pointers lead to (and, for a company Memory pointed
     at nothing of, the ones code chooses: the fallback), the passages chosen as the
     Investigator's, for counterevidence: each accepted item a contradiction of a named
     Claim or bear context about a company. An accepted, independent contradiction may
     disprove a company premise, applied when the task is recorded (by `atlas-skeptic`),
     which cancels only what depends on it.
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
     `searched`, `read` and `not_read` sections (atlas.investigations.coverage; `not_read`:
     the companies the pointers name that no Investigator read). A finding contradicted
     by an independent contradiction needs review, and so does the investigation
     (atlas.roles.editor); bear context marks no finding and stops nothing. With no accepted
     Claim at all the card has no finding, only what was searched and read and the open
     questions for the next round, and the investigation stops
     `no_new_independent_evidence` as before. The Editor cites each Claim by a short
     reference (`c1`, `c2`, ...), which code maps back. An answer cut off at the output cap
     is asked again once with the cap doubled, up to `editor_max_output_tokens`; if it is
     cut off there too, or quarantined, the card is code's alone (no finding, the accepted
     Claims by company, the reason) and the investigation stops `needs_review`.
   - **The argument plan's roles** (bottleneck-argument ticket 05; atlas.investigations.argument):
     a **Reader** per step (atlas.investigations.reader; its session keyed by the task, so it
     continues where it stopped), the **Skeptic** as the same loop sent the Readers' Facts to
     challenge, the **Financial Analyst** sent the Readers' Facts in place of Claims, and the
     **Editor** writing the argument (`EDITOR_ARGUMENT`), each step's statement through the
     grounding check and the finding judge, each step's status decided by code.
3. **Outcome.** Under the lock, the task's outcome is recorded and the plan advanced. When
   the run's token budget runs out, the task and the investigation stop `budget_exhausted`
   (resumable). An LLM quota or outage (a pausable failure) records `task_paused` and
   re-raises, so the worker pauses the queue and requeues the job; nothing is written for
   the role. Any other failure is retried; on the job's last attempt the task fails and the
   investigation stops `needs_review`.
"""

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast

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
from atlas.investigations.argument import (
    SKEPTIC_CHALLENGED,
    ArgumentFacts,
    StepStatement,
    argument_facts,
    build_steps,
    challenged,
    quantity_text,
    step_counts,
)
from atlas.investigations.companies import FloorCandidate, document_floor, documents_in_order
from atlas.investigations.coverage import coverage, not_read, skeptic_coverage, unchecked_note
from atlas.investigations.entity_hop import HopLimits, record_entity_pointers
from atlas.investigations.grounding import GROUNDING_LIMIT, CheckedFinding, check_findings
from atlas.investigations.meaning import JUDGE_LIMIT, judge_findings, voting
from atlas.investigations.model import (
    RUN_KIND,
    CardBearContext,
    CardClaimSummary,
    CardCompanyClaims,
    CardContradiction,
    CardFinding,
    ResearchCard,
    SourceSpan,
    UnsupportedFinding,
    ValidityDates,
)
from atlas.investigations.pointers import (
    SCOUT_ACTOR,
    LayerRecall,
    Recall,
    record_pointers,
    round_reading,
    scout_queries,
)
from atlas.investigations.reader import (
    READER_ACTOR,
    Reader,
    ReaderCompanyRow,
    ReaderSetup,
    open_session,
    reader_companies,
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
from atlas.research.provenance import ProvenanceResolver
from atlas.research.service import (
    RecallResponse,
    Research,
    ResearchScope,
    reading_index_recall,
)
from atlas.roles import (
    QuotedText,
    RoleCaller,
    RoleCallFailed,
    RoleOutputQuarantined,
    RoleOutputTruncated,
    TokenBudgetExhausted,
)
from atlas.roles.editor import (
    EDITOR,
    EDITOR_ARGUMENT,
    EDITOR_REGROUND,
    EDITOR_REVISE,
    ArgumentFactItem,
    ArgumentStepDraft,
    ArgumentStepItem,
    CardFindingDraft,
    EditorArgumentRequest,
    EditorBearContext,
    EditorCardClaim,
    EditorContradiction,
    EditorCounterevidence,
    EditorDocumentRead,
    EditorLead,
    EditorQuery,
    EditorReading,
    EditorRegroundRequest,
    EditorRequest,
    EditorReviseRequest,
    RegroundedFindings,
    RevisedFindings,
)
from atlas.roles.financial_analyst import FINANCIAL_ANALYST
from atlas.roles.finding_judge import FINDING_JUDGE, FindingJudgement, FindingJudgeRequest
from atlas.roles.reader import (
    ARGUMENT_SKEPTIC,
    ARGUMENT_SKEPTIC_VERSION,
    ARGUMENT_STEPS,
    READER,
    READER_VERSION,
    SKEPTIC_STEP,
    STEPS,
    ArgumentStep,
)
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
        argument = investigation["plan"] == "argument"
        if role == "scout":
            return self._scout(job, investigation, task, run_id)
        if role == "investigator":
            return self._investigator(job, investigation, task, run_id)
        if role == "reader":
            return self._reader(investigation, task, run_id)
        if role == "skeptic":
            if argument:
                return self._argument_skeptic(investigation, task, run_id)
            return self._skeptic(investigation, task, run_id)
        if role == "financial_analyst":
            return self._financial_analyst(investigation, run_id)
        if role == "editor":
            if argument:
                return self._argument_editor(investigation, task, run_id)
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

    def _ask_editor_again(
        self,
        investigation: RowMapping,
        run_id: uuid.UUID,
        request: EditorRegroundRequest,
        retrieved: list[QuotedText],
    ) -> tuple[RegroundedFindings, uuid.UUID]:
        """The Editor asked once more for its ungrounded findings (pilot-fixes ticket 21)."""
        with self._caller(investigation) as caller:
            return caller.call_recorded(
                EDITOR_REGROUND, request, run_id=run_id, retrieved=retrieved
            )

    def _judge_finding(
        self,
        investigation: RowMapping,
        run_id: uuid.UUID,
        request: FindingJudgeRequest,
        retrieved: list[QuotedText],
    ) -> tuple[FindingJudgement, uuid.UUID]:
        """The finding judge on one finding (bottleneck-argument ticket 04)."""
        with self._caller(investigation) as caller:
            return caller.call_recorded(FINDING_JUDGE, request, run_id=run_id, retrieved=retrieved)

    def _ask_editor_to_revise(
        self,
        investigation: RowMapping,
        run_id: uuid.UUID,
        request: EditorReviseRequest,
        retrieved: list[QuotedText],
    ) -> tuple[RevisedFindings, uuid.UUID]:
        """The Editor asked once to rewrite its misstated findings (ticket 04)."""
        with self._caller(investigation) as caller:
            return caller.call_recorded(EDITOR_REVISE, request, run_id=run_id, retrieved=retrieved)

    def _company_names(self) -> list[tuple[str, str]]:
        """Each company's display and legal names: one name, for the grounding check."""
        with self._engine.connect() as connection:
            rows = connection.execute(text("SELECT display_name, legal_name FROM company")).all()
        return [(row.display_name, row.legal_name) for row in rows]

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
            self._engine,
            self._theme_recall(theme_id, universe, investigation["as_of"]),
            investigation,
            task,
            queries,
            layer_recall=self._layer_recall(theme_id, universe, investigation["as_of"]),
        )
        # The entity hop (memory-quality ticket 09): what other companies' documents say
        # about the companies this round reads, whether or not a recall ranked them.
        hop = record_entity_pointers(
            self._engine,
            self._gateway,
            ProvenanceResolver(
                self._engine, open_archive(self._settings), self._gateway
            ).resolve_recalled,
            investigation,
            task,
            HopLimits(
                max_companies=self._settings.entity_hop_max_companies,
                max_facts=self._settings.entity_hop_max_facts,
                pointer_weight=self._settings.entity_hop_pointer_weight,
            ),
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
        artifacts: dict[str, JsonValue] = dict(pointers) | hop
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

    def _theme_recall(
        self, theme_id: str, universe: Universe, as_of: datetime, actor: Actor = SCOUT_ACTOR
    ) -> Recall:
        ask = self._asker(theme_id, universe, as_of, actor)
        return lambda query: ask(query, None)

    def _layer_recall(
        self, theme_id: str, universe: Universe, as_of: datetime, actor: Actor = SCOUT_ACTOR
    ) -> LayerRecall:
        """The same recall limited to the facts labelled with a layer (memory-quality ticket
        13): the theme AND the layer's label tag, in one compound tag filter."""
        ask = self._asker(theme_id, universe, as_of, actor)
        return lambda query, layer: ask(query, layer)

    def _asker(
        self, theme_id: str, universe: Universe, as_of: datetime, actor: Actor
    ) -> Callable[[str, str | None], RecallResponse]:
        """Recall across the theme: every memory tagged with it, whichever company's.

        Asked like a reading index (memory-quality ticket 07; docs/decisions.md, "Recall as a
        reading index"): `pointer_recall_max_tokens` of results, budget high, an observation
        in place of the facts it was built from, recency judged from the investigation's
        as-of time, each observation's sources and every fact's chunk in the same answer."""
        research = Research(
            self._engine, open_archive(self._settings), self._gateway, actor, lambda: universe
        )
        max_tokens = self._settings.pointer_recall_max_tokens

        def ask(query: str, layer: str | None = None) -> RecallResponse:
            return research.recall(
                reading_index_recall(
                    query,
                    ResearchScope(theme_ids=[theme_id], layer=layer),
                    max_tokens=max_tokens,
                    as_of=as_of,
                )
            )

        return ask

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
        """The task's Source Versions (chosen once, within the document budget): its
        company's document floor (the latest periodic report and results release; pilot fix
        24), then the ones the round's reading pointers into its company name, best pointer
        first, then its latest ones (atlas.investigations.companies.documents_in_order); and
        how many available ones the budget left out."""
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
            where = {
                "company": task["company_id"],
                "as_of": investigation["as_of"],
                "id": investigation["id"],
                "round": task["round"],
            }
            # Where Memory pointed in this company's documents: one Source Version per Source
            # Document (the latest one a pointer names), by its best pointer, best first.
            pointed_rows = list(
                connection.execute(
                    text(
                        "SELECT id, source_document_id FROM (SELECT DISTINCT ON"
                        " (v.source_document_id) v.id, v.source_document_id,"
                        " p.rank, p.query_index, a.available_at FROM reading_pointer p"
                        " JOIN investigation_task t ON t.id = p.task_id AND t.role = 'scout'"
                        " JOIN source_version v ON v.id = p.source_version_id"
                        " JOIN source_version_availability a ON a.source_version_id = v.id"
                        " JOIN source_document d ON d.id = v.source_document_id"
                        " WHERE p.investigation_id = :id AND p.round = :round"
                        " AND d.company_id = :company AND a.available_at <= :as_of"
                        " AND v.parse_status IN ('parsed', 'incomplete')"
                        " AND v.parsed_object_uri IS NOT NULL"
                        " AND NOT EXISTS (SELECT FROM investigation_document r"
                        "  WHERE r.investigation_id = :id AND r.source_version_id = v.id)"
                        " ORDER BY v.source_document_id, a.available_at DESC, v.id, p.rank,"
                        " p.query_index) best"
                        " ORDER BY rank, query_index, available_at DESC, id"
                    ),
                    where,
                )
            )
            pointed: list[uuid.UUID] = [row.id for row in pointed_rows]
            floor = _document_floor(
                connection, where, {row.source_document_id: row.id for row in pointed_rows}
            )
            # Then the latest version of each of its other Source Documents, newest first.
            latest = list(
                connection.execute(
                    text(
                        "SELECT id FROM (SELECT DISTINCT ON (v.source_document_id) v.id,"
                        " a.available_at FROM source_version v"
                        " JOIN source_version_availability a ON a.source_version_id = v.id"
                        " JOIN source_document d ON d.id = v.source_document_id"
                        " WHERE d.company_id = :company AND a.available_at <= :as_of"
                        " AND v.parse_status IN ('parsed', 'incomplete')"
                        " AND v.parsed_object_uri IS NOT NULL"
                        " AND v.source_document_id NOT IN (SELECT source_document_id"
                        "  FROM source_version WHERE id = ANY(:pointed))"
                        " ORDER BY v.source_document_id, a.available_at DESC, v.id) latest"
                        # An earlier round's (or another task's) reading isn't repeated.
                        " WHERE NOT EXISTS (SELECT FROM investigation_document r"
                        "  WHERE r.investigation_id = :id AND r.source_version_id = latest.id)"
                        " ORDER BY available_at DESC, id"
                    ),
                    where | {"pointed": pointed},
                ).scalars()
            )
            available = len({*floor, *pointed, *latest})
            room = _document_share(
                connection, investigation, task, max(investigation["max_documents"] - int(used), 0)
            )
            chosen = documents_in_order(floor, pointed, latest, room)
            dropped = available - len(chosen)
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
                    " 'documents_pointed', CAST(:pointed AS integer),"
                    " 'documents_floor', CAST(:floor AS jsonb),"
                    " 'documents_dropped', CAST(:dropped AS integer)) WHERE id = :id"
                ),
                {
                    "id": task["id"],
                    "n": len(chosen),
                    # How many of them the reading pointers named.
                    "pointed": len(set(chosen) & set(pointed)),
                    # Which of them the document floor chose (pilot fix 24), in floor order.
                    "floor": json.dumps([str(each) for each in floor if each in chosen]),
                    "dropped": dropped,
                },
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
        universe = load_universe(self._settings.themes_config)
        theme = universe.themes.get(investigation["theme"])
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
                # Memory chooses what the Skeptic reads: its recalls, across the theme.
                self._theme_recall(
                    investigation["theme"], universe, investigation["as_of"], SKEPTIC_ACTOR
                ),
                max_queries=self._settings.discovery_max_queries,
                max_passages=self._settings.investigator_max_passages,
                max_document_share=self._settings.investigator_max_passage_share_per_document,
                passages_per_call=self._settings.investigator_passages_per_call,
                edgar=EdgarFullTextSearch.from_settings(self._settings),
            )
            found = skeptic.run(
                investigation,
                task,
                run_id,
                theme_title=theme.title if theme else investigation["theme"],
                company_ids=company_ids,
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
        argument = investigation["plan"] == "argument"
        with self._engine.connect() as connection:
            # The argument plan's Analyst is sent the Readers' Facts in place of Claims.
            claims = (
                argument_facts(connection, investigation["id"], statements=True).supporting
                if argument
                else accepted_claims(connection, investigation["id"], run_id)
            )
            companies = analyst_companies(connection, investigation["seed_company_ids"], claims)
            if not companies:
                return _Outcome(
                    "skipped",
                    detail=(
                        "nothing to quantify: the Readers recorded no Fact about a seed company"
                        if argument
                        else "nothing to quantify: the Investigators accepted no Claims"
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
            unread = not_read(connection, investigation["id"])
            unchecked = skeptic_coverage(connection, investigation, claims)
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
        # The Editor cites each Claim by a short reference, which code maps back to its ID.
        refs = {f"c{index}": c for index, c in enumerate(claims, start=1)}
        ref_of = {c["id"]: ref for ref, c in refs.items()}
        request = EditorRequest(
            theme_id=investigation["theme"],
            theme_title=theme.title if theme else investigation["theme"],
            research_question=investigation["question"],
            claims=[
                EditorCardClaim(
                    ref=ref,
                    subject=c["subject_name"],
                    predicate=c["predicate"],
                    object=c["object_name"] or c["object_text"] or "",
                    product=c["product"],
                    layer=c["layer"],
                    epistemic_type=c["epistemic_type"],
                    source_title=c["source_title"],
                    source_version_id=str(c["source_version_id"]),
                )
                for ref, c in refs.items()
            ],
            leads=[
                EditorLead(lead_id=str(lead.id), title=lead.title, url=lead.url) for lead in leads
            ],
            contradictions=[
                EditorContradiction(
                    **each.model_dump(exclude={"contradicts_claim_ids"}),
                    contradicts_refs=[
                        ref_of[claim] for claim in found.contradicts_claim_ids if claim in ref_of
                    ],
                    how=found.how,
                )
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
                    id=ref,
                    source=f"{c['source_version_id']}#{c['span_start']}-{c['span_end']}",
                    text=c["quote"],
                )
                for ref, c in refs.items()
            ]
            + [
                QuotedText(id=str(lead.id), source=lead.url, text=f"{lead.title}\n{lead.snippet}")
                for lead in leads
            ]
            + quoted
            + context_quoted
        )
        by_claim = counterevidence_by_claim(against)
        bound = self._settings.editor_max_output_tokens
        cap = min(EDITOR.max_output_tokens, bound)
        try:
            with self._caller(investigation) as caller:
                try:
                    draft, role_call_id = caller.call_recorded(
                        EDITOR, request, run_id=run_id, retrieved=retrieved, max_output_tokens=cap
                    )
                except RoleOutputTruncated:
                    if cap >= bound:
                        raise
                    # Cut off at the cap: once more with the cap doubled, up to the bound.
                    draft, role_call_id = caller.call_recorded(
                        EDITOR,
                        request,
                        run_id=run_id,
                        retrieved=retrieved,
                        max_output_tokens=min(2 * cap, bound),
                    )
        except RoleOutputQuarantined as failure:
            # The investigation never ends card-less: code writes the card without findings.
            stop_reason = "needs_review" if claims else "no_new_independent_evidence"
            stop_detail = f"the Editor failed, so the card has no finding: {failure}"
            if (note := unchecked_note(unchecked)) is not None:
                stop_detail = f"{stop_detail}; {note}"
            card = ResearchCard(
                status="draft",
                question=investigation["question"],
                findings=[],
                open_questions=[],
                unsupported_findings=[],
                editor_verdict="needs_review",
                claims_considered=len(claims),
                lead_ids=[lead.id for lead in leads],
                disproven_premises=disproven,
                editor_role_call_id=failure.role_call_id,
                contradictions=against,
                bear_context=context,
                searched=searched,
                read=read,
                not_read=unread,
                skeptic_coverage=unchecked,
                grounding_limit=GROUNDING_LIMIT,
                editor_failure=str(failure),
                claims_by_company=claims_by_company(claims),
            )
            return _Outcome(
                "succeeded",
                artifacts={
                    "role_call_id": str(failure.role_call_id),
                    "claims": len(claims),
                    "new_evidence_families": len(new_families),
                    "findings": 0,
                    "editor_failure": str(failure),
                    "contradictions": len(against),
                    "bear_context": sum(len(group.items) for group in context),
                    "stop_reason": stop_reason,
                    "stop_detail": stop_detail,
                },
                card=card,
            )
        findings: list[CardFinding] = []
        unsupported: list[UnsupportedFinding] = []
        citing: list[tuple[CardFindingDraft, list[str]]] = []
        for finding in draft.findings:
            cited = list(dict.fromkeys(finding.claim_refs))
            unknown = [each for each in cited if each not in refs]
            if not cited or unknown:
                reason = (
                    "cites no Claim"
                    if not cited
                    else "cites what isn't an accepted Claim of this investigation: "
                    + ", ".join(unknown)
                )
                # The Claims it does name by their IDs; what isn't a Claim's reference as written.
                named = [str(refs[each]["id"]) if each in refs else each for each in cited]
                unsupported.append(
                    UnsupportedFinding(statement=finding.statement, claim_ids=named, reason=reason)
                )
                continue
            citing.append((finding, cited))
        # A finding says only what its Claims say (pilot-fixes ticket 21): checked by code,
        # an ungrounded one asked again once, and set aside if it still is.
        checked = check_findings(
            citing,
            refs,
            investigation["question"],
            self._company_names(),
            lambda again, quotes: self._ask_editor_again(investigation, run_id, again, quotes),
        )
        grounded: list[CheckedFinding] = []
        for each in checked.findings:
            if each.ungrounded:
                unsupported.append(
                    UnsupportedFinding(
                        statement=each.draft.statement,
                        claim_ids=[str(refs[ref]["id"]) for ref in each.cited],
                        reason="ungrounded: " + ", ".join(each.ungrounded),
                    )
                )
                continue
            grounded.append(each)
        # Then for meaning (bottleneck-argument ticket 04): each grounded finding judged
        # against its quotes, a misstated one rewritten once and judged again, and set aside
        # if it still is.
        meaning = None
        if self._settings.finding_judge and grounded:
            meaning = judge_findings(
                grounded,
                refs,
                investigation["question"],
                self._company_names(),
                voting(
                    lambda asked, quotes: self._judge_finding(investigation, run_id, asked, quotes),
                    self._settings.finding_judge_votes,
                ),
                lambda asked, quotes: self._ask_editor_to_revise(
                    investigation, run_id, asked, quotes
                ),
            )
            for outcome in meaning.outcomes:
                if not outcome.kept:
                    unsupported.append(
                        UnsupportedFinding(
                            statement=outcome.draft.statement,
                            claim_ids=[str(refs[ref]["id"]) for ref in outcome.cited],
                            reason=outcome.reason or "misstated",
                        )
                    )
                    continue
                findings.append(
                    card_finding(
                        outcome.draft.statement,
                        [refs[ref] for ref in outcome.cited],
                        outcome.draft,
                        by_claim,
                        grounded=True,
                        judged=outcome.judged,
                        # Its judge call failed: the finding stands, for review.
                        unjudged=outcome.judged is None,
                    )
                )
        else:
            for each in grounded:
                findings.append(
                    card_finding(
                        each.draft.statement,
                        [refs[ref] for ref in each.cited],
                        each.draft,
                        by_claim,
                        grounded=True,
                    )
                )
        unjudged = meaning.counts["failed_first"] if meaning is not None else 0
        contradicted = sum(1 for f in findings if f.counterevidence_ids)
        if not claims:
            # The card reports what was searched and read; the stop reason is as before.
            stop_reason = "no_new_independent_evidence"
            stop_detail = "no new independent Evidence: the Investigator accepted no Claims"
        elif (
            draft.verdict == "answered"
            and findings
            and not unsupported
            and not contradicted
            and not unjudged
        ):
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
            if unjudged:
                problems.append(f"{unjudged} findings could not be judged for meaning")
            if not findings:
                problems.append("no finding cites an accepted Claim")
            if draft.verdict != "answered":
                problems.append("the Editor asks for review")
            stop_detail = "; ".join(problems)
        if claims and (note := unchecked_note(unchecked)) is not None:
            stop_detail = f"{stop_detail}; {note}"
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
            not_read=unread,
            skeptic_coverage=unchecked,
            grounding_limit=GROUNDING_LIMIT + (JUDGE_LIMIT if meaning is not None else ""),
            judged=meaning.judgements if meaning is not None else [],
        )
        return _Outcome(
            "succeeded",
            artifacts={
                "role_call_id": str(role_call_id),
                "claims": len(claims),
                "new_evidence_families": len(new_families),
                "findings": len(findings),
                "unsupported_findings": len(unsupported),
                "grounding": {
                    "asked_again": checked.asked_again,
                    "repaired": checked.repaired,
                    "role_call_id": (
                        str(checked.role_call_id) if checked.role_call_id is not None else None
                    ),
                    "failure": checked.failure,
                },
                "meaning": (
                    {
                        **meaning.counts,
                        "revise_role_call_id": (
                            str(meaning.revise_role_call_id)
                            if meaning.revise_role_call_id is not None
                            else None
                        ),
                        "revise_failure": meaning.revise_failure,
                    }
                    if meaning is not None
                    else None
                ),
                "contradictions": len(against),
                "bear_context": sum(len(group.items) for group in context),
                "contradicted_findings": contradicted,
                "stop_reason": stop_reason,
                "stop_detail": stop_detail,
            },
            card=card,
        )

    # --- the argument plan (bottleneck-argument ticket 05) -------------------------------------

    def _reader_recall(
        self, theme_id: str, universe: Universe, as_of: datetime, actor: Actor
    ) -> Recall:
        """Memory across the theme, asked like a reading index at the Reader's text budget."""
        research = Research(
            self._engine, open_archive(self._settings), self._gateway, actor, lambda: universe
        )
        max_tokens = self._settings.reader_recall_max_tokens

        def ask(query: str) -> RecallResponse:
            return research.recall(
                reading_index_recall(
                    query, ResearchScope(theme_ids=[theme_id]), max_tokens=max_tokens, as_of=as_of
                )
            )

        return ask

    def _run_reader(
        self,
        investigation: RowMapping,
        task: RowMapping,
        run_id: uuid.UUID,
        *,
        skeptic: bool,
        setup: Callable[[list[ReaderCompanyRow], str], ReaderSetup],
    ) -> _Outcome:
        """One Reader (or the argument Skeptic) in the investigation's run, its session keyed
        by the task, so a retried, paused or resumed task continues it."""
        universe = load_universe(self._settings.themes_config)
        theme = universe.themes.get(investigation["theme"])
        question = self._question(investigation, task)
        step: ArgumentStep = SKEPTIC_STEP.key if skeptic else _step_of(task["key"])
        with self._engine.begin() as connection:
            companies = reader_companies(
                connection,
                investigation["seed_company_ids"],
                list(theme.companies) if theme else [],
            )
            session = open_session(
                connection,
                key=f"task:{task['id']}",
                run_id=lambda: run_id,
                role="skeptic" if skeptic else "reader",
                step=step,
                question=question,
                as_of=investigation["as_of"],
                task_id=task["id"],
                investigation_id=investigation["id"],
            )
        actor = SKEPTIC_ACTOR if skeptic else READER_ACTOR
        with self._caller(investigation) as caller:
            reader = Reader(
                self._engine,
                open_archive(self._settings),
                caller,
                self._reader_recall(
                    investigation["theme"], universe, investigation["as_of"], actor
                ),
                role=ARGUMENT_SKEPTIC if skeptic else READER,
                extractor_version=ARGUMENT_SKEPTIC_VERSION if skeptic else READER_VERSION,
                actor=actor,
                max_calls=self._settings.reader_max_calls,
                max_passages=self._settings.reader_max_passages,
            )
            outcome = reader.run(session, setup(companies, question))
        if outcome.status == "budget_exhausted":
            return _Outcome(
                "budget_exhausted",
                detail=f"the run's token budget ran out during the {task['key']} task",
                artifacts=outcome.artifacts,
            )
        return _Outcome("succeeded", artifacts=outcome.artifacts)

    def _reader(self, investigation: RowMapping, task: RowMapping, run_id: uuid.UUID) -> _Outcome:
        step = STEPS[_step_of(task["key"])]
        return self._run_reader(
            investigation,
            task,
            run_id,
            skeptic=False,
            setup=lambda companies, question: ReaderSetup(
                question=question,
                step=step,
                companies=companies,
                investigation_id=investigation["id"],
            ),
        )

    def _argument_skeptic(
        self, investigation: RowMapping, task: RowMapping, run_id: uuid.UUID
    ) -> _Outcome:
        with self._engine.connect() as connection:
            facts = argument_facts(connection, investigation["id"])
        if not facts.supporting:
            return _Outcome(
                "skipped",
                detail="nothing to challenge: the Readers recorded no Fact",
                artifacts={"facts_to_challenge": 0},
            )
        sent, quotes = challenged(facts.supporting)
        ids = {each.ref: row["id"] for each, row in zip(sent, facts.supporting, strict=False)}
        outcome = self._run_reader(
            investigation,
            task,
            run_id,
            skeptic=True,
            setup=lambda companies, question: ReaderSetup(
                question=question,
                step=SKEPTIC_STEP,
                companies=companies,
                investigation_id=investigation["id"],
                challenge=sent,
                challenge_quotes=quotes,
                challenge_ids=ids,
            ),
        )
        outcome.artifacts |= {
            "facts_to_challenge": len(sent),
            SKEPTIC_CHALLENGED: [str(each) for each in ids.values()],
        }
        return outcome

    def _argument_editor(
        self, investigation: RowMapping, task: RowMapping, run_id: uuid.UUID
    ) -> _Outcome:
        with self._engine.connect() as connection:
            facts = argument_facts(connection, investigation["id"])
            leads = connection.execute(
                text(
                    "SELECT l.id, l.url, l.title, l.snippet FROM investigation_lead il"
                    " JOIN lead l ON l.id = il.lead_id WHERE il.investigation_id = :id"
                    " ORDER BY il.rank"
                ),
                {"id": investigation["id"]},
            ).all()
            searched, _ = coverage(connection, investigation["id"])
            skeptic_task = (
                connection.execute(
                    text(
                        "SELECT status, artifacts FROM investigation_task"
                        " WHERE investigation_id = :id AND round = :round AND key = 'skeptic'"
                    ),
                    {"id": investigation["id"], "round": task["round"]},
                )
                .mappings()
                .one_or_none()
            )
        round_ = task["round"]
        if round_ > 1 and not any(
            facts.rounds.get(row["id"]) == round_ for row in facts.supporting
        ):
            return _Outcome(
                "skipped",
                detail="no new Fact: the round's Readers recorded none, so the earlier card stands",
                artifacts={"facts": len(facts.supporting), "new_facts": 0},
            )
        skeptic_artifacts: dict[str, Any] = dict(skeptic_task["artifacts"]) if skeptic_task else {}
        skeptic_ran = skeptic_task is not None and skeptic_task["status"] == "succeeded"
        recorded = cast(list[Any], skeptic_artifacts.get(SKEPTIC_CHALLENGED) or [])
        skeptic_checked = {uuid.UUID(str(each)) for each in recorded}
        rows = [*facts.supporting, *facts.counter]
        refs = {f"c{index}": row for index, row in enumerate(rows, start=1)}
        ref_of = {row["id"]: ref for ref, row in refs.items()}
        theme = load_universe(self._settings.themes_config).themes.get(investigation["theme"])
        latest = {s.step: s for s in facts.sessions if s.role == "reader"}
        request = EditorArgumentRequest(
            theme_id=investigation["theme"],
            theme_title=theme.title if theme else investigation["theme"],
            research_question=investigation["question"],
            steps=[
                ArgumentStepItem(
                    step=step.key,
                    title=step.title,
                    asks=step.asks,
                    fact_refs=_step_refs(facts, ref_of, step.key)[0],
                    counter_refs=_step_refs(facts, ref_of, step.key)[1],
                    searched=(
                        [str(each["query"]) for each in latest[step.key].state.searches]
                        if step.key in latest
                        else []
                    ),
                    reader_summary=(latest[step.key].state.summary if step.key in latest else None),
                )
                for step in ARGUMENT_STEPS
            ],
            facts=[_argument_item(ref_of[r["id"]], r, []) for r in facts.supporting],
            counterevidence=[
                _argument_item(
                    ref_of[r["id"]],
                    r,
                    [ref_of[each] for each in facts.against.get(r["id"], []) if each in ref_of],
                )
                for r in facts.counter
            ],
            leads=[
                EditorLead(lead_id=str(lead.id), title=lead.title, url=lead.url) for lead in leads
            ],
        )
        retrieved = [
            QuotedText(
                id=ref,
                source=f"{row['source_version_id']}#{row['span_start']}-{row['span_end']}",
                text=row["quote"],
            )
            for ref, row in refs.items()
        ] + [
            QuotedText(id=str(lead.id), source=lead.url, text=f"{lead.title}\n{lead.snippet}")
            for lead in leads
        ]
        bound = self._settings.editor_max_output_tokens
        cap = min(EDITOR_ARGUMENT.max_output_tokens, bound)
        card_base: dict[str, Any] = {
            "status": "draft",
            "question": investigation["question"],
            "findings": [],
            "claims_considered": 0,
            "lead_ids": [lead.id for lead in leads],
            "disproven_premises": [],
            "searched": searched,
            "plan": "argument",
        }
        try:
            with self._caller(investigation) as caller:
                try:
                    draft, role_call_id = caller.call_recorded(
                        EDITOR_ARGUMENT,
                        request,
                        run_id=run_id,
                        retrieved=retrieved,
                        max_output_tokens=cap,
                    )
                except RoleOutputTruncated:
                    if cap >= bound:
                        raise
                    draft, role_call_id = caller.call_recorded(
                        EDITOR_ARGUMENT,
                        request,
                        run_id=run_id,
                        retrieved=retrieved,
                        max_output_tokens=min(2 * cap, bound),
                    )
        except RoleOutputQuarantined as failure:
            steps = build_steps(facts, {}, refs, skeptic_checked, skeptic_ran)
            stop_reason = "needs_review" if facts.supporting else "no_new_independent_evidence"
            card = ResearchCard(
                **card_base,
                open_questions=[],
                unsupported_findings=[],
                editor_verdict="needs_review",
                editor_role_call_id=failure.role_call_id,
                editor_failure=str(failure),
                steps=steps,
            )
            return _Outcome(
                "succeeded",
                artifacts={
                    "role_call_id": str(failure.role_call_id),
                    "facts": len(facts.supporting),
                    "counterevidence": len(facts.counter),
                    "editor_failure": str(failure),
                    "steps": step_counts(steps),
                    "stop_reason": stop_reason,
                    "stop_detail": f"the Editor failed, so no step has a statement: {failure}",
                },
                card=card,
            )
        # The first statement the Editor wrote for each step; what it cites must be Facts.
        drafts: dict[str, ArgumentStepDraft] = {}
        for each in draft.steps:
            if each.step in STEPS and each.step not in drafts:
                drafts[each.step] = each
        unsupported: list[UnsupportedFinding] = []
        checking: list[tuple[str, CardFindingDraft, list[str]]] = []
        for key, each in drafts.items():
            cited = list(dict.fromkeys([*each.fact_refs, *each.counter_refs]))
            unknown = [ref for ref in cited if ref not in refs]
            if unknown:
                unsupported.append(
                    UnsupportedFinding(
                        statement=each.statement,
                        claim_ids=[str(refs[r]["id"]) if r in refs else r for r in cited],
                        reason="cites what isn't a Fact of this investigation: "
                        + ", ".join(unknown),
                    )
                )
                continue
            if not cited:
                continue  # a statement resting on no Fact says only that the step is unknown
            finding = CardFindingDraft(
                statement=each.statement, claim_refs=cited, limitations=[], open_questions=[]
            )
            checking.append((key, finding, cited))
        checked = check_findings(
            [(finding, cited) for _, finding, cited in checking],
            refs,
            investigation["question"],
            self._company_names(),
            lambda again, quotes: self._ask_editor_again(investigation, run_id, again, quotes),
        )
        kept: dict[str, tuple[str, bool | None]] = {}
        grounded: list[tuple[str, CheckedFinding]] = []
        for (key, _, _), each in zip(checking, checked.findings, strict=True):
            if each.ungrounded:
                unsupported.append(
                    UnsupportedFinding(
                        statement=each.draft.statement,
                        claim_ids=[str(refs[ref]["id"]) for ref in each.cited],
                        reason="ungrounded: " + ", ".join(each.ungrounded),
                    )
                )
                continue
            grounded.append((key, each))
        meaning = None
        if self._settings.finding_judge and grounded:
            meaning = judge_findings(
                [each for _, each in grounded],
                refs,
                investigation["question"],
                self._company_names(),
                lambda asked, quotes: self._judge_finding(investigation, run_id, asked, quotes),
                lambda asked, quotes: self._ask_editor_to_revise(
                    investigation, run_id, asked, quotes
                ),
            )
            for (key, _), outcome in zip(grounded, meaning.outcomes, strict=True):
                if not outcome.kept:
                    unsupported.append(
                        UnsupportedFinding(
                            statement=outcome.draft.statement,
                            claim_ids=[str(refs[ref]["id"]) for ref in outcome.cited],
                            reason=outcome.reason or "misstated",
                        )
                    )
                    continue
                kept[key] = (outcome.draft.statement, outcome.judged)
        else:
            for key, each in grounded:
                kept[key] = (each.draft.statement, None)
        statements = {
            key: StepStatement(
                statement=kept[key][0] if key in kept else None,
                cited=list(dict.fromkeys([*each.fact_refs, *each.counter_refs])),
                editor_status=each.status,
                unchecked=each.unchecked,
                grounded=True if key in kept else None,
                judged=kept[key][1] if key in kept else None,
            )
            for key, each in drafts.items()
        }
        steps = build_steps(facts, statements, refs, skeptic_checked, skeptic_ran)
        unjudged = meaning.counts["failed_first"] if meaning is not None else 0
        unknown_steps = [s.step for s in steps if s.status == "unknown"]
        disputed = [s.step for s in steps if s.status == "disputed"]
        if not facts.supporting:
            stop_reason = "no_new_independent_evidence"
            stop_detail = "no Fact: the Readers recorded none, so every step is unknown"
        elif (
            draft.verdict == "answered"
            and not unknown_steps
            and not disputed
            and not unsupported
            and not unjudged
        ):
            stop_reason = "answered"
            stop_detail = "every step of the argument is supported by its Facts"
        else:
            stop_reason = "needs_review"
            problems: list[str] = []
            if unknown_steps:
                problems.append(f"steps unknown: {', '.join(unknown_steps)}")
            if disputed:
                problems.append(f"steps disputed: {', '.join(disputed)}")
            if unsupported:
                problems.append(f"{len(unsupported)} statements were dropped")
            if unjudged:
                problems.append(f"{unjudged} statements could not be judged for meaning")
            if draft.verdict != "answered":
                problems.append("the Editor asks for review")
            stop_detail = "; ".join(problems)
        card = ResearchCard(
            **card_base,
            open_questions=draft.open_questions,
            unsupported_findings=unsupported,
            editor_verdict=draft.verdict,
            editor_role_call_id=role_call_id,
            grounding_limit=GROUNDING_LIMIT + (JUDGE_LIMIT if meaning is not None else ""),
            judged=meaning.judgements if meaning is not None else [],
            steps=steps,
        )
        return _Outcome(
            "succeeded",
            artifacts={
                "role_call_id": str(role_call_id),
                "facts": len(facts.supporting),
                "counterevidence": len(facts.counter),
                "steps": step_counts(steps),
                "statements_kept": len(kept),
                "unsupported_findings": len(unsupported),
                "grounding": {
                    "asked_again": checked.asked_again,
                    "repaired": checked.repaired,
                    "role_call_id": (
                        str(checked.role_call_id) if checked.role_call_id is not None else None
                    ),
                    "failure": checked.failure,
                },
                "meaning": (
                    {
                        **meaning.counts,
                        "revise_role_call_id": (
                            str(meaning.revise_role_call_id)
                            if meaning.revise_role_call_id is not None
                            else None
                        ),
                        "revise_failure": meaning.revise_failure,
                    }
                    if meaning is not None
                    else None
                ),
                "stop_reason": stop_reason,
                "stop_detail": stop_detail,
            },
            card=card,
        )


# --- helpers ------------------------------------------------------------------------------------


def _document_floor(
    connection: Connection, where: Mapping[str, Any], pointed: Mapping[Any, uuid.UUID]
) -> list[uuid.UUID]:
    """The company's document floor (atlas.investigations.companies.document_floor) among
    the latest parsed version of each of its Source Documents available as of the
    investigation's time (or, for a document a pointer names, the version it names); a floor
    document the investigation has already read is not read again."""
    rows = connection.execute(
        text(
            "SELECT DISTINCT ON (v.source_document_id) v.id, v.source_document_id,"
            " a.available_at, d.form_type, d.document_type, v.metadata -> 'items' AS filing_items"
            " FROM source_version v JOIN source_document d ON d.id = v.source_document_id"
            " JOIN source_version_availability a ON a.source_version_id = v.id"
            " WHERE d.company_id = :company AND a.available_at <= :as_of"
            " AND v.parse_status IN ('parsed', 'incomplete')"
            " AND v.parsed_object_uri IS NOT NULL"
            " ORDER BY v.source_document_id, a.available_at DESC, v.id"
        ),
        dict(where),
    ).all()
    floor = document_floor(
        [
            FloorCandidate(
                version_id=pointed.get(row.source_document_id, row.id),
                available_at=row.available_at,
                form_type=row.form_type,
                document_type=row.document_type,
                items=_filing_items(row.filing_items),
            )
            for row in rows
        ]
    )
    read = set(
        connection.execute(
            text(
                "SELECT source_version_id FROM investigation_document"
                " WHERE investigation_id = :id AND source_version_id = ANY(:floor)"
            ),
            {"id": where["id"], "floor": floor},
        ).scalars()
    )
    return [each for each in floor if each not in read]


def _filing_items(recorded: Any) -> tuple[str, ...]:
    """A version's recorded 8-K Items (`metadata.items`), none when not recorded."""
    items = cast(list[Any], recorded) if isinstance(recorded, list) else []
    return tuple(str(item) for item in items)


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


def claims_by_company(claims: Sequence[RowMapping]) -> list[CardCompanyClaims]:
    """The accepted Claims grouped by their subject company, companies in order of their first
    Claim, as the card lists them when the Editor failed."""
    grouped: dict[uuid.UUID, list[RowMapping]] = {}
    for claim in claims:
        grouped.setdefault(claim["subject_company_id"], []).append(claim)
    return [
        CardCompanyClaims(
            company_id=company,
            company_name=held[0]["subject_name"],
            claims=[
                CardClaimSummary(
                    claim_id=c["id"],
                    predicate=c["predicate"],
                    object=c["object_name"] or c["object_text"] or "",
                    layer=c["layer"],
                    source_version_id=c["source_version_id"],
                    source_title=c["source_title"],
                )
                for c in held
            ],
        )
        for company, held in grouped.items()
    ]


def _family(claim: RowMapping) -> str:
    """The claim's Evidence Family (a Source Version outside any family is its own)."""
    family = claim["evidence_family_id"]
    return f"family:{family}" if family is not None else f"version:{claim['source_version_id']}"


def card_finding(
    statement: str,
    cited: list[RowMapping],
    finding: Any,
    counterevidence: Mapping[uuid.UUID, list[uuid.UUID]] | None = None,
    *,
    grounded: bool | None = None,
    judged: bool | None = None,
    unjudged: bool = False,
) -> CardFinding:
    """A finding citing `cited` accepted Claims, with the independent contradictions
    (`counterevidence`: claim ID -> counterevidence IDs, atlas.investigations.skeptic) of any
    of them; `grounded` the grounding check's result (None: not checked); `judged` the finding
    judge's (True: supported; None: not judged), and `unjudged` when its judge call failed
    (the finding then needs review)."""
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
        or any(c["verification_status"] != "corroborated" for c in cited)
        or unjudged,
        open_questions=finding.open_questions,
        grounded=grounded,
        judged=judged,
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


def _step_of(key: str) -> ArgumentStep:
    """The argument step of a Reader task (`reader:<step>`)."""
    step = key.removeprefix("reader:")
    if step not in STEPS:
        raise RoleCallFailed(f"no argument step {step!r} for task {key!r}")
    return STEPS[step].key


def _step_refs(
    facts: ArgumentFacts, ref_of: Mapping[uuid.UUID, str], step: str
) -> tuple[list[str], list[str]]:
    """A step's Facts and the counterevidence against it (on the step, or against one of its
    Facts), by the Editor's references."""
    ids = {row["id"] for row in facts.supporting if row["step"] == step}
    counter = [
        ref_of[row["id"]]
        for row in facts.counter
        if row["step"] == step or set(facts.against.get(row["id"], [])) & ids
    ]
    return [ref_of[row["id"]] for row in facts.supporting if row["id"] in ids], counter


def _argument_item(ref: str, row: RowMapping, against: list[str]) -> ArgumentFactItem:
    value: dict[str, Any] = row["value_json"] if isinstance(row["value_json"], dict) else {}
    return ArgumentFactItem(
        ref=ref,
        step=row["step"],
        company=row["subject_name"],
        statement=str(value.get("statement", "")),
        status=str(value.get("status", "")),
        quantity=quantity_text(row),
        period=value.get("period"),
        source_title=row["source_title"],
        against=against,
    )


def _budget_detail(role: str, error: TokenBudgetExhausted) -> str:
    return (
        f"the run's token budget ran out before the {role}'s call"
        f" ({error.spent} of {error.budget} tokens spent)"
    )


def _json(value: dict[str, JsonValue]) -> str:
    return json.dumps(value)
