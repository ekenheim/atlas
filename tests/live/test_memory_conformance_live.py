"""The memory conformance check, live (memory-quality ticket 14). Never in CI.

Run it with `scripts/memory-conformance.sh` (see `docs/runbooks.md`, "Memory conformance"),
which sets the two locks (`ATLAS_LIVE_TESTS=1`, and the confirmation) and the settings below;
its `--rehearse` runs `tests/integration/test_memory_conformance.py` instead.

- **Known answers** (`ATLAS_CONFORMANCE_BASE_URL`, default production): read-only through the
  running Atlas's `/api/v1`: every answer of `configs/memory/known-answers.yaml` resolved, the
  five questions recalled with their queries; no LLM call, no write.
- **Behaviours** (`ATLAS_LIVE_HINDSIGHT_URL`/`_API_KEY`): a throwaway bank on the real
  Hindsight, prepared through Atlas's retain path from the recorded fixtures
  (`tests/live/conformance.py`), behind the counting proxies (at most 10 retain operations and
  6 reflect, refresh or consolidation requests), always deleted. Hindsight's own extraction
  (on the owner's MiniMax) is the main cost: one LLM request per stored chunk of the 19
  sections retained; the report gives the bank's own LLM request log.

The report (`ATLAS_CONFORMANCE_RESULTS_DIR`) is written when the module ends; each test fails
when its half does (`--strict`: also while a check is pending).
"""

import os
import uuid
from collections.abc import Generator, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from atlas.companies import load_universe
from atlas.conformance import (
    DEFAULT_RECALL_MAX_TOKENS,
    AtlasApi,
    ConformanceReport,
    KnownAnswersError,
    load_known_answers,
    run_known_answers,
)
from atlas.db.migrate import upgrade
from atlas.research.probes import load_probes
from tests.fakes.serve import serve
from tests.fakes.tradingview import FakeTradingView
from tests.live.conformance import (
    KNOWN_ANSWERS,
    PROBES,
    THEMES,
    Caps,
    conformance_settings,
    new_bank_id,
    run_behaviours,
)
from tests.live.stack import DEFAULT_ADMIN_DATABASE_URL, live_mode

DEFAULT_BASE_URL = "https://atlas.ekenhome.se"
PARTS = ("known-answers", "behaviours")
SETTLE_SECONDS = 3600.0  # the retains and the consolidation of the throwaway bank
POLL_SECONDS = 5.0


def recall_max_tokens() -> list[int]:
    """The recalls' results budgets to measure (`--recall-max-tokens`, comma-separated; the
    first decides the verdict): the setting's default and 16,000 unless given."""
    given = os.environ.get("ATLAS_CONFORMANCE_RECALL_MAX_TOKENS", "")
    values = [int(part) for part in given.replace(" ", "").split(",") if part]
    return list(dict.fromkeys(values)) or [DEFAULT_RECALL_MAX_TOKENS, 16000]


def _selected(part: str) -> bool:
    chosen = os.environ.get("ATLAS_CONFORMANCE_PARTS") or ",".join(PARTS)
    return part in chosen.split(",")


@pytest.fixture(scope="module")
def report() -> Iterator[ConformanceReport]:
    if live_mode() != "live":
        pytest.skip("the live check needs ATLAS_LIVE_TESTS=1; --rehearse runs the CI one")
    strict = os.environ.get("ATLAS_CONFORMANCE_STRICT") == "1"
    conformance = ConformanceReport(mode="live", strict=strict)
    yield conformance
    results = os.environ.get("ATLAS_CONFORMANCE_RESULTS_DIR")
    if results:
        conformance.write(Path(results))


def test_known_answers_on_the_live_bank(report: ConformanceReport) -> None:
    if not _selected("known-answers"):
        pytest.skip("not selected (--only behaviours)")
    base_url = os.environ.get("ATLAS_CONFORMANCE_BASE_URL") or DEFAULT_BASE_URL
    report.stack["atlas"] = base_url
    universe = load_universe(THEMES)
    probes = load_probes(PROBES, universe)
    try:
        answers = load_known_answers(KNOWN_ANSWERS, universe, probes)
    except KnownAnswersError as error:
        report.known_answers_error = str(error)
        raise
    budgets = recall_max_tokens()
    with httpx2.Client(base_url=base_url.rstrip("/"), timeout=120.0) as client:
        reports = [
            run_known_answers(AtlasApi(client), answers, probes, max_tokens=value)
            for value in budgets
        ]
    report.known_answers, report.known_answers_sweep = reports[0], reports[1:]
    assert report.known_answers.verdict == "passed", report.known_answers.reason


@contextmanager
def _fresh_database() -> Generator[str]:
    admin_url = os.environ.get("ATLAS_TEST_DATABASE_URL") or DEFAULT_ADMIN_DATABASE_URL
    name = f"atlas_conformance_{uuid.uuid4().hex[:12]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
        upgrade(url)
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_behaviours_on_a_throwaway_bank(
    report: ConformanceReport, tmp_path_factory: pytest.TempPathFactory
) -> None:
    if not _selected("behaviours"):
        pytest.skip("not selected (--only known-answers)")
    hindsight_url = os.environ.get("ATLAS_LIVE_HINDSIGHT_URL", "").rstrip("/")
    assert hindsight_url, "set ATLAS_LIVE_HINDSIGHT_URL (scripts/memory-conformance.sh does)"
    report.stack["hindsight"] = hindsight_url
    with ExitStack() as stack:
        tradingview = stack.enter_context(serve(FakeTradingView().handle))
        caps = Caps.around(hindsight_url)
        stack.callback(caps.close)
        llm_served = stack.enter_context(serve(caps.llm.handle))
        caps.chain(llm_served.url)
        retains_served = stack.enter_context(serve(caps.retains.handle))
        database_url = stack.enter_context(_fresh_database())
        settings = conformance_settings(
            database_url=database_url,
            workdir=tmp_path_factory.mktemp("conformance"),
            hindsight_url=retains_served.url,
            hindsight_api_key=os.environ.get("ATLAS_LIVE_HINDSIGHT_API_KEY") or None,
            bank_id=new_bank_id(),
            tradingview_url=tradingview.url,
            fast=False,
        )
        run_behaviours(
            report,
            settings,
            caps,
            settle_seconds=SETTLE_SECONDS,
            poll_seconds=POLL_SECONDS,
            read_llm_stats=True,
        )
    failures = [f for f in report.failures() if not f.startswith("known answers")]
    pending = [f"{c.number} ({c.reason})" for c in report.pending()]
    assert not failures, failures
    assert not (report.strict and pending), f"--strict: pending checks {pending}"
