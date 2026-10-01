"""Running gold cases through Atlas: `atlas evaluate [--case ID] [--live]`.

Each case runs in isolation, through the same code paths as production:

1. **A fresh database** on the configured Postgres server: one database per run is migrated
   to head and used as the template of one database per case (`CREATE DATABASE ... TEMPLATE`,
   so the role needs `CREATEDB`); all are dropped when the run ends. A temporary directory
   holds the case's filesystem archive, its universe config (the case's entities, one theme)
   and, for recorded EDGAR responses, a fixture directory.
2. **Services** on localhost (`atlas.evaluation.stubs`): the SearXNG stub, and in fake mode
   the Hindsight stub (it recalls nothing) and the scripted LiteLLM. In live mode the
   configured LiteLLM answers instead (the model under evaluation), and the configured
   Hindsight holds a throwaway bank per case (`atlas-eval-<case>-<random>`) into which the
   case's sources are retained, through triage, before the pipeline runs, so recall is the
   real system's; the bank is deleted when the case ends. Until 2026-09-30 live mode used the
   empty stub too, which left memory and retrieval unmeasured (Codex review, item 1).
3. **The pipeline** the case names: its document sources recorded as manual imports (in
   publication order, `available_at` = the source's publication time), or its EDGAR responses
   ingested through the fixture path; then the jobs (`extract_claims`, `review_relationships`)
   or an investigation, run by single worker passes with the builtin handlers.
4. **Observation** through the read side (Claims, the edge table, Assertions and their spans,
   Evidence Families, as-of financial observations, the investigation), in the case's terms
   (entity and source keys), then **scoring** against the gold (`atlas.evaluation.scoring`).

A case passes when every check holds, no job failed and no stub saw an unexpected request.
"""

import json
import shutil
import tempfile
import time
import traceback
import uuid
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import JsonValue
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from atlas.archive import Archive, open_archive
from atlas.audit import Actor
from atlas.bank_template import BankTemplate, apply_template
from atlas.claims.extraction import EXTRACT_CLAIMS_KIND, extract_claims_payload
from atlas.claims.reads import list_claims
from atlas.companies import load_universe, seed
from atlas.db.migrate import upgrade
from atlas.evaluation.gold import Case, GoldError, GoldSet, LoadedCase
from atlas.evaluation.scoring import score
from atlas.evaluation.store import (
    CaseResult,
    Mode,
    finish_run,
    record_result,
    start_run,
)
from atlas.evaluation.stubs import (
    STUB_API_KEY,
    STUB_MODEL,
    ScriptContext,
    ScriptedLiteLLM,
    hindsight_stub,
    searxng_stub,
    serve,
)
from atlas.financials.reads import selected_observations
from atlas.hindsight import HindsightGateway
from atlas.investigations import Investigations, get_investigation
from atlas.investigations.model import Budgets
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from atlas.ledger.manual_import import import_document
from atlas.ledger.reads import get_version
from atlas.relationships.reads import get_relationship_detail, list_relationships
from atlas.relationships.review import REVIEW_RELATIONSHIPS_KIND
from atlas.runs import code_version
from atlas.settings import Settings

EVALUATION_BANK = "atlas-evaluation"
LIVE_OPT_IN = "ATLAS_LIVE_TESTS"
_PAGE = 1000


class EvaluationRefused(Exception):
    """The evaluation can't run as asked (a missing opt-in or provider, an unknown case)."""


@dataclass(frozen=True)
class RunOutcome:
    run_id: uuid.UUID
    results: list[CaseResult]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)


def evaluate(
    settings: Settings,
    gold: GoldSet,
    *,
    case_ids: list[str] | None = None,
    mode: Mode = "fake",
    report: Callable[[CaseResult], None] | None = None,
) -> RunOutcome:
    """Run the cases (default: every active one), store each result, and return them all."""
    if mode == "live" and not (settings.litellm_url and settings.litellm_api_key):
        raise EvaluationRefused(
            "a live evaluation needs the model: set ATLAS_LITELLM_URL and ATLAS_LITELLM_API_KEY"
        )
    if mode == "live" and not settings.hindsight_url:
        raise EvaluationRefused(
            "a live evaluation needs memory: set ATLAS_HINDSIGHT_URL (and ATLAS_HINDSIGHT_API_KEY)"
        )
    wanted = case_ids or gold.active_ids()
    unknown = [c for c in wanted if c not in {e.case_id for e in gold.manifest.cases}]
    if unknown:
        raise EvaluationRefused(f"no such case in the gold set: {', '.join(unknown)}")
    cases = [gold.load(case_id) for case_id in wanted]
    engine = create_engine(settings.database_url)
    run_id = start_run(
        engine,
        mode=mode,
        model=STUB_MODEL if mode == "fake" else settings.llm_role_model,
        code_version=code_version(settings),
        manifest_sha256=gold.manifest_sha256,
        case_ids=wanted,
        actor=settings.actor,
    )
    results: list[CaseResult] = []
    try:
        with _databases(settings.database_url, run_id) as new_database:
            for loaded in cases:
                result = _evaluate_case(settings, loaded, new_database(), mode)
                record_result(engine, run_id, result)
                results.append(result)
                if report is not None:
                    report(result)
    except BaseException as error:
        finish_run(engine, run_id, error=f"{type(error).__name__}: {error}"[:500])
        engine.dispose()
        raise
    finish_run(engine, run_id)
    engine.dispose()
    return RunOutcome(run_id, results)


# --- databases ----------------------------------------------------------------------------------


@contextmanager
def _databases(database_url: str, run_id: uuid.UUID) -> Generator[Callable[[], str]]:
    """A factory of fresh, migrated databases on the server of `database_url`; all dropped
    on exit."""
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    prefix = f"atlas_eval_{run_id.hex[:12]}"
    template = f"{prefix}_template"
    created: list[str] = []

    def url(name: str) -> str:
        return make_url(database_url).set(database=name).render_as_string(hide_password=False)

    def create(name: str, from_template: str | None = None) -> None:
        clause = f' TEMPLATE "{from_template}"' if from_template else ""
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"{clause}'))
        created.append(name)

    def new_database() -> str:
        name = f"{prefix}_{len(created)}"
        create(name, template)
        return url(name)

    try:
        create(template)
        upgrade(url(template))
        yield new_database
    finally:
        with admin.connect() as connection:
            for name in reversed(created):
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


# --- one case -----------------------------------------------------------------------------------


def _evaluate_case(base: Settings, loaded: LoadedCase, database_url: str, mode: Mode) -> CaseResult:
    case = loaded.case
    started = time.monotonic()
    workdir = Path(tempfile.mkdtemp(prefix=f"atlas-{case.case_id.lower()}-"))
    (workdir / "archive").mkdir()
    context = ScriptContext()
    errors: list[str] = []
    observed: dict[str, JsonValue] = {}
    try:
        with ExitStack() as stack:
            searxng = stack.enter_context(serve(searxng_stub))
            served = [searxng]
            if mode == "fake":
                hindsight = stack.enter_context(serve(hindsight_stub))
                served.append(hindsight)
                hindsight_url, bank = hindsight.url, EVALUATION_BANK
                llm = ScriptedLiteLLM(case.script, context, base.llm_aliases())
                served.append(stack.enter_context(serve(llm.handle)))
                litellm_url, litellm_key = served[-1].url, STUB_API_KEY
            else:
                hindsight_url = base.hindsight_url
                bank = f"atlas-eval-{case.case_id.lower()}-{uuid.uuid4().hex[:8]}"
                litellm_url, litellm_key = base.litellm_url, base.litellm_api_key
            settings = _case_settings(
                base,
                case,
                database_url,
                workdir,
                mode,
                hindsight_url=hindsight_url,
                hindsight_bank_id=bank,
                searxng_url=searxng.url,
                litellm_url=litellm_url,
                litellm_api_key=litellm_key,
            )
            engine = create_engine(database_url)
            stack.callback(engine.dispose)
            try:
                _run_pipeline(settings, loaded, engine, context, workdir, mode)
            except Exception as error:  # the case fails; its partial output is still scored
                errors.append(_describe(error))
            observed = _observe(settings, loaded, engine, context)
            errors.extend(f"stub: {e}" for each in served for e in each.errors)
            if mode == "live":
                try:
                    _delete_bank(settings)
                except Exception as error:
                    errors.append(f"bank {bank} not deleted: {_describe(error)}")
    except Exception as error:
        errors.append(_describe(error))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    checks = score(case, observed) if observed else []
    failed_jobs = [job for job in _jobs(observed) if job.get("status") != "succeeded"]
    errors.extend(f"job {job['kind']} {job['status']}: {job.get('error')}" for job in failed_jobs)
    scores: dict[str, float] = {}
    for metric in dict.fromkeys(check.metric for check in checks):
        mine = [check for check in checks if check.metric == metric]
        scores[metric] = round(sum(check.passed for check in mine) / len(mine), 4)
    return CaseResult(
        id=uuid.uuid4(),
        case_id=case.case_id,
        case_sha256=loaded.sha256,
        category=case.category,
        title=case.title,
        temporal_convention=case.temporal_convention,
        passed=bool(checks) and all(check.passed for check in checks) and not errors,
        scores=scores,
        checks=checks,
        predicted=observed,
        error="\n".join(errors)[:4000] or None,
        duration_ms=int((time.monotonic() - started) * 1000),
        evaluated_at=datetime.now(UTC),
    )


def _describe(error: Exception) -> str:
    frame = traceback.extract_tb(error.__traceback__)[-1:] if error.__traceback__ else []
    where = f" ({frame[0].filename.rsplit('/', 1)[-1]}:{frame[0].lineno})" if frame else ""
    return f"{type(error).__name__}: {error}{where}"


def _jobs(observed: dict[str, JsonValue]) -> list[dict[str, Any]]:
    jobs = observed.get("jobs")
    return [dict(job) for job in jobs if isinstance(job, dict)] if isinstance(jobs, list) else []


def _case_settings(
    base: Settings, case: Case, database_url: str, workdir: Path, mode: Mode, **services: Any
) -> Settings:
    themes = workdir / "themes.yaml"
    themes.write_text(yaml.safe_dump(_universe(case)), encoding="utf-8")
    values = base.model_dump()
    values.update(
        database_url=database_url,
        archive_backend="filesystem",
        archive_root=workdir / "archive",
        themes_config=themes,
        hindsight_version=None,
        # Live: the case's sources go through triage into its bank, as in production.
        retention_triage="off" if mode == "fake" else "auto",
        sec_live=False,
        sec_fixtures_dir=workdir / "edgar",
        sec_8k_items="*",
        sec_8k_exhibits_only_items="",
        backfill_window="",
        investigator_max_passages=200,
        investigator_passages_per_call=50,
        **services,
    )
    return Settings.model_validate(values)


def _universe(case: Case) -> dict[str, Any]:
    companies: dict[str, Any] = {}
    for entity in case.entities:
        if entity.cik is None:
            raise GoldError(f"{case.case_id}: entity {entity.key} needs a cik (source path sec)")
        companies[entity.key] = {
            "legal_name": entity.legal_name,
            "display_name": entity.display_name or entity.legal_name,
            "cik": entity.cik,
            "country": entity.country,
            "source_path": "sec",
            **({"layer": entity.layer} if entity.layer else {}),
        }
    keys = [entity.key for entity in case.entities]
    themes = {
        theme: {"title": f"Evaluation: {theme}", "description": case.title, "companies": keys}
        for theme in case.scope.themes
    }
    return {"version": 1, "name": "evaluation", "companies": companies, "themes": themes}


# --- the pipeline -------------------------------------------------------------------------------


def _delete_bank(settings: Settings) -> None:
    gateway = HindsightGateway.from_settings(settings)
    assert gateway is not None
    with gateway:
        gateway.delete_bank()


def _run_pipeline(
    settings: Settings,
    loaded: LoadedCase,
    engine: Engine,
    context: ScriptContext,
    workdir: Path,
    mode: Mode,
) -> None:
    case = loaded.case
    actor = Actor.from_settings(settings)
    universe = load_universe(settings.themes_config)
    with engine.begin() as connection:
        for seeded in seed(connection, actor, universe):
            context.companies[seeded.slug] = seeded.company_id
    gateway = HindsightGateway.from_settings(settings)
    assert gateway is not None
    with gateway:
        apply_template(engine, gateway, BankTemplate.load(settings.hindsight_template_path), actor)
    # Fake: recording sources makes no retain and no triage call (the stub recalls nothing).
    # Live: each source is retained into the case's bank, through triage, and those jobs
    # run to completion before the pipeline's, so recall sees the case's evidence.
    ledger_settings = (
        settings
        if mode == "live"
        else settings.model_copy(
            update={"hindsight_url": None, "litellm_url": None, "litellm_api_key": None}
        )
    )
    kind = case.pipeline.kind
    if kind == "financials":
        _ingest_edgar(ledger_settings, loaded, engine, context, workdir)
        return
    documents = sorted(
        (s for s in case.sources if s.kind == "document"), key=lambda s: s.clocks.published_at
    )
    for source in documents:
        if source.company is None:
            raise GoldError(f"{case.case_id}: document source {source.key} names no company")
        imported = import_document(
            ledger_settings,
            company=source.company,
            file=loaded.source_path(source.key),
            origin_url=source.origin_url,
            published_at=source.clocks.published_at,
            title=source.title,
            media_type=source.media_type,
        )
        context.versions[source.key] = imported.source_version_id
    queue = JobQueue(engine)
    if mode == "live":
        _drain(settings, queue)  # the sources' triage, retain and poll jobs
    key = f"evaluation:{case.case_id}"
    if kind == "relationships":
        read = case.pipeline.extract_sources or [s.key for s in documents]
        payload = extract_claims_payload([context.versions[k] for k in read])
        queue.enqueue(EXTRACT_CLAIMS_KIND, key, payload, max_attempts=1)
        _drain(settings, queue)
        queue.enqueue(REVIEW_RELATIONSHIPS_KIND, key, {}, max_attempts=1)
        _drain(settings, queue)
    elif kind == "investigation":
        seeds = case.pipeline.seeds or case.scope.companies
        Investigations(engine, queue).create(
            actor,
            universe,
            theme=case.scope.themes[0],
            question=case.question,
            seed_company_ids=[context.companies[s] for s in seeds],
            as_of=case.as_of or datetime.now(UTC),
            budgets=Budgets(
                max_rounds=2,
                max_leads=settings.investigation_max_leads,
                max_documents=settings.investigation_max_documents,
                token_budget=settings.run_token_budget,
            ),
            bank_id=settings.hindsight_bank_id,
        )
        _drain(settings, queue)


def _drain(settings: Settings, queue: JobQueue) -> None:
    Worker(queue, builtin_registry(settings)).run_once()


def _ingest_edgar(
    settings: Settings, loaded: LoadedCase, engine: Engine, context: ScriptContext, workdir: Path
) -> None:
    """The case's recorded EDGAR responses as a fixture directory, ingested for its company."""
    case = loaded.case
    (company,) = case.scope.companies
    root = workdir / "edgar" / company
    responses: list[dict[str, Any]] = []
    for source in case.sources:
        if source.kind != "edgar_response":
            continue
        parts = urlsplit(source.origin_url)
        relative = f"{parts.hostname}{parts.path}"
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(loaded.source_path(source.key), root / relative)
        responses.append(
            {
                "url": source.origin_url,
                "file": relative,
                "status": 200,
                "headers": {"content-type": source.media_type},
            }
        )
    (root / "manifest.json").write_text(json.dumps({"responses": responses}), encoding="utf-8")
    queue = JobQueue(engine)
    queue.enqueue(INGEST_KIND, f"evaluation:{case.case_id}", ingest_payload(company, None, None), 1)
    _drain(settings, queue)
    with engine.connect() as connection:
        for source in case.sources:
            version = connection.execute(
                text(
                    "SELECT v.id FROM source_version v JOIN source_document d"
                    " ON d.id = v.source_document_id WHERE d.canonical_url = :url"
                    " ORDER BY v.available_at DESC, v.id LIMIT 1"
                ),
                {"url": source.origin_url},
            ).scalar_one_or_none()
            if version is not None:
                context.versions[source.key] = version


# --- observation --------------------------------------------------------------------------------


def _observe(
    settings: Settings, loaded: LoadedCase, engine: Engine, context: ScriptContext
) -> dict[str, JsonValue]:
    case = loaded.case
    archive = open_archive(settings)
    entity = context.entity_key
    sources = {str(v): k for k, v in context.versions.items()}

    def source_key(version_id: object) -> str | None:
        return None if version_id is None else sources.get(str(version_id), str(version_id))

    observed: dict[str, JsonValue] = {}
    with engine.connect() as connection:
        claims, _ = list_claims(connection, limit=_PAGE, offset=0)
        observed["claims"] = [
            {
                "subject": entity(str(c.subject_company_id)),
                "predicate": c.predicate,
                "object": entity(str(c.object_company_id)) if c.object_company_id else None,
                "object_text": c.object_text,
                "layer": c.layer,
                "quote": c.quote,
                "source": source_key(c.source_version_id),
                "outcome": c.outcome,
                "reason_code": c.reason_code,
            }
            for c in claims
        ]
        edges, _ = list_relationships(connection, limit=_PAGE, offset=0)
        relationships: list[JsonValue] = []
        for edge in edges:
            detail = get_relationship_detail(connection, edge.id)
            evidence: list[JsonValue] = []
            for each in detail.evidence if detail is not None else []:
                evidence.append(
                    {
                        "source": source_key(each.assertion.source_version_id),
                        "quote": each.assertion.quote,
                    }
                )
            relationships.append(
                {
                    "subject": entity(str(edge.subject_company_id)),
                    "predicate": edge.predicate,
                    "object": entity(str(edge.object_company_id))
                    if edge.object_company_id
                    else None,
                    "object_text": edge.object_text,
                    "layer": edge.layer,
                    "review_state": edge.review_state,
                    "reasons": list[JsonValue](edge.review_reasons),
                    "evidence": evidence,
                }
            )
        observed["relationships"] = relationships
        observed["assertions"] = _assertions(connection, archive, entity, source_key)
        families: dict[str, JsonValue] = {}
        for key, version_id in context.versions.items():
            version = get_version(connection, version_id)
            family = version.evidence_family if version is not None else None
            families[key] = str(family.evidence_family_id) if family is not None else None
        observed["families"] = families
        observed["financials"] = [
            _financial(connection, context, gold) for gold in case.gold.financials
        ]
        investigation_id = connection.execute(
            text("SELECT id FROM investigation ORDER BY created_at LIMIT 1")
        ).scalar_one_or_none()
        if investigation_id is not None:
            found = get_investigation(connection, investigation_id, queue_paused=False)
            assert found is not None
            card = found.research_card
            observed["investigation"] = {
                "status": found.status,
                "stop_reason": found.stop_reason,
                "stop_detail": found.stop_detail,
                "documents": [source_key(d.source_version_id) for d in found.documents],
                "findings": [
                    {
                        "claim_text": f.claim_text,
                        "entities": [entity(str(e)) for e in f.entity_ids],
                        "counterevidence": len(f.counterevidence_ids),
                    }
                    for f in (card.findings if card is not None else [])
                ],
                "contradictions": [
                    {
                        "independent": c.independent,
                        "source": source_key(c.source_span.source_version_id),
                    }
                    for c in (card.contradictions if card is not None else [])
                ],
                "counterevidence": [
                    {
                        "outcome": c.outcome,
                        "kind": c.kind,
                        "source": source_key(c.source_version_id),
                        "independent": c.independent,
                        "reason_code": c.reason_code,
                    }
                    for c in found.counterevidence
                ],
            }
        observed["jobs"] = [
            {"kind": row.kind, "status": row.status, "error": row.last_error}
            for row in connection.execute(
                text("SELECT kind, status, last_error FROM job ORDER BY created_at, id")
            )
        ]
    return observed


def _assertions(
    connection: Any, archive: Archive, entity: Callable[[str | None], str | None], source_key: Any
) -> list[JsonValue]:
    rows = connection.execute(
        text(
            "SELECT a.subject_company_id, a.predicate, a.object_company_id, a.quote,"
            " a.span_start, a.span_end, a.source_version_id, p.parsed_object_uri"
            " FROM assertion a LEFT JOIN source_version_parse p"
            " ON p.source_version_id = a.source_version_id AND p.parser_version = a.parser_version"
            " ORDER BY a.extracted_at, a.id"
        )
    ).all()
    parsed: dict[str, str | None] = {}
    found: list[JsonValue] = []
    for row in rows:
        uri = row.parsed_object_uri
        if uri is not None and uri not in parsed:
            try:
                parsed[uri] = archive.get(uri).decode("utf-8")
            except Exception:  # an unreadable parse: the span can't resolve
                parsed[uri] = None
        body = parsed.get(uri) if uri is not None else None
        found.append(
            {
                "subject": entity(str(row.subject_company_id)),
                "predicate": row.predicate,
                "object": entity(str(row.object_company_id)) if row.object_company_id else None,
                "source": source_key(row.source_version_id),
                "quote": row.quote,
                "resolves": body is not None and body[row.span_start : row.span_end] == row.quote,
            }
        )
    return found


def _financial(connection: Any, context: ScriptContext, gold: Any) -> JsonValue:
    """The as-of observation of the gold's period key, or None."""
    (company_id,) = context.companies.values() if len(context.companies) == 1 else (None,)
    if company_id is None:
        return None
    for observation in selected_observations(
        connection, company_id, gold.as_of, concept=gold.concept, unit=gold.unit
    ):
        if (
            observation.period_end == gold.period_end
            and observation.period_start == gold.period_start
        ):
            return {
                "as_of": gold.as_of.isoformat(),
                "value": str(observation.value),
                "accession": observation.accession,
                "linkage": observation.linkage,
                "available_at": observation.available_at.isoformat(),
            }
    return {"as_of": gold.as_of.isoformat(), "value": None}
