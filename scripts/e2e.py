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
3. starts the API with uvicorn on a free localhost port, serving `frontend/out` on the
   same origin (`ATLAS_FRONTEND_DIR`), and runs `playwright test` against it.
4. stops the API and drops the database.
"""

# The commands run here are fixed (npm, node and the atlas CLI), never user input.
# ruff: noqa: S603, S607

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
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import uvicorn
from pydantic import JsonValue
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from atlas.api.app import create_app
from atlas.archive import open_archive
from atlas.assertions import AssertionCreate, Assertions
from atlas.audit import Actor
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

    with tempfile.TemporaryDirectory(prefix="atlas-e2e-") as tmp, fresh_database() as url:
        workdir = Path(tmp)  # the CLI runs here, so no developer .env is picked up
        archive = workdir / "archive"
        archive.mkdir()
        seed(url, archive, workdir)
        settings = Settings.model_validate(
            {
                "database_url": url,
                "actor": "e2e-smoke",
                "archive_root": archive,
                "themes_config": THEMES,
                "frontend_dir": STATIC_EXPORT,
            }
        )
        with running_api(settings) as base_url:
            print(f"e2e: API and static export at {base_url}", flush=True)
            env = {**os.environ, "ATLAS_E2E_BASE_URL": base_url}
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
