"""Live verification of every Phase 3-6a part (ticket 32): small, bounded, and reported.

**Opt-in and never in CI.** It needs the `live` marker *and* `ATLAS_LIVE_TESTS` (`1`: live,
`rehearse`: every part against the fakes on localhost); without it every part is skipped.
Run it with `scripts/live-verify.sh` (`docs/runbooks.md`, "Live verification"), which
chooses the parts (`ATLAS_LIVE_VERIFY_PARTS`), the companies (`ATLAS_LIVE_VERIFY_COMPANIES`)
and the filings per company (`ATLAS_LIVE_VERIFY_LIMIT`).

One run has one throwaway app database and archive, and one throwaway Hindsight bank (the
stack of `tests/live/stack.py`: the cluster's or the Compose Hindsight, the bank deleted at
the end unless kept). The template is applied once and the universe (the repo's plus NVIDIA,
which the Coherent 10-K names) seeded. Each part is one test, in this order:

1. `sec`: live SEC ingest of each company's `--limit` recent filings, triage on (MiniMax),
   the selected sections retained, consolidation waited for, then a cross-company recall
   and one reflect with its citations resolved.
2. `exchanges`: the FCA NSM (IQE) and the AMF (Soitec): discovery and one document each
   through the fetch gate (retention off), with the gate's decisions.
3. `tradingview`: ticket 31's `tradingview_catalog` for the first selected company with a
   `tradingview_symbol` (documents and news, at most two tool calls a job), then the
   `tradingview_transcripts` job it enqueues (at most two transcripts, archived, not
   retained). Skipped, saying what to do, unless `ATLAS_TRADINGVIEW_ENABLED` is set with a
   token (`atlas tradingview login`'s token file); a rehearsal serves the TradingView fake.
4. `discovery`: the Scout (MiniMax) and SearXNG give leads; the mention extractor and live
   entity resolution (SEC, GLEIF, OpenFIGI) give Candidates. Skipped without SearXNG.
5. `relationships`: the Investigator on the recorded Coherent FY2026 10-K (supplier-rich),
   then the Reviewer (MiniMax): machine-reviewed or exception edges.
6. `investigation`: Scout -> Investigators (Coherent, Lumentum) -> Skeptic || Financial
   Analyst -> Editor to a stop, a Hypothesis draft, a scenario recomputed byte-identically,
   and publishing version 1 behind the gate: the harness approves the edges the version
   depends on as the owner step (recorded as such), then reads the Research Snapshot back.
7. `identity`: `atlas companies resolve` for two companies; the pending reviews listed.

**Caps.** Atlas reaches LiteLLM and Hindsight only through `CappedProxy`s
(`tests/live/verify.py`), which refuse any chat completion or retain batch beyond the part's
budget or the run's cap (40 chat completions, 25 retain operations): the part is then
aborted. Settings bound the rest (triage batches, `--max-retains`, run token budgets,
passages, queries, leads and documents). Each part's usage is reported from the proxies and
from what the database recorded (`llm_call`, `role_call`, `hindsight_operation`).

The report (`results.json`, `summary.md`) goes to `ATLAS_LIVE_RESULTS_DIR`. A rehearsal's
answers are scripted (`RehearsalModel`), so it checks the harness, never a model.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from atlas.api.app import create_app
from atlas.companies import load_universe
from atlas.db.migrate import upgrade
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from atlas.llm_routes import LiteLLMError, LiteLLMRoutes
from atlas.settings import Settings
from atlas.tradingview import TokenSet, write_token_file
from tests.fakes.identity import FakeIdentitySources
from tests.fakes.litellm import ChatReply
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.fakes.tradingview import ACCESS_TOKEN as TV_ACCESS_TOKEN
from tests.fakes.tradingview import SYMBOLS as TV_SYMBOLS
from tests.fakes.tradingview import FakeTradingView
from tests.live.stack import REFUSED, REPO, LiveStack, Refused, live_mode, live_stack
from tests.live.verify import (
    DISCOVERY_QUERY,
    INVESTIGATION_QUERY,
    NOT_SELECTED,
    PART_BUDGETS,
    PARTS,
    RUN_CHAT_CAP,
    RUN_RETAIN_CAP,
    CapExceeded,
    CappedProxy,
    RehearsalModel,
    VerifyReport,
    as_dict,
    as_list,
    is_chat_completion,
    is_retain,
)

THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"
SITES = REPO / "configs" / "sources" / "sites.yaml"
TEMPLATE = REPO / "configs" / "hindsight" / "bank-template.json"
METRICS = REPO / "configs" / "financials" / "metrics.yaml"
FIXTURES = REPO / "tests" / "fixtures"
EDGAR_FIXTURES = FIXTURES / "edgar"
EXCHANGE_FIXTURES = {"iqe": FIXTURES / "fca-nsm", "soitec": FIXTURES / "amf"}
DEFAULT_COMPANIES = "lumentum,coherent,axt,applied-optoelectronics"
DEFAULT_LIMIT = 2
DEFAULT_ROLE_MODEL = "MiniMax-M3"
REHEARSAL_UA = "Atlas Research ops@example.com"  # not a real contact
# The recorded supplier-rich filing (NVIDIA supply agreement) the relationships part reads.
COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
IDENTITY_COMPANIES = ("lumentum", "coherent")
INVESTIGATION_SEEDS = ("coherent", "lumentum")
DISCOVERY_QUESTION = "Who can supply EML lasers for 1.6T AI data-center transceivers?"
INVESTIGATION_QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?"
RUN_TOKEN_BUDGET = 150_000  # per run (an extraction, a discovery, the investigation)
FINAL_STATES = {"completed", "zero_fact", "linked"}


def _env_list(name: str, default: str) -> list[str]:
    return [each.strip() for each in (os.environ.get(name) or default).split(",") if each.strip()]


def _selected_parts() -> list[str]:
    parts = _env_list("ATLAS_LIVE_VERIFY_PARTS", ",".join(PARTS))
    unknown = [p for p in parts if p not in PARTS]
    assert not unknown, f"unknown parts {unknown}: choose from {', '.join(PARTS)}"
    return parts


# --- the run ----------------------------------------------------------------------------------


class Verify:
    """One verification run: the stack, the capped proxies, a fresh database and archive, the
    CLI, worker passes with each part's settings, the API and the report."""

    def __init__(
        self,
        stack: LiveStack,
        report: VerifyReport,
        llm: CappedProxy,
        llm_served: Served,
        hindsight: CappedProxy,
        hindsight_served: Served,
        database_url: str,
        tmp_path: Path,
        model: RehearsalModel | None,
        searxng_url: str | None,
        identity_url: str | None,
        tradingview_url: str | None = None,
    ) -> None:
        self.stack = stack
        self.report = report
        self.llm, self.llm_url = llm, llm_served.url
        self.hindsight, self.hindsight_url = hindsight, hindsight_served.url
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.archive = tmp_path / "archive"
        self.archive.mkdir(exist_ok=True)
        self.themes = _themes(tmp_path)
        self.model = model
        self.searxng_url = searxng_url
        self.identity_url = identity_url
        self.tradingview_url = tradingview_url  # the served fake, in a rehearsal only
        self.selected = _selected_parts()
        self.companies = _env_list("ATLAS_LIVE_VERIFY_COMPANIES", DEFAULT_COMPANIES)
        self.limit = int(os.environ.get("ATLAS_LIVE_VERIFY_LIMIT") or DEFAULT_LIMIT)
        self.role_model = os.environ.get("ATLAS_LLM_ROLE_MODEL") or DEFAULT_ROLE_MODEL
        self.sec_user_agent = (
            REHEARSAL_UA if self.rehearsing else os.environ.get("ATLAS_SEC_USER_AGENT") or None
        )
        self.part_deadline = float(os.environ.get("ATLAS_LIVE_PART_DEADLINE_SECONDS") or 1800)
        self.engine: Engine = create_engine(database_url)
        self.api = TestClient(create_app(self.settings()))
        self._part_started: Any = None

    @property
    def rehearsing(self) -> bool:
        return self.stack.rehearsal is not None

    # settings, CLI, worker

    def settings(self, **overrides: Any) -> Settings:
        stack = self.stack
        values: dict[str, Any] = {
            "database_url": self.database_url,
            "actor": "live-verify",
            "archive_root": self.archive,
            "themes_config": self.themes,
            "source_sites_config": SITES,
            "financial_metrics_config": METRICS,
            "hindsight_url": self.hindsight_url,
            "hindsight_api_key": stack.hindsight_api_key,
            "hindsight_version": os.environ.get("ATLAS_LIVE_HINDSIGHT_VERSION") or None,
            "hindsight_bank_id": stack.bank_id,
            "hindsight_template_path": TEMPLATE,
            "litellm_url": self.llm_url,
            "litellm_api_key": stack.litellm_api_key,
            "llm_extract_alias": stack.extract_alias,
            "llm_reflect_alias": stack.reflect_alias,
            "llm_role_model": self.role_model,
            "retain_poll_timeout_seconds": stack.poll_timeout_seconds,
            "retain_poll_interval_seconds": stack.poll_interval_seconds,
            "retain_poll_attempts": stack.poll_attempts,
            "retention_triage": "off",
            "triage_sections_per_call": 30,
            "backfill_window": "",
            "run_token_budget": RUN_TOKEN_BUDGET,
            "investigator_max_passages": 8,
            "investigator_passages_per_call": 8,
            "reviewer_assertions_per_call": 10,
            "discovery_max_queries": 3,
            "investigation_max_leads": 5,
            "investigation_max_documents": 6,
            "exchange_user_agent": os.environ.get("ATLAS_EXCHANGE_USER_AGENT") or "AtlasResearch",
            "searxng_url": self.searxng_url,
            "sec_user_agent": self.sec_user_agent,
            **self._identity_urls(),
        }
        return Settings.model_validate(values | overrides)

    def fixture_settings(self) -> dict[str, Any]:
        """Recorded EDGAR filings and no retention: nothing reaches SEC or Hindsight."""
        return {"sec_fixtures_dir": EDGAR_FIXTURES, "sec_live": False, "hindsight_url": None}

    def _identity_urls(self) -> dict[str, str]:
        url = self.identity_url
        if url is None:
            return {}
        return {
            "sec_files_url": f"{url}/files",
            "sec_data_url": url,
            "gleif_url": f"{url}/api/v1",
            "openfigi_url": url,
        }

    def cli(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        base = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp_path),
            "ATLAS_DATABASE_URL": self.database_url,
            "ATLAS_ACTOR": "live-verify",
            "ATLAS_ARCHIVE_ROOT": str(self.archive),
            "ATLAS_THEMES_CONFIG": str(self.themes),
            "ATLAS_SOURCE_SITES_CONFIG": str(SITES),
            "ATLAS_FINANCIAL_METRICS_CONFIG": str(METRICS),
            "ATLAS_HINDSIGHT_URL": self.hindsight_url,
            "ATLAS_HINDSIGHT_BANK_ID": self.stack.bank_id,
            "ATLAS_HINDSIGHT_TEMPLATE_PATH": str(TEMPLATE),
        }
        if self.stack.hindsight_api_key:
            base["ATLAS_HINDSIGHT_API_KEY"] = self.stack.hindsight_api_key
        return subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=self.tmp_path,
            env=base | env,
            capture_output=True,
            text=True,
            timeout=900,
        )

    def enqueue(self, *args: str) -> str:
        enqueued = self.cli(*args)
        assert enqueued.returncode == 0, enqueued.stderr
        return json.loads(enqueued.stdout)["id"]

    def drain(self, settings: Settings, deadline: float | None = None) -> float:
        """Worker passes with `settings` until no job is queued or running (waiting out
        pauses), a proxy refuses over a cap (`CapExceeded`), or the deadline passes."""
        limit = deadline or self.part_deadline
        started = time.monotonic()
        while True:
            queue = JobQueue(self.engine, pacing=Pacing.from_settings(settings))
            ran = Worker(queue, builtin_registry(settings)).run_once()
            self.check_caps()
            pending = [
                k for k in self.get("/api/v1/queue")["pending"] if k["queued"] or k["running"]
            ]
            if not pending:
                return time.monotonic() - started
            if time.monotonic() - started > limit:
                raise AssertionError(f"jobs still pending after {round(limit)} s: {pending}")
            if ran == 0:
                time.sleep(self.stack.idle_sleep_seconds or 0.05)

    def check_caps(self) -> None:
        for proxy in (self.llm, self.hindsight):
            if proxy.refusals:
                raise CapExceeded(
                    f"{proxy.name} cap reached: {len(proxy.refusals)} request(s) refused"
                    f" ({proxy.part_count}/{proxy.part_cap} this part)"
                )

    def abandon_pending(self, reason: str) -> int:
        """Fail every job still queued (without retry), so nothing spills into the next part."""
        queue = JobQueue(self.engine)
        queue.clear_pause()
        abandoned = 0
        while (job := queue.claim("live-verify-cleanup", _lease())) is not None:
            queue.fail(job, "live-verify-cleanup", reason, retry=False)
            abandoned += 1
        return abandoned

    # API

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, f"GET {path}: {response.status_code} {response.text}"
        return response.json()

    def post(self, path: str, body: dict[str, Any], expect: int) -> Any:
        response = self.api.post(path, json=body)
        assert response.status_code == expect, (
            f"POST {path}: {response.status_code} {response.text}"
        )
        return response.json()

    def company(self, slug: str) -> dict[str, Any]:
        companies = self.get("/api/v1/companies", limit=200)["items"]
        return next(company for company in companies if company["slug"] == slug)

    def job(self, job_id: str) -> dict[str, Any]:
        return self.get(f"/api/v1/jobs/{job_id}")

    def versions(self, slug: str) -> list[dict[str, Any]]:
        company = self.company(slug)
        documents = self.get(f"/api/v1/companies/{company['id']}/sources", limit=200)["items"]
        versions: list[dict[str, Any]] = []
        for document in documents:
            for summary in self.get(f"/api/v1/sources/{document['id']}/versions")["items"]:
                versions.append(self.get(f"/api/v1/source-versions/{summary['id']}"))
        return versions

    def ingest_fixtures(self, *slugs: str) -> dict[str, str]:
        """The recorded EDGAR filings of `slugs`, with retention off (idempotent)."""
        jobs: dict[str, str] = {}
        for slug in slugs:
            jobs[slug] = self.enqueue("ingest", "--company", slug, "--key", f"fixtures-{slug}")
        self.drain(self.settings(**self.fixture_settings()))
        for slug, job_id in jobs.items():
            job = self.job(job_id)
            assert job["status"] == "succeeded", (slug, job.get("failures"))
        return {slug: self.job(job_id)["status"] for slug, job_id in jobs.items()}

    # parts

    def part(self, name: str) -> Any:
        """The part's report context; skips an unselected part and sets its caps."""
        if name not in self.selected:
            self.report.parts[name] = {
                "status": "skipped",
                "reason": NOT_SELECTED,
                "budget": vars(PART_BUDGETS[name]),
                "numbers": {},
            }
            pytest.skip(NOT_SELECTED)
        budget = PART_BUDGETS[name]
        self.llm.begin_part(name, budget.chat_calls)
        self.hindsight.begin_part(name, budget.retain_operations)
        with self.engine.connect() as connection:
            self._part_started = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        return _PartContext(self, name)

    def usage(self) -> dict[str, Any]:
        """This part's calls: the proxies' counts and what the database recorded since it began."""
        since = {"since": self._part_started}
        with self.engine.connect() as connection:
            llm = connection.execute(
                text(
                    "SELECT count(*) AS calls, coalesce(sum(tokens_in), 0) AS tokens_in,"
                    " coalesce(sum(tokens_out), 0) AS tokens_out FROM llm_call"
                    " WHERE called_at >= :since"
                ),
                since,
            ).one()
            roles = connection.execute(
                text(
                    "SELECT role, status, count(*) FROM role_call WHERE started_at >= :since"
                    " GROUP BY role, status ORDER BY role, status"
                ),
                since,
            ).all()
            operations = connection.execute(
                text(
                    "SELECT kind, status, count(*) FROM hindsight_operation"
                    " WHERE submitted_at >= :since GROUP BY kind, status ORDER BY kind, status"
                ),
                since,
            ).all()
        return {
            "chat_calls": self.llm.part_count,
            "chat_calls_refused": len(self.llm.refusals),
            "retain_operations": self.hindsight.part_count,
            "retain_operations_refused": len(self.hindsight.refusals),
            "llm_calls_recorded": int(llm.calls),
            "tokens_in": int(llm.tokens_in),
            "tokens_out": int(llm.tokens_out),
            "role_calls": {f"{role}:{status}": int(count) for role, status, count in roles},
            "hindsight_operations_recorded": {
                f"{kind}:{status}": int(count) for kind, status, count in operations
            },
            "hindsight_requests": dict(self.hindsight.routes),
        }

    def close(self) -> None:
        self.api.close()
        self.engine.dispose()


class _PartContext:
    def __init__(self, verify: Verify, name: str) -> None:
        self.verify, self.name = verify, name
        self._context: Any = None

    def __enter__(self) -> dict[str, Any]:
        self._context = self.verify.report.part(self.name, self.verify.usage)
        return self._context.__enter__()

    def __exit__(self, *exc: Any) -> bool | None:
        try:
            return self._context.__exit__(*exc)
        finally:
            if exc[0] is not None and not isinstance(exc[1], pytest.skip.Exception):
                self.verify.abandon_pending(f"live-verify: part {self.name} ended")


def _lease() -> Any:
    from datetime import timedelta

    return timedelta(minutes=5)


def _themes(tmp_path: Path) -> Path:
    """The repo's universe plus NVIDIA, which the Coherent 10-K names (its entity tags)."""
    universe = yaml.safe_load(THEMES.read_text(encoding="utf-8"))
    universe["companies"]["nvidia"] = {
        "legal_name": "NVIDIA Corporation",
        "display_name": "NVIDIA",
        "cik": "0001045810",
        "country": "US",
        "source_path": "sec",
    }
    path = tmp_path / "themes.yaml"
    path.write_text(yaml.safe_dump(universe), encoding="utf-8")
    return path


# --- fixtures ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def verify(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Verify]:
    mode = live_mode()
    assert mode is not None  # tests/live/conftest.py skips every part otherwise
    report = VerifyReport(mode, _selected_parts())
    results = os.environ.get("ATLAS_LIVE_RESULTS_DIR")
    with ExitStack() as exits:
        if results:
            exits.callback(lambda: report.write(Path(results)))
        stack = exits.enter_context(live_stack(mode))
        model: RehearsalModel | None = None
        searxng_url = os.environ.get("ATLAS_SEARXNG_URL") or None
        identity_url: str | None = None
        tradingview_url: str | None = None
        if stack.rehearsal is not None:
            model = RehearsalModel()
            stack.rehearsal.llm.script_chat(
                *[ChatReply.answer(model.answer, tokens=(1000, 100))] * (RUN_CHAT_CAP + 10)
            )
            searxng = FakeSearXNG()
            searxng.script(DISCOVERY_QUERY, SearchReply.of("unseeded-companies"))
            searxng.script(INVESTIGATION_QUERY, SearchReply.of("inp-substrate-capacity"))
            searxng_served = exits.enter_context(serve(searxng.handle))
            exits.callback(searxng_served.raise_errors)
            identity_served = exits.enter_context(serve(FakeIdentitySources().handle))
            exits.callback(identity_served.raise_errors)
            tradingview_served = exits.enter_context(serve(FakeTradingView().handle))
            exits.callback(tradingview_served.raise_errors)
            searxng_url, identity_url = searxng_served.url, identity_served.url
            tradingview_url = tradingview_served.url
        try:
            checked = stack.preflight()
            role_model = os.environ.get("ATLAS_LLM_ROLE_MODEL") or DEFAULT_ROLE_MODEL
            if stack.rehearsal is None:
                checked["role_model_routes"] = _role_model_routes(stack, role_model)
            checked["role_model"] = role_model
        except Refused as error:
            report.refused = str(error)
            pytest.exit(f"live verification refused: {error}", returncode=REFUSED)
        report.stack = checked
        # --max-chat-calls may lower the run's cap on chat completions, never raise it.
        cap = os.environ.get("ATLAS_LIVE_VERIFY_MAX_CHAT_CALLS") or str(RUN_CHAT_CAP)
        report.chat_cap = min(RUN_CHAT_CAP, int(cap))
        llm = CappedProxy("LiteLLM chat", stack.litellm_url, is_chat_completion, report.chat_cap)
        hindsight = CappedProxy("Hindsight retain", stack.hindsight_url, is_retain, RUN_RETAIN_CAP)
        exits.callback(llm.close)
        exits.callback(hindsight.close)
        llm_served = exits.enter_context(serve(llm.handle))
        hindsight_served = exits.enter_context(serve(hindsight.handle))
        exits.callback(llm_served.raise_errors)
        exits.callback(hindsight_served.raise_errors)
        database_url = exits.enter_context(stack.fresh_database())
        upgrade(database_url)
        if stack.keep_database:
            report.stack["database"] = database_url.rsplit("/", 1)[-1]
        harness = Verify(
            stack,
            report,
            llm,
            llm_served,
            hindsight,
            hindsight_served,
            database_url,
            tmp_path_factory.mktemp("verify"),
            model,
            searxng_url,
            identity_url,
            tradingview_url,
        )
        exits.callback(harness.close)
        hindsight.begin_part("setup", 0)
        applied = harness.cli("hindsight", "apply-template")
        assert applied.returncode == 0, applied.stderr
        report.extra["template"] = json.loads(applied.stdout)
        seeded = harness.cli("companies", "seed")
        assert seeded.returncode == 0, seeded.stderr
        yield harness
        if stack.rehearsal is None and set(harness.selected) & {"sec"}:
            try:
                report.extra["hindsight_llm_usage"] = stack.llm_usage()
            except Exception as error:
                report.extra["hindsight_llm_usage"] = f"unavailable: {type(error).__name__}"


def _role_model_routes(stack: LiveStack, model: str) -> list[dict[str, Any]]:
    try:
        with LiteLLMRoutes(stack.litellm_url, stack.litellm_api_key) as litellm:
            routes = litellm.routes([model])
    except LiteLLMError as error:
        raise Refused(f"LiteLLM: the role model {model!r}: {error} (set --model)") from None
    return [each.model_dump(mode="json") for each in routes[model]]


# --- 1. SEC live -----------------------------------------------------------------------------


def test_part_1_sec_ingest_triage_retain_recall_and_reflect(verify: Verify) -> None:
    with verify.part("sec") as record:
        numbers: dict[str, Any] = record["numbers"]
        universe = load_universe(verify.themes)
        sec = [s for s in verify.companies if s in universe.companies]
        numbers["not_configured"] = [s for s in verify.companies if s not in universe.companies]
        numbers["not_sec"] = [s for s in sec if universe.companies[s].source_path != "sec"]
        sec = [s for s in sec if universe.companies[s].source_path == "sec"]
        overrides: dict[str, Any] = {"retention_triage": "on"}
        if verify.rehearsing:
            recorded = {p.name for p in EDGAR_FIXTURES.iterdir() if p.is_dir()}
            numbers["no_fixtures_in_rehearsal"] = [s for s in sec if s not in recorded]
            sec = [s for s in sec if s in recorded]
            overrides |= {"sec_fixtures_dir": EDGAR_FIXTURES, "sec_live": False}
        else:
            assert verify.sec_user_agent, "set ATLAS_SEC_USER_AGENT (SEC's fair-access policy)"
            overrides |= {"sec_live": True}
        assert sec, "no SEC company selected (--companies)"
        # Each retained version may cost two operations (retain, one reprocess).
        max_retains = max(1, min(verify.limit * 2, RUN_RETAIN_CAP // 2 // len(sec)))
        numbers |= {"companies": sec, "limit": verify.limit, "max_retains_per_company": max_retains}
        settings = verify.settings(**overrides)
        jobs = {
            slug: verify.enqueue(
                "ingest",
                "--company",
                slug,
                "--limit",
                str(verify.limit),
                "--max-retains",
                str(max_retains),
                "--key",
                f"verify-sec-{slug}",
            )
            for slug in sec
        }
        numbers["drain_seconds"] = round(
            verify.drain(settings, deadline=verify.stack.retain_deadline_seconds)
        )
        numbers["ingest_jobs"] = {slug: verify.job(j)["status"] for slug, j in jobs.items()}
        companies: dict[str, Any] = {}
        completed: dict[str, str] = {}  # slug -> one completed section's document ID
        for slug in sec:
            versions = verify.versions(slug)
            company = verify.company(slug)
            triage = verify.get("/api/v1/triage", company_id=company["id"], limit=500)["items"]
            sections: dict[str, int] = {}
            facts = 0
            for version in versions:
                memory = verify.get(f"/api/v1/source-versions/{version['id']}/memory")
                for document in memory["documents"]:
                    state = document["retain_state"]
                    sections[state] = sections.get(state, 0) + 1
                    facts += document["fact_count"] or 0
                    if state == "completed":
                        completed.setdefault(slug, document["document_id"])
            companies[slug] = {
                "versions": [
                    {
                        "form": v["source_document"]["form_type"],
                        "url": v["source_document"]["canonical_url"],
                        "parse_status": v["parse_status"],
                        "available_at": v["available_at"],
                    }
                    for v in versions
                ],
                "triage": _count(triage, "decision"),
                "triage_methods": _count(triage, "method"),
                "sections": sections,
                "facts": facts,
            }
        numbers["by_company"] = companies
        for slug, job_id in jobs.items():
            job = verify.job(job_id)
            assert job["status"] == "succeeded", (slug, job.get("failures"))
        assert completed, "no section was retained with facts"

        consolidation = verify.stack.wait_for_consolidation(list(completed.values()))
        numbers["consolidation"] = consolidation
        observation = (consolidation.get("observation_ids") or [None])[0]
        ids = {verify.company(slug)["id"]: slug for slug in sec}
        names = ", ".join(verify.company(slug)["display_name"] for slug in sec)
        recalled = verify.post(
            "/api/v1/memory/recall",
            {
                "query": f"{names}: products, customers, suppliers and capacity",
                "scope": {"company_ids": list(ids)},
            },
            200,
        )
        numbers["recall"] = {
            "memories": len(recalled["memories"]),
            "counts": recalled.get("counts"),
            "by_company": _count(
                [
                    {"company": ids.get(s["company_id"], "?")}
                    for m in recalled["memories"]
                    for s in m["provenance"]["sources"]
                ],
                "company",
            ),
            "provenance": _count([m["provenance"] for m in recalled["memories"]], "state"),
        }
        verify.stack.before_reflect(list(completed.values()), observation)
        accepted = verify.post(
            "/api/v1/memory/reflect",
            {
                "question": (
                    f"Using only the filings in memory for {names}: for each company, state its"
                    " most recent reporting period and one fact it reported about its business,"
                    " supported by a short passage quoted verbatim in double quotes."
                ),
                "scope": {"company_ids": list(ids)},
            },
            202,
        )
        verify.drain(settings)
        answer = verify.get(f"/api/v1/memory/reflect/{accepted['research_answer']['id']}")
        citations: list[dict[str, Any]] = as_list(answer.get("citations"))
        numbers["reflect"] = {
            "status": answer["status"],
            "error": answer["error"],
            "counts": answer["counts"],
            "by_kind_and_state": _count(
                [{"k": f"{c['kind']}:{c['state']}"} for c in citations], "k"
            ),
            "companies_cited": sorted(
                {ids.get(str(e["company_id"]), "?") for e in as_list(answer.get("evidence"))}
            ),
            "unverified": [
                {"kind": c["kind"], "reason": c["reason"], "text": c["text"][:160]}
                for c in citations
                if c["state"] == "unverified"
            ],
            "answer": (answer["answer"] or "")[:1500],
        }
        assert answer["status"] == "completed", answer["error"]
        assert as_dict(answer["counts"]).get("broken", 0) == 0, "broken citations"


# --- 2. Exchanges live ------------------------------------------------------------------------


def test_part_2_exchanges_discovery_and_one_document_each_through_the_fetch_gate(
    verify: Verify,
) -> None:
    with verify.part("exchanges") as record:
        numbers: dict[str, Any] = record["numbers"]
        for slug in ("iqe", "soitec"):
            overrides: dict[str, Any] = {"hindsight_url": None}  # archived, not retained
            if verify.rehearsing:
                overrides["exchange_fixtures_dir"] = EXCHANGE_FIXTURES[slug]
            else:
                overrides["exchange_live"] = True
            job_id = verify.enqueue(
                "ingest", "--company", slug, "--limit", "1", "--key", f"verify-exchange-{slug}"
            )
            verify.drain(verify.settings(**overrides))
            job = verify.job(job_id)
            company = verify.company(slug)
            decisions = verify.get(
                f"/api/v1/companies/{company['id']}/fetch-gate-decisions", limit=200
            )["items"]
            versions = verify.versions(slug)
            numbers[slug] = {
                "job": job["status"],
                "failures": job.get("failures"),
                "counts": as_dict(job.get("artifacts")).get("counts"),
                "gate_decisions": _count(decisions, "status"),
                "blocked": [
                    {k: d.get(k) for k in ("url", "site", "reason")}
                    for d in decisions
                    if d.get("status") == "blocked"
                ],
                "documents": [
                    {
                        "url": v["source_document"]["canonical_url"],
                        "title": v["source_document"].get("title"),
                        "parse_status": v["parse_status"],
                        "language": v.get("language"),
                        "available_at": v["available_at"],
                    }
                    for v in versions
                ],
                "user_agent": verify.settings().exchange_user_agent,
            }
        for slug in ("iqe", "soitec"):
            assert numbers[slug]["job"] == "succeeded", (slug, numbers[slug]["failures"])
            assert numbers[slug]["documents"], f"{slug}: no document fetched"


# --- 3. TradingView (ticket 31) ---------------------------------------------------------------


def test_part_3_tradingview_catalog_and_its_transcripts(verify: Verify) -> None:
    with verify.part("tradingview") as record:
        numbers: dict[str, Any] = record["numbers"]
        overrides = _tradingview_settings(verify)
        slug = _tradingview_company(verify)
        # Archived, not retained (the part's retain budget is 0); at most two tool calls a
        # job: the catalog's documents and news, then at most two transcripts.
        settings = verify.settings(hindsight_url=None, tradingview_max_calls_per_job=2, **overrides)
        catalog_id = verify.enqueue(
            "jobs",
            "enqueue",
            "tradingview_catalog",
            "--key",
            f"verify-tv-catalog-{slug}",
            "--payload",
            json.dumps({"company": slug}),
        )
        verify.drain(settings)
        catalog = verify.job(catalog_id)
        artifacts = as_dict(catalog.get("artifacts"))
        numbers["company"] = slug
        numbers["catalog_job"] = _job_summary(catalog)
        assert catalog["status"] == "succeeded", catalog.get("failures")
        company_id = verify.company(slug)["id"]
        entries = verify.get("/api/v1/tradingview/catalog", company_id=company_id, limit=200)
        numbers["catalog"] = {
            "entries": entries["total"],
            "by_category": _count(entries["items"], "category"),
        }
        headlines = [
            lead
            for lead in verify.get("/api/v1/leads", limit=200)["items"]
            if lead.get("origin") == "tradingview_news"
        ]
        numbers["news_leads"] = len(headlines)
        transcripts_id = artifacts.get("transcripts_job_id")
        if not transcripts_id:  # every transcript in the lookback is already in the ledger
            numbers["transcripts_job"] = "none enqueued (no transcript pending)"
            return
        transcripts = verify.job(str(transcripts_id))
        numbers["transcripts_job"] = _job_summary(transcripts)
        stored = as_list(as_dict(transcripts.get("artifacts")).get("source_versions"))
        numbers["transcripts"] = [
            {
                "url": version["source_document"]["canonical_url"],
                "source_tier": version["source_document"]["source_tier"],
                "available_at": version["available_at"],
                "parse_status": version["parse_status"],
                "language": version.get("language"),
            }
            for version in (verify.get(f"/api/v1/source-versions/{v}") for v in stored)
        ]
        assert transcripts["status"] == "succeeded", transcripts.get("failures")
        assert stored, "the transcripts job stored no transcript"


def _tradingview_settings(verify: Verify) -> dict[str, Any]:
    """Ticket 31's settings for this part: in a rehearsal, its fake served with a token file
    written here; live, the owner's `ATLAS_TRADINGVIEW_*` (exported from .env by
    `scripts/live-verify.sh`) and the token file `atlas tradingview login` wrote. Skips, with
    what to do, when TradingView is off or has no token."""
    if verify.tradingview_url is not None:
        token_file = verify.tmp_path / "tradingview-token.json"
        write_token_file(
            token_file,
            TokenSet(
                access_token=TV_ACCESS_TOKEN,
                refresh_token=None,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                token_endpoint=None,
                client_id=None,
                resource=f"{verify.tradingview_url}/mcp",
            ),
        )
        return {
            "tradingview_enabled": True,
            "tradingview_mcp_url": f"{verify.tradingview_url}/mcp",
            "tradingview_token_file": token_file,
            "tradingview_rate_per_s": 1.0,
        }
    names = [name for name in Settings.model_fields if name.startswith("tradingview_")]
    values: dict[str, Any] = {
        name: os.environ[f"ATLAS_{name.upper()}"]
        for name in names
        if os.environ.get(f"ATLAS_{name.upper()}")
    }
    configured = verify.settings(**values)
    if not configured.tradingview_enabled:
        pytest.skip(
            "TradingView is off (the owner override is off by default): set"
            " ATLAS_TRADINGVIEW_ENABLED=true and run `uv run atlas tradingview login`"
        )
    token_file = configured.tradingview_token_file
    if not token_file.is_absolute():  # `atlas tradingview login` writes it from the repo root
        token_file = REPO / token_file
    values["tradingview_token_file"] = token_file
    has_secret = configured.tradingview_access_token or configured.tradingview_refresh_token
    if not token_file.is_file() and not has_secret:
        pytest.skip(
            f"no TradingView token: no token file at {token_file} and no"
            " ATLAS_TRADINGVIEW_ACCESS_TOKEN; run `uv run atlas tradingview login` first"
        )
    return values


def _tradingview_company(verify: Verify) -> str:
    """The first selected company with a `tradingview_symbol` (in a rehearsal, one the fake
    has documents for)."""
    universe = load_universe(verify.themes)
    for slug in verify.companies:
        company = universe.companies.get(slug)
        if company is None or company.tradingview_symbol is None:
            continue
        if verify.tradingview_url is None or company.tradingview_symbol in TV_SYMBOLS:
            return slug
    pytest.skip(f"no selected company ({', '.join(verify.companies)}) has a tradingview_symbol")


# --- 4. Discovery -----------------------------------------------------------------------------


def test_part_4_discovery_scout_searxng_leads_and_candidates(verify: Verify) -> None:
    with verify.part("discovery") as record:
        numbers: dict[str, Any] = record["numbers"]
        if not verify.searxng_url:
            pytest.skip("no SearXNG: set ATLAS_SEARXNG_URL (or SEARXNG_URL in .env)")
        assert verify.sec_user_agent, "set ATLAS_SEC_USER_AGENT (entity resolution calls SEC)"
        if verify.model is not None:
            verify.model.scout_queries = [DISCOVERY_QUERY]
        payload = json.dumps({"theme": "photonics", "question": DISCOVERY_QUESTION})
        job_id = verify.enqueue(
            "jobs", "enqueue", "discover", "--key", "verify-discover", "--payload", payload
        )
        settings = verify.settings()
        verify.drain(settings)
        job = verify.job(job_id)
        artifacts: dict[str, Any] = as_dict(job.get("artifacts"))
        numbers["discover_job"] = _job_summary(job)
        assert job["status"] == "succeeded", job.get("failures")
        discovery = verify.get(f"/api/v1/discoveries/{artifacts['discovery_id']}")
        leads = verify.get("/api/v1/leads", limit=200)["items"]
        numbers["discovery"] = {
            "status": discovery["status"],
            "last_error": discovery["last_error"],
            "engines": discovery["engines"],
            "queries": [
                {
                    "query": q["query"],
                    "status": q["status"],
                    "results": q["result_count"],
                    "new_leads": q["new_leads"],
                    "unresponsive_engines": q["unresponsive_engines"],
                    "error": q["error"],
                }
                for q in discovery["queries"]
            ],
            "leads": len(leads),
        }
        propose_id = artifacts.get("propose_candidates_job_id")
        assert propose_id, "no propose_candidates job was enqueued"
        propose = verify.job(propose_id)
        numbers["propose_candidates_job"] = _job_summary(propose)
        candidates = verify.get("/api/v1/candidates", limit=200)["items"]
        numbers["candidates"] = {
            "count": len(candidates),
            "by_state": _count(candidates, "state"),
            "items": [
                {k: c.get(k) for k in ("name", "state", "identity_key", "tier", "country")}
                for c in candidates[:25]
            ],
        }
        assert leads, "the discovery found no lead"
        assert propose["status"] == "succeeded", propose.get("failures")


# --- 5. Claims -> Relationships ---------------------------------------------------------------


def test_part_5_claims_on_a_supplier_rich_filing_reviewed_into_relationships(
    verify: Verify,
) -> None:
    with verify.part("relationships") as record:
        numbers: dict[str, Any] = record["numbers"]
        numbers["fixture_ingest"] = verify.ingest_fixtures("coherent")
        company = verify.company("coherent")
        documents = verify.get(f"/api/v1/companies/{company['id']}/sources", limit=200)["items"]
        document = next(d for d in documents if d["canonical_url"] == COHR_10K)
        versions = verify.get(f"/api/v1/sources/{document['id']}/versions")["items"]
        version_id = versions[-1]["id"]
        payload = json.dumps({"source_version_ids": [version_id]})
        extract = verify.enqueue(
            "jobs", "enqueue", "extract_claims", "--key", "verify-extract", "--payload", payload
        )
        settings = verify.settings()
        verify.drain(settings)
        job = verify.job(extract)
        numbers["extract_job"] = _job_summary(job)
        assert job["status"] == "succeeded", job.get("failures")
        extraction_id = as_dict(job.get("artifacts")).get("extraction_id")
        claims = verify.get("/api/v1/claims", extraction_id=extraction_id, limit=500)["items"]
        numbers["claims"] = {
            "count": len(claims),
            "by_outcome": _count(claims, "outcome"),
            "rejected_reasons": _count(
                [c for c in claims if c["outcome"] != "accepted"], "reason_code"
            ),
            "by_predicate": _count(claims, "predicate"),
        }
        review = verify.enqueue(
            "jobs", "enqueue", "review_relationships", "--key", "verify-review", "--payload", "{}"
        )
        verify.drain(settings)
        reviewed = verify.job(review)
        numbers["review_job"] = _job_summary(reviewed)
        assert reviewed["status"] == "succeeded", reviewed.get("failures")
        edges = verify.get("/api/v1/relationships", limit=200)["items"]
        exceptions = verify.get("/api/v1/relationships/exceptions", limit=200)["items"]
        numbers["relationships"] = {
            "count": len(edges),
            "by_review_state": _count(edges, "review_state"),
            "exceptions": len(exceptions),
            "edges": [
                {k: e.get(k) for k in ("predicate", "layer", "review_state", "evidence_count")}
                for e in edges[:20]
            ],
        }
        assert claims, "the Investigator proposed no Claim"
        assert edges, "no Relationship formed (machine_reviewed or exception)"


# --- 6. Investigation end to end --------------------------------------------------------------


def test_part_6_investigation_to_a_hypothesis_scenario_and_publish(verify: Verify) -> None:
    with verify.part("investigation") as record:
        numbers: dict[str, Any] = record["numbers"]
        if not verify.searxng_url:
            pytest.skip("no SearXNG: set ATLAS_SEARXNG_URL (or SEARXNG_URL in .env)")
        numbers["fixture_ingest"] = verify.ingest_fixtures(*INVESTIGATION_SEEDS)
        if verify.model is not None:
            verify.model.scout_queries = [INVESTIGATION_QUERY]
        seeds = [verify.company(slug)["id"] for slug in INVESTIGATION_SEEDS]
        started = verify.post(
            "/api/v1/investigations",
            {
                "theme": "photonics",
                "question": INVESTIGATION_QUESTION,
                "seed_company_ids": seeds,
                "budgets": {
                    "max_leads": 5,
                    "max_documents": 6,
                    # The seeds only: an Investigator added for a company the reading pointers
                    # name (the earlier parts' companies are in the bank) would spend MiniMax
                    # calls this part's cap doesn't count on.
                    "max_companies": len(seeds),
                    "token_budget": RUN_TOKEN_BUDGET,
                },
            },
            202,
        )
        settings = verify.settings()
        verify.drain(settings)
        found = verify.get(f"/api/v1/investigations/{started['id']}")
        card = as_dict(found.get("research_card"))
        numbers["investigation"] = {
            "status": found["status"],
            "stop_reason": found["stop_reason"],
            "stop_detail": found["stop_detail"],
            "tasks": {t["key"]: t["status"] for t in found["tasks"]},
            "usage": found["usage"],
            "leads": len(as_list(found.get("leads"))),
            "documents": len(as_list(found.get("documents"))),
            "counterevidence": len(as_list(found.get("counterevidence"))),
            "card_findings": len(as_list(card.get("findings"))),
            "card_verdict": card.get("editor_verdict"),
        }
        assert found["status"] == "stopped", found["stop_detail"]

        hypothesis = verify.post("/api/v1/hypotheses", {"investigation_id": found["id"]}, 202)
        verify.drain(settings)
        hypothesis = verify.get(f"/api/v1/hypotheses/{hypothesis['id']}")
        numbers["hypothesis"] = {
            "draft_status": hypothesis["draft_status"],
            "draft_error": hypothesis.get("draft_error"),
            "status": hypothesis["status"],
            "latest_version": hypothesis.get("latest_version"),
        }
        assert hypothesis["draft_status"] == "drafted", hypothesis.get("draft_error")

        path = f"/api/v1/hypotheses/{hypothesis['id']}/scenarios"
        response = verify.api.post(path, json={"version": 1})
        origin = "financial_analyst"
        if response.status_code == 409:  # the Analyst proposed no table: a researcher's
            origin = "researcher"
            response = verify.api.post(
                path, json={"version": 1, "assumptions": _estimated_table(seeds[0])}
            )
        assert response.status_code == 201, response.text
        first = response.json()["items"][0]
        again = verify.post(path, {"version": 1, "assumptions": first["assumptions"]}, 201)
        read = verify.get(f"{path}/{first['id']}")
        numbers["scenario"] = {
            "origin": origin,
            "scenarios": len(response.json()["items"]),
            "outputs_sha256": first["outputs_sha256"],
            "recomputes_identically": read["recomputes_identically"],
            "resent_table_same_bytes": again["items"][0]["outputs_json"] == first["outputs_json"],
        }
        assert read["recomputes_identically"] is True
        assert again["items"][0]["outputs_sha256"] == first["outputs_sha256"]

        numbers["publish"] = _publish(verify, hypothesis["id"])


OWNER_NOTE = "live verification: the harness approved this as the owner step (ticket 32)"


def _publish(verify: Verify, hypothesis_id: str) -> dict[str, Any]:
    """Publish version 1 behind the gate (ticket 20) and read its Research Snapshot back.

    evidence_ready, then the gate is read. When the owner's approval of the Relationships the
    version depends on is all it lacks, the harness plays the owner: it approves each edge
    through `POST /relationships/{id}/review` and records that it did so (`owner_step`). It
    then publishes when the gate allows, and reads the snapshot (re-hashed on every read). A
    gate the owner can't open (no falsifier, no unresolved question, an Assertion not yet
    machine-reviewed) is reported, not forced."""
    base = f"/api/v1/hypotheses/{hypothesis_id}"
    moved = verify.api.post(f"{base}/transitions", json={"to": "evidence_ready"})
    if moved.status_code != 200:
        return {"published": False, "transition": moved.status_code, "detail": moved.json()}
    gate = verify.get(f"{base}/publish-gate")
    result: dict[str, Any] = {"gate_before": _gate_summary(gate), "owner_step": None}
    codes = {failure["code"] for failure in gate["failures"]}
    if gate["blocked"] is None and codes == {"relationship_not_approved"}:
        edges = sorted({str(each) for f in gate["failures"] for each in f["relationship_ids"]})
        approvals: list[dict[str, Any]] = []
        for edge_id in edges:
            before = verify.get(f"/api/v1/relationships/{edge_id}")
            verify.post(
                f"/api/v1/relationships/{edge_id}/review",
                {"review_state": "approved", "note": OWNER_NOTE},
                200,
            )
            approvals.append(
                {
                    "relationship_id": edge_id,
                    "predicate": before.get("predicate"),
                    "review_state_before": before.get("review_state"),
                }
            )
        result["owner_step"] = {
            "by": "the live-verify harness, as the owner (not a human decision)",
            "note": OWNER_NOTE,
            "approved": approvals,
        }
        gate = verify.get(f"{base}/publish-gate")
        result["gate_after"] = _gate_summary(gate)
    if not gate["publishable"]:
        return result | {"published": False, "snapshot": None}
    published = verify.api.post(
        f"{base}/publish-version", json={"version": 1, "note": "live verification"}
    )
    assert published.status_code == 200, f"the gate allowed it, yet: {published.text}"
    snapshots = verify.get("/api/v1/snapshots", hypothesis_id=hypothesis_id)["items"]
    assert len(snapshots) == 1, snapshots
    snapshot = verify.get(f"/api/v1/snapshots/{snapshots[0]['id']}")
    assert snapshot["verified"] is True
    return result | {
        "published": True,
        "status": published.json()["status"],
        "snapshot": {
            "id": snapshot["id"],
            "hypothesis_version": snapshot["hypothesis_version"],
            "sha256": snapshot["sha256"],
            "byte_size": snapshot["byte_size"],
            "object_uri": snapshot["object_uri"],
            "verified": snapshot["verified"],
        },
    }


def _gate_summary(gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": gate["version"],
        "blocked": gate["blocked"],
        "publishable": gate["publishable"],
        "failures": [
            {"code": f["code"], "relationships": len(f["relationship_ids"])}
            for f in gate["failures"]
        ],
    }


def _estimated_table(company_id: str) -> dict[str, Any]:
    def guess(low: str, base: str, high: str) -> dict[str, Any]:
        return {"kind": "estimated", "basis": "live verification", "low": low, "base": base,
                "high": high}  # fmt: skip

    return {
        "company_id": company_id,
        "product": "advanced lasers",
        "currency": "USD",
        "inputs": {
            "addressable_units": guess("8000000", "10000000", "12000000"),
            "company_share": guess("0.2", "0.25", "0.3"),
            "downstream_unit_price": guess("900", "1000", "1100"),
            "bom_share": guess("0.15", "0.2", "0.25"),
            "operating_margin": guess("0.25", "0.3", "0.35"),
            "ev_multiple": guess("15", "20", "25"),
            "reported_revenue": guess("6000000000", "6000000000", "6000000000"),
            "total_debt": guess("3000000000", "3000000000", "3000000000"),
            "cash": guess("900000000", "900000000", "900000000"),
            "diluted_shares": guess("150000000", "150000000", "150000000"),
        },
    }


# --- 7. Identity ------------------------------------------------------------------------------


def test_part_7_identity_resolve_two_companies_and_list_pending_reviews(verify: Verify) -> None:
    with verify.part("identity") as record:
        numbers: dict[str, Any] = record["numbers"]
        assert verify.sec_user_agent, "set ATLAS_SEC_USER_AGENT (entity resolution calls SEC)"
        env = {"ATLAS_SEC_USER_AGENT": verify.sec_user_agent}
        env |= {f"ATLAS_{k.upper()}": v for k, v in verify._identity_urls().items()}  # pyright: ignore[reportPrivateUsage]
        args: list[str] = []
        for slug in IDENTITY_COMPANIES:
            args += ["--company", slug]
        resolved = verify.cli("companies", "resolve", *args, **env)
        results = [json.loads(line) for line in resolved.stdout.splitlines() if line.strip()]
        pending = verify.get("/api/v1/identity-mappings", review_state="pending", limit=200)
        numbers["resolve"] = {
            "exit": resolved.returncode,
            # The CLI logs every request at INFO; only warnings and errors are kept.
            "stderr": [
                line[:400]
                for line in resolved.stderr.splitlines()
                if '"levelname": "INFO"' not in line
            ][-10:],
            "results": results,
        }
        numbers["pending_reviews"] = {
            "count": pending["total"],
            "items": [
                {
                    k: m.get(k)
                    for k in ("company_slug", "kind", "value", "tier", "source", "reasons")
                }
                for m in pending["items"][:25]
            ],
        }
        numbers["companies"] = {
            slug: {
                "cik": verify.company(slug).get("cik"),
                "lei": verify.company(slug).get("lei"),
                "listings": [
                    {k: each.get(k) for k in ("ticker", "exchange_mic", "segment_mic", "figi")}
                    for each in as_list(verify.company(slug).get("securities"))
                ],
            }
            for slug in IDENTITY_COMPANIES
        }
        assert resolved.returncode == 0, resolved.stderr


# --- helpers ----------------------------------------------------------------------------------


def _count(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    artifacts = as_dict(job.get("artifacts"))
    return {
        "status": job["status"],
        "attempts": job.get("attempts"),
        "failures": job.get("failures"),
        "artifacts": {k: v for k, v in artifacts.items() if not isinstance(v, list | dict)},
    }
