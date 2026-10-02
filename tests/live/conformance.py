"""The memory conformance check's driver (memory-quality ticket 14): a throwaway bank prepared
through Atlas's real retain path, then the checks.

Used by the CI rehearsal (`tests/integration/test_memory_conformance.py`: the recorded Hindsight
fake) and the live run (`tests/live/test_memory_conformance_live.py`: the real Hindsight); both
through `scripts/memory-conformance.sh`. See `docs/runbooks.md`, "Memory conformance".

`throwaway_bank` makes a fresh Atlas (its own database and archive) whose Hindsight bank is
`atlas-conformance-<random>`, applies the research bank's template to it, ingests the recorded
EDGAR fixtures of two companies (Lumentum's 8-K exhibit and 10-Q, Coherent's 10-K and 10-Q:
Coherent's 10-K Item 5 names Lumentum) and the synthetic call transcript (TradingView's fake
on localhost, synthetic content), lets the worker retain them with triage off (every section,
no LLM call by Atlas), asks for a consolidation, and yields the `BehaviourBank` the checks
read. On the way out, whatever happened (a failure, an abort, an interrupt), it deletes the
bank and records whether that worked.

The caps are the counting proxies' (`tests/live/verify.py`, `CappedProxy`): Atlas reaches
Hindsight only through two of them, one counting retain operations, one counting the requests
that make Hindsight call its LLM besides extraction (reflect, a mental-model refresh,
consolidation). A request over a cap is refused (HTTP 400) and the run is reported aborted.
"""

import json
import time
import uuid
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx2
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy import Engine, create_engine, text

from atlas.api.app import create_app
from atlas.audit import Actor
from atlas.bank_template import BankTemplate, apply_template
from atlas.companies import load_universe, seed
from atlas.conformance import (
    AtlasApi,
    BehaviourBank,
    Check,
    ConformanceReport,
    Usage,
    run_checks,
)
from atlas.hindsight import CONFORMANCE_BANK_PREFIX, HindsightGateway, HindsightNotFound
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from atlas.settings import Settings
from atlas.tradingview import TokenSet, write_token_file
from tests.fakes.tradingview import ACCESS_TOKEN, REFRESH_TOKEN
from tests.live.verify import CappedProxy, is_retain

REPO = Path(__file__).parents[2]
THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"
TEMPLATE = REPO / "configs" / "hindsight" / "bank-template.json"
EDGAR_FIXTURES = REPO / "tests" / "fixtures" / "edgar"
PROBES = REPO / "configs" / "memory" / "probes.yaml"
KNOWN_ANSWERS = REPO / "configs" / "memory" / "known-answers.yaml"
THEME = "photonics"
# What the throwaway bank holds: each company and the forms ingested from its recorded fixtures.
INGESTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lumentum", ("8-K", "10-Q")),
    ("coherent", ("10-K", "10-Q")),
)
TRANSCRIPT_COMPANY = "lumentum"  # the synthetic call transcript (tests/fixtures/tradingview)
RETAIN_CAP = 10  # retain operations per run (one per Source Version; 5 are expected)
LLM_CAP = 6  # reflect, refresh and consolidation requests per run (4 are expected)


def is_llm_operation(request: httpx2.Request) -> bool:
    """A request that makes Hindsight call its LLM, extraction aside: a reflect, a mental-model
    refresh or a consolidation."""
    path = request.url.path
    return request.method == "POST" and (
        path.endswith("/reflect")
        or path.endswith("/consolidate")
        or ("/mental-models/" in path and path.endswith("/refresh"))
    )


def new_bank_id() -> str:
    return f"{CONFORMANCE_BANK_PREFIX}{uuid.uuid4().hex[:12]}"


@dataclass
class Caps:
    """The two counting proxies Atlas reaches Hindsight through, and the retain bodies seen."""

    retains: CappedProxy
    llm: CappedProxy
    items: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    @classmethod
    def around(
        cls, hindsight_url: str, retain_cap: int = RETAIN_CAP, llm_cap: int = LLM_CAP
    ) -> "Caps":
        """Proxies in front of `hindsight_url`: Atlas -> retains -> llm -> Hindsight. Serve
        `llm` first, then point `retains.upstream` at it (`chain`)."""
        caps = cls(
            retains=CappedProxy("Hindsight retain", "", is_retain, retain_cap),
            llm=CappedProxy("Hindsight LLM", hindsight_url, is_llm_operation, llm_cap),
        )
        counted = caps.retains.counted

        def counted_and_kept(request: httpx2.Request) -> bool:
            if counted(request):
                body = cast(dict[str, Any], json.loads(request.content))
                caps.items.extend(cast(list[dict[str, Any]], body.get("items") or []))
                return True
            return False

        caps.retains.counted = counted_and_kept
        caps.retains.begin_part("conformance", retain_cap)
        caps.llm.begin_part("conformance", llm_cap)
        return caps

    def chain(self, llm_url: str) -> None:
        self.retains.upstream = llm_url

    def refused(self) -> list[str]:
        return [*self.retains.refusals, *self.llm.refusals]

    def usage(self) -> Usage:
        return Usage(
            retain_operations=self.retains.total,
            retain_cap=self.retains.run_cap,
            llm_operations=self.llm.total,
            llm_cap=self.llm.run_cap,
            refused=self.refused(),
        )

    def close(self) -> None:
        self.retains.close()
        self.llm.close()


class Aborted(Exception):
    """The bank could not be prepared as the checks need it (a cap, a timeout)."""


@dataclass
class Outcome:
    """What happened to the throwaway bank, whatever the checks did."""

    bank_id: str
    deleted: bool | None = None
    delete_error: str | None = None


def conformance_settings(
    *,
    database_url: str,
    workdir: Path,
    hindsight_url: str,
    hindsight_api_key: str | None,
    bank_id: str,
    tradingview_url: str,
    fast: bool,
) -> Settings:
    """A fresh Atlas's settings: the recorded EDGAR fixtures, retention triage off, the
    TradingView fake for the transcript, the throwaway bank."""
    token_file = workdir / "tradingview-token.json"
    write_token_file(
        token_file,
        TokenSet(
            access_token=ACCESS_TOKEN,
            refresh_token=REFRESH_TOKEN,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            token_endpoint=f"{tradingview_url}/auth/token",
            client_id="fake-registered-client",
            resource=f"{tradingview_url}/mcp",
        ),
    )
    (workdir / "archive").mkdir(parents=True, exist_ok=True)
    polling: dict[str, Any] = (
        {"retain_poll_timeout_seconds": 0.3, "retain_poll_interval_seconds": 0.01} if fast else {}
    )
    return Settings.model_validate(
        {
            "database_url": database_url,
            "actor": "atlas-conformance",
            "archive_backend": "filesystem",
            "archive_root": workdir / "archive",
            "themes_config": THEMES,
            "hindsight_template_path": TEMPLATE,
            "sec_fixtures_dir": EDGAR_FIXTURES,
            "sec_live": False,
            "hindsight_url": hindsight_url,
            "hindsight_api_key": hindsight_api_key,
            "hindsight_bank_id": bank_id,
            "retention_triage": "off",
            "backfill_window": "",
            "tradingview_enabled": True,
            "tradingview_mcp_url": f"{tradingview_url}/mcp",
            "tradingview_token_file": token_file,
            "tradingview_rate_per_s": 1.0,
            **polling,
        }
    )


def _queued(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM job WHERE status IN ('queued', 'running')")
            ).scalar_one()
        )


def _pending_sections(engine: Engine, bank_id: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM memory_document WHERE bank_id = :bank"
                    " AND retain_state = 'pending'"
                ),
                {"bank": bank_id},
            ).scalar_one()
        )


@contextmanager
def throwaway_bank(
    settings: Settings,
    caps: Caps,
    outcome: Outcome,
    *,
    settle_seconds: float,
    poll_seconds: float,
) -> Generator[BehaviourBank]:
    """Prepare the bank (see the module docstring), yield it, and always delete it."""
    engine = create_engine(settings.database_url)
    gateway = HindsightGateway.from_settings(settings)
    assert gateway is not None
    client = TestClient(create_app(settings))
    queue = JobQueue(engine, actor=Actor.from_settings(settings))

    def drain() -> None:
        deadline = time.monotonic() + settle_seconds
        while True:
            Worker(queue, builtin_registry(settings)).run_once()
            if caps.refused():
                raise Aborted(f"a cap refused {', '.join(caps.refused())}")
            if not _queued(engine) and not _pending_sections(engine, settings.hindsight_bank_id):
                return
            if time.monotonic() > deadline:
                raise Aborted(f"the queue did not settle within {settle_seconds:g} s")
            time.sleep(poll_seconds)

    def enqueue(kind: str, key: str, payload: dict[str, JsonValue]) -> None:
        queue.enqueue(kind, key, payload)

    try:
        actor = Actor.from_settings(settings)
        universe = load_universe(settings.themes_config)
        with engine.begin() as connection:
            seeded = {s.slug: str(s.company_id) for s in seed(connection, actor, universe)}
        template = BankTemplate.load(settings.hindsight_template_path)
        apply_template(engine, gateway, template, actor)
        for slug, forms in INGESTS:
            queue.enqueue(
                INGEST_KIND, f"conformance:{slug}", ingest_payload(slug, list(forms), None)
            )
        queue.enqueue(
            "tradingview_catalog", "conformance:transcript", {"company": TRANSCRIPT_COMPANY}
        )
        drain()
        consolidation = gateway.consolidate()
        if caps.refused():
            raise Aborted(f"a cap refused {', '.join(caps.refused())}")
        gateway.wait_for_operation(
            consolidation.operation_id, timeout=settle_seconds, poll_interval=poll_seconds
        )
        bank = BehaviourBank(
            api=AtlasApi(client),
            gateway=gateway,
            theme=THEME,
            companies={slug: seeded[slug] for slug, _ in INGESTS},
            versions=_versions(engine, settings.hindsight_bank_id),
            retained_items=lambda: list(caps.items),
            template=cast(dict[str, Any], template.manifest),
            settings_fields=frozenset(Settings.model_fields),
            drain=drain,
            enqueue=enqueue,
        )
        yield bank
    finally:
        try:
            gateway.delete_bank()
            outcome.deleted = True
        except HindsightNotFound:
            outcome.deleted = True  # never created: nothing to delete
        except Exception as error:
            outcome.deleted, outcome.delete_error = False, f"{type(error).__name__}: {error}"
        gateway.close()
        client.close()
        engine.dispose()


def run_behaviours(
    report: ConformanceReport,
    settings: Settings,
    caps: Caps,
    *,
    settle_seconds: float,
    poll_seconds: float,
    checks: Sequence[Check] | None = None,
    during: Callable[[BehaviourBank], None] | None = None,
    read_llm_stats: bool = False,
) -> None:
    """Prepare the throwaway bank, run `during` (the rehearsal's known answers) and the checks
    on it into `report`, and record the bank's deletion and the caps' counts whatever happens
    (an interrupt still propagates, after the bank is deleted and the report filled). With
    `read_llm_stats` (live only: the fake has no recording for a throwaway bank), the bank's own
    LLM request log is read before the bank is deleted: what extraction and the rest cost."""
    outcome = Outcome(bank_id=settings.hindsight_bank_id)
    report.bank_id = outcome.bank_id
    stats: dict[str, Any] | None = None
    try:
        with throwaway_bank(
            settings, caps, outcome, settle_seconds=settle_seconds, poll_seconds=poll_seconds
        ) as bank:
            if during is not None:
                during(bank)
            report.behaviours = run_checks(bank, checks)
            if read_llm_stats:
                try:
                    stats = bank.gateway.llm_request_stats(period="1d").model_dump(mode="json")
                except Exception as error:  # the cost is reported, never a reason to fail
                    stats = {"error": f"{type(error).__name__}: {error}"}
            if caps.refused():
                raise Aborted(f"a cap refused {', '.join(caps.refused())}")
    except Aborted as error:
        report.aborted = str(error)
    finally:
        report.bank_deleted = outcome.deleted
        if outcome.delete_error:
            report.stack["bank_delete_error"] = outcome.delete_error
        report.usage = caps.usage()
        report.usage.bank_llm_requests = stats


def _versions(engine: Engine, bank_id: str) -> dict[str, dict[str, str]]:
    """Each Source Version retained into the bank: its company, whether it is a transcript,
    its URL."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT DISTINCT v.id, c.slug, d.provider, d.canonical_url FROM memory_document m"
                " JOIN source_version v ON v.id = m.source_version_id"
                " JOIN source_document d ON d.id = v.source_document_id"
                " JOIN company c ON c.id = d.company_id WHERE m.bank_id = :bank"
            ),
            {"bank": bank_id},
        ).all()
    return {
        str(row.id): {
            "company": str(row.slug),
            "kind": "transcript" if row.provider == "tradingview" else "filing",
            "url": str(row.canonical_url),
        }
        for row in rows
    }
