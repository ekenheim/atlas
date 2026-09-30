"""Run the frontend's Playwright tests against a live, freshly seeded Atlas.

    uv run python scripts/e2e.py

Needs the Compose Postgres (`docker compose up -d --wait postgres-app`) and the built
static export (`npm --prefix frontend run build`). In order, it:

1. installs Playwright's chromium (`--with-deps` when `CI` is set) and checks that it
   launches. If it can't, the test is skipped with a message locally, and fails in CI.
2. creates an empty database (`atlas_e2e_<hex>`) next to the test databases
   (`ATLAS_TEST_DATABASE_URL`) and, through the `atlas` CLI, migrates it, seeds the
   company universe, enqueues the Lumentum ingest and runs one worker pass against the
   recorded EDGAR fixtures (`tests/fixtures/edgar`), archiving into a temporary directory.
   It then records the synthetic annual-report PDF (`tests/fixtures/pdf`) for Lumentum
   through the ledger, and builds three Relationships through the Assertions service and a
   `review_relationships` job (hedged quotes, so no Reviewer call), approving one.
3. creates a second database for the research workbench, whose investigations need the
   recorded fakes (`tests/fakes`: Hindsight, LiteLLM with scripted role answers, SearXNG)
   served on localhost: it migrates it, applies the bank template, seeds the universe (plus
   NVIDIA, which the Coherent 10-K names), ingests and retains Coherent from the EDGAR
   fixtures, then runs two investigations through the API and worker passes to answered
   research cards with open questions (`seed_workbench`).
4. creates a third database for the Hypothesis dossier (`scripts/e2e_hypothesis.py`):
   Coherent ingested, an investigation, a Hypothesis drafted, published and corrected, all
   through the real services with the LLM, Hindsight and SearXNG faked on localhost. The
   workbench and the dossier each get their own database because their companies, edges and
   investigations would change what the other pages' tests count.
5. starts an API with uvicorn on a free localhost port for each database, serving
   `frontend/out` on the same origin (`ATLAS_FRONTEND_DIR`; the workbench's with the fakes
   configured), and runs `playwright test` against them (`ATLAS_E2E_BASE_URL`,
   `ATLAS_E2E_WORKBENCH_URL` and `ATLAS_E2E_HYPOTHESIS_BASE_URL`).
6. stops the APIs and the fakes and drops the databases.
"""

# The commands run here are fixed (npm, node and the atlas CLI), never user input.
# ruff: noqa: S603, S607

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import uvicorn
import yaml
from e2e_hypothesis import seed_hypothesis
from pydantic import JsonValue
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from atlas.api.app import create_app
from atlas.archive import open_archive
from atlas.assertions import AssertionCreate, Assertions
from atlas.audit import Actor
from atlas.db.migrate import upgrade
from atlas.jobs import HandlerRegistry, JobQueue, Worker
from atlas.ledger import SourceLedger
from atlas.relationships import (
    REVIEW_RELATIONSHIPS_KIND,
    OwnerReview,
    RelationshipReviewer,
    Relationships,
    list_relationships,
)
from atlas.roles import RoleCaller
from atlas.settings import Settings
from atlas.sources import FetchedDocument, HttpValidators, SourceCandidate

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))  # the recorded fakes and the test harness, in `tests`

from tests.fakes.hindsight import RecordedHindsight  # noqa: E402
from tests.fakes.litellm import ChatReply, FakeLiteLLM  # noqa: E402
from tests.fakes.searxng import FakeSearXNG, SearchReply  # noqa: E402
from tests.fakes.serve import Served, serve  # noqa: E402
from tests.harness import Atlas  # noqa: E402

FRONTEND = REPO / "frontend"
STATIC_EXPORT = FRONTEND / "out"
THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"
EDGAR_FIXTURES = REPO / "tests" / "fixtures" / "edgar"
PDF_FIXTURE = REPO / "tests" / "fixtures" / "pdf" / "annual-report-en.pdf"
ADMIN_DATABASE_URL = os.environ.get(
    "ATLAS_TEST_DATABASE_URL", "postgresql+psycopg://atlas:atlas@127.0.0.1:55432/atlas"
)
# Host ports the Compose services and the dev API own; never bind them here.
RESERVED_PORTS = {55432, 59000, 58000, 58080}
IN_CI = bool(os.environ.get("CI"))


def main() -> int:
    if not (STATIC_EXPORT / "index.html").is_file():
        print(f"e2e: {STATIC_EXPORT} has no build; run `npm --prefix frontend run build`")
        return 1
    unavailable = browser_unavailable()
    if unavailable:
        if IN_CI:
            print(f"e2e: FAILED: the Playwright chromium browser is unavailable: {unavailable}")
            return 1
        print(
            "e2e: SKIPPED: the Playwright chromium browser is unavailable "
            f"({unavailable}). Install it with "
            "`npm --prefix frontend exec playwright install --with-deps chromium` and re-run; "
            "on a distro Playwright doesn't support, PLAYWRIGHT_HOST_PLATFORM_OVERRIDE="
            "ubuntu22.04-x64 may work."
        )
        return 0

    with (
        tempfile.TemporaryDirectory(prefix="atlas-e2e-") as tmp,
        fresh_database() as url,
        fresh_database() as workbench_url,
        workbench_fakes() as fakes,
        fresh_database() as hypothesis_url,
    ):
        workdir = Path(tmp)  # the CLI runs here, so no developer .env is picked up
        archive = workdir / "archive"
        archive.mkdir()
        seed(url, archive, workdir)
        upgrade(hypothesis_url)
        dossier = seed_hypothesis(hypothesis_url, workdir / "hypothesis")
        settings = Settings.model_validate(
            {
                "database_url": url,
                "actor": "e2e-smoke",
                "archive_root": archive,
                "themes_config": THEMES,
                "frontend_dir": STATIC_EXPORT,
            }
        )
        workbench = workdir / "workbench"
        workbench.mkdir()
        workbench_settings = seed_workbench(workbench_url, workbench, fakes)
        hypothesis_settings = Settings.model_validate(
            {
                "database_url": hypothesis_url,
                "actor": "e2e-smoke",
                "archive_root": dossier.archive,
                "themes_config": dossier.themes,
                "frontend_dir": STATIC_EXPORT,
            }
        )
        with (
            running_api(settings) as base_url,
            running_api(workbench_settings) as bench_url,
            running_api(hypothesis_settings) as dossier_url,
        ):
            print(f"e2e: API and static export at {base_url}", flush=True)
            print(f"e2e: the research workbench's API at {bench_url}", flush=True)
            print(f"e2e: the Hypothesis dossier's API at {dossier_url}", flush=True)
            env = {
                **os.environ,
                "ATLAS_E2E_BASE_URL": base_url,
                "ATLAS_E2E_WORKBENCH_URL": bench_url,
                "ATLAS_E2E_HYPOTHESIS_BASE_URL": dossier_url,
            }
            return subprocess.run(npx("playwright", "test"), cwd=FRONTEND, env=env).returncode


def npx(*args: str) -> list[str]:
    return ["npm", "exec", "--no", "--", *args]


def browser_unavailable() -> str | None:
    """Why chromium can't be installed or launched, or None when it launches."""
    install = npx("playwright", "install", *(["--with-deps"] if IN_CI else []), "chromium")
    installed = subprocess.run(install, cwd=FRONTEND, capture_output=True, text=True)
    if installed.returncode != 0:
        return f"`playwright install` failed: {last_line(installed.stderr or installed.stdout)}"
    probe = "require('@playwright/test').chromium.launch().then((b) => b.close())"
    launched = subprocess.run(["node", "-e", probe], cwd=FRONTEND, capture_output=True, text=True)
    if launched.returncode != 0:
        return f"chromium does not launch: {last_line(launched.stderr)}"
    return None


def last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


@contextmanager
def fresh_database() -> Generator[str]:
    name = f"atlas_e2e_{uuid.uuid4().hex[:12]}"
    admin = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(ADMIN_DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def seed(database_url: str, archive: Path, workdir: Path) -> None:
    """Migrate, then ingest Lumentum from the recorded EDGAR fixtures via the CLI."""
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(workdir),
        "ATLAS_DATABASE_URL": database_url,
        "ATLAS_ACTOR": "e2e-smoke",
        "ATLAS_ARCHIVE_ROOT": str(archive),
        "ATLAS_THEMES_CONFIG": str(THEMES),
        "ATLAS_SEC_FIXTURES_DIR": str(EDGAR_FIXTURES),
    }
    for args in (
        ["migrate"],
        ["companies", "seed"],
        ["ingest", "--company", "lumentum", "--key", "e2e-smoke"],
        ["worker", "--once"],
    ):
        done = subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if done.returncode != 0:
            raise SystemExit(f"e2e: `atlas {' '.join(args)}` failed:\n{done.stderr}")
    seed_pdf(database_url, archive)
    seed_relationships(database_url, archive)


# Hedged sentences of Lumentum's FY2026 10-K (the recorded fixture's parsed text): each
# names a relation with a directional cue and a hedge ("may"), so machine review sends its
# edge to the exceptions queue (`hedged_language`) without asking the Reviewer (an LLM).
LUMENTUM_10K = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026057358/lite-20260627.htm"
)
SEEDED_EDGES: tuple[tuple[str, str | None, str, dict[str, JsonValue]], ...] = (
    # (predicate, object company slug, quote, value_json)
    (
        "depends_on",
        "fabrinet",
        "For many products, a particular contract manufacturer may be the sole source of the"
        " finished good products.",
        {"layer": "contract-manufacturing", "product": None},
    ),
    (
        "competes_with",
        "coherent",
        "Our current or potential customers may also determine to develop and produce products"
        " for their own use which may be competitive to our products.",
        {"layer": "module", "product": None},
    ),
    (
        "manufactures",
        None,
        "Changes in demand and customer requirements for our products may reduce manufacturing"
        " yields, which could negatively impact our profitability.",
        {"layer": "module", "object_text": "optical and photonic products", "product": None},
    ),
)


def seed_relationships(database_url: str, archive_root: Path) -> None:
    """Build three Relationships through the real services: Assertions on the Lumentum 10-K,
    then one `review_relationships` job on the queue, run by a worker pass. Each is hedged,
    so each edge lands in the exceptions queue; the owner then approves the `manufactures`
    edge, leaving two in the queue for the test to decide."""
    settings = Settings.model_validate(
        {"database_url": database_url, "actor": "e2e-smoke", "archive_root": archive_root}
    )
    engine = create_engine(database_url)
    archive = open_archive(settings)
    actor = Actor("e2e-smoke")
    try:
        with engine.connect() as connection:
            version_id, parsed_uri = connection.execute(
                text(
                    "SELECT v.id, v.parsed_object_uri FROM source_version v"
                    " JOIN source_document d ON d.id = v.source_document_id"
                    " WHERE d.canonical_url = :url ORDER BY v.version_number DESC LIMIT 1"
                ),
                {"url": LUMENTUM_10K},
            ).one()
            companies: dict[str, uuid.UUID] = {
                row.slug: row.id for row in connection.execute(text("SELECT slug, id FROM company"))
            }
        parsed = archive.get(parsed_uri).decode("utf-8")
        assertions = Assertions(engine, archive, actor)
        assertion_ids: list[JsonValue] = []
        for predicate, target, quote, value in SEEDED_EDGES:
            start = parsed.index(quote)
            recorded = assertions.create(
                AssertionCreate(
                    subject_company_id=companies["lumentum"],
                    predicate=predicate,
                    object_company_id=None if target is None else companies[target],
                    value_json=value,
                    source_version_id=version_id,
                    quote=quote,
                    span_start=start,
                    span_end=start + len(quote),
                    epistemic_type="company_claim",
                )
            )
            assertion_ids.append(str(recorded.assertion.id))

        queue = JobQueue(engine)
        queue.enqueue(
            REVIEW_RELATIONSHIPS_KIND, "e2e-relationships", {"assertion_ids": assertion_ids}
        )
        registry = HandlerRegistry()
        with no_reviewer(engine) as caller:
            reviewer = RelationshipReviewer(engine, archive, caller, None, per_call=10)
            registry.register(REVIEW_RELATIONSHIPS_KIND, reviewer.review, pausable=True)
            Worker(queue, registry).run_once()
        with engine.connect() as connection:
            edges = list_relationships(connection, limit=10, offset=0)[0]
        if [edge.review_state for edge in edges] != ["needs_human_review"] * len(SEEDED_EDGES):
            raise SystemExit(f"e2e: the seeded relationships were not all exceptions: {edges}")
        (made,) = [edge for edge in edges if edge.predicate == "manufactures"]
        Relationships(engine, actor).review(
            made.id, OwnerReview(review_state="approved", note="seeded by scripts/e2e.py")
        )
    finally:
        engine.dispose()


@contextmanager
def no_reviewer(engine: Engine) -> Generator[RoleCaller]:
    """A role caller whose every call fails: the seeded Assertions never reach the Reviewer."""

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise SystemExit(f"e2e: the Reviewer was asked ({request.url}); the seed expects not")

    caller = RoleCaller(
        engine,
        "http://reviewer.invalid",
        "unused",
        model="unused",
        extra_body={},
        token_budget=0,
        timeout=1,
        transport=httpx2.MockTransport(refuse),
    )
    with caller:
        yield caller


def seed_pdf(database_url: str, archive: Path) -> None:
    """Record the synthetic annual-report PDF (tests/fixtures/pdf) as a Lumentum Source
    Version, through the ledger as an adapter's fetch would: no adapter fetches PDFs yet."""
    settings = Settings.model_validate(
        {"database_url": database_url, "actor": "e2e-smoke", "archive_root": archive}
    )
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            company_id = connection.execute(
                text("SELECT id FROM company WHERE slug = 'lumentum'")
            ).scalar_one()
        url = f"https://www.sec.gov/Archives/edgar/data/1633978/{PDF_FIXTURE.name}"
        now = datetime.now(UTC)
        candidate = SourceCandidate(
            provider_id="sec_edgar",
            kind="sec_filing_document",
            url=url,
            title="Synthetic annual report (PDF)",
            document_type="PDF",
            discovered_at=now,
            available_at=now,
            available_at_basis="observed_discovery",
        )
        fetched = FetchedDocument(
            candidate=candidate,
            url=url,
            fetched_at=now,
            not_modified=False,
            content=PDF_FIXTURE.read_bytes(),
            media_type="application/pdf",
            validators=HttpValidators(),
            attempts=(),
        )
        ledger = SourceLedger(engine, open_archive(settings), Actor("e2e-smoke"))
        ledger.record(fetched, company_id=company_id)
    finally:
        engine.dispose()


# --- the research workbench's database -----------------------------------------------------------

WORKBENCH_QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?"
HYPOTHESIS_QUESTION = "Which laser makers does NVIDIA depend on?"
OPEN_QUESTION = "Does NVIDIA qualify a second laser source?"
CARD_QUESTION = "Is InP substrate capacity a constraint for 2027?"
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
# From the Coherent FY2026 10-K (the recorded fixture's parsed text).
COHERENT_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)


@dataclass
class Fakes:
    hindsight: Served
    litellm: Served
    searxng: Served
    llm: FakeLiteLLM
    search: FakeSearXNG


@contextmanager
def workbench_fakes() -> Generator[Fakes]:
    """The recorded Hindsight, LiteLLM and SearXNG fakes, served on localhost."""
    hindsight = RecordedHindsight()
    hindsight.derive_memories()
    llm, search = FakeLiteLLM(), FakeSearXNG()
    with (
        serve(hindsight.transport.handle_request) as hindsight_served,
        serve(llm.handle) as litellm_served,
        serve(search.handle) as searxng_served,
    ):
        yield Fakes(hindsight_served, litellm_served, searxng_served, llm, search)


def asked(body: dict[str, Any]) -> dict[str, Any]:
    """A role call's user message: `{"request": ..., "retrieved_data": [...]}`."""
    return json.loads(body["messages"][1]["content"])


def seed_workbench(database_url: str, root: Path, fakes: Fakes) -> Settings:
    """Two investigations, each stopped `answered` with a research card and open questions,
    through the API and worker passes with scripted role answers; returns the settings the
    workbench's API is started with."""
    themes = root / "themes.yaml"
    universe = yaml.safe_load(THEMES.read_text(encoding="utf-8"))
    universe["companies"]["nvidia"] = {
        "legal_name": "NVIDIA Corporation",
        "display_name": "NVIDIA",
        "cik": "0001045810",
        "country": "US",
        "source_path": "sec",
    }
    themes.write_text(yaml.safe_dump(universe), encoding="utf-8")
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(root),
        "ATLAS_DATABASE_URL": database_url,
        "ATLAS_ACTOR": "e2e-smoke",
        "ATLAS_ARCHIVE_ROOT": str(root / "archive"),
        "ATLAS_THEMES_CONFIG": str(themes),
    }
    for args in (["migrate"], ["companies", "seed"]):
        done = subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if done.returncode != 0:
            raise SystemExit(f"e2e: workbench `atlas {' '.join(args)}` failed:\n{done.stderr}")
    atlas = Atlas(
        database_url,
        root,
        fakes.hindsight.url,
        fakes.litellm.url,
        themes_config=themes,
        searxng_url=fakes.searxng.url,
        investigator_passages_per_call=50,
        actor="e2e-smoke",
    )
    try:
        atlas.apply_template()
        atlas.ingest_company("coherent")
        companies = {each["slug"]: each["id"] for each in atlas.get("/api/v1/companies")["items"]}
        for question in (WORKBENCH_QUESTION, HYPOTHESIS_QUESTION):
            investigate(atlas, fakes, companies, question)
        for served in (fakes.hindsight, fakes.litellm, fakes.searxng):
            served.raise_errors()
        return atlas.settings().model_copy(update={"frontend_dir": STATIC_EXPORT})
    finally:
        atlas.engine.dispose()


def investigate(atlas: Atlas, fakes: Fakes, companies: dict[str, str], question: str) -> None:
    """One investigation of Coherent and Lumentum: the Scout's one query, the Investigator's
    supply Claim (the Coherent 10-K), a Skeptic that finds nothing in what code's fallback
    chose for it (its plan chooses nothing) and a Financial Analyst that
    proposes no scenario (scripted by role: their jobs run in either order), an Editor
    answering with open questions, then the chained Reviewer."""
    started = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": question,
            "seed_company_ids": [companies["coherent"], companies["lumentum"]],
        },
    )
    if started.status_code != 202:
        raise SystemExit(f"e2e: the workbench investigation was refused: {started.text}")
    claim: dict[str, JsonValue] = {
        "subject_company_id": companies["coherent"],
        "predicate": "supplies",
        "object_company_id": companies["nvidia"],
        "object_name": None,
        "object_text": None,
        "product": "advanced lasers",
        "layer": "chip-laser",
        "quote": COHERENT_QUOTE,
        "epistemic_type": "company_claim",
    }

    def quoting(body: dict[str, Any]) -> JsonValue:
        for passage in asked(body)["retrieved_data"]:
            if COHERENT_QUOTE in passage["text"]:
                at = passage["text"].index(COHERENT_QUOTE)
                end = at + len(COHERENT_QUOTE)
                return {
                    "claims": [
                        claim | {"passage_id": passage["id"], "quote_start": at, "quote_end": end}
                    ]
                }
        return {"claims": []}

    def editing(body: dict[str, Any]) -> JsonValue:
        claims = asked(body)["request"]["claims"]
        return {
            "findings": [
                {
                    "statement": "Coherent supplies NVIDIA with advanced lasers under a"
                    " multi-year supply agreement.",
                    "claim_ids": [each["claim_id"] for each in claims],
                    "limitations": ["A company's own statement; no volumes or prices."],
                    "open_questions": [OPEN_QUESTION],
                }
            ],
            "open_questions": [CARD_QUESTION],
            "verdict": "answered",
        }

    def reviewing(body: dict[str, Any]) -> JsonValue:
        return {
            "reviews": [
                {
                    "item_id": item["item_id"],
                    "verdict": "confirmed",
                    "direction": "as_proposed",
                    "layer": "correct",
                    "suggested_layer": None,
                    "reasoning": "the quote states it",
                }
                for item in asked(body)["request"]["items"]
            ]
        }

    def finding_nothing(body: dict[str, Any]) -> JsonValue:
        # Its plan chooses nothing; code's fallback then chooses the seed companies' filings
        # (pilot fix 06), and its reading of them finds no counterevidence.
        if "catalog" in asked(body)["request"]:
            return {"queries": [], "documents": []}
        return {"counterevidence": []}

    fakes.llm.script_role("skeptic", *[ChatReply.answer(finding_nothing)] * 8)
    fakes.llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}))
    fakes.llm.script_chat(
        ChatReply.json({"queries": [{"query": SUBSTRATE, "purpose": "InP substrate capacity"}]}),
        ChatReply.answer(quoting),
        ChatReply.answer(editing),
        ChatReply.answer(reviewing),
    )
    fakes.search.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    atlas.worker_pass()
    found = atlas.get(f"/api/v1/investigations/{started.json()['id']}")
    if (found["stop_reason"], len(found["evidence"])) != ("answered", 1):
        raise SystemExit(f"e2e: the workbench investigation ended {found['stop_reason']}: {found}")


def free_port() -> int:
    while True:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port: int = probe.getsockname()[1]
        if port not in RESERVED_PORTS:
            return port


@contextmanager
def running_api(settings: Settings) -> Generator[str]:
    port = free_port()
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise SystemExit(f"e2e: the API did not start on port {port}")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    if shutil.which("npm") is None:
        raise SystemExit("e2e: npm is not on PATH")
    sys.exit(main())
