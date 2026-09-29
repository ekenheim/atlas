"""The stack the live Phase 2 gate suite runs against, and the report it writes.

The suite (`tests/live/test_phase2_gate_live.py`) is opt-in by environment, on top of the
`live` marker (see `docs/runbooks.md`, "Live test suite"):

- `ATLAS_LIVE_TESTS=1`: **live**. Real Hindsight 0.10.1 (`ATLAS_LIVE_HINDSIGHT_URL`, default
  the Compose `hindsight` profile at `http://127.0.0.1:58888`) with MiniMax behind LiteLLM
  (`ATLAS_LITELLM_URL`/`ATLAS_LITELLM_API_KEY`). Retains and reflects spend MiniMax quota.
- `ATLAS_LIVE_TESTS=rehearse`: the same scenarios against the recorded Hindsight fake and the
  LiteLLM `/model/info` fake, served on localhost. No external call is made; it checks the
  suite's own wiring, not Hindsight or the model.
- anything else (or unset): every scenario is skipped.

`ATLAS_LIVE_STOP_BEFORE_LLM=1` stops a run before its first LLM-backed call: it runs the
preflight, migrates a fresh database, applies the template (only if it has no mental models,
whose import would queue refreshes) and ingests the fixtures with retention off; the LLM-backed
scenarios are then skipped.

The preflight refuses a run (`pytest.exit`, exit status 4) under `CI`, when a service is
unreachable, when Hindsight isn't 0.10.1, or when a LiteLLM alias isn't routed. It reads only
`/health`, `/version` and `/model/info`, which call no model.
"""

import json
import os
import time
import uuid
from collections.abc import Callable, Generator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx2
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from atlas.hindsight import HindsightError, HindsightGateway, HindsightNotFound
from atlas.llm_routes import LiteLLMError, LiteLLMRoutes
from tests.fakes.hindsight import ChunkContent, RecordedHindsight
from tests.fakes.litellm import API_KEY, FakeLiteLLM
from tests.fakes.serve import Served, serve

type Mode = Literal["live", "rehearse"]

REPO = Path(__file__).parents[2]
HINDSIGHT_VERSION = "0.10.1"
DEFAULT_HINDSIGHT_URL = "http://127.0.0.1:58888"  # the Compose `hindsight` profile
DEFAULT_ADMIN_DATABASE_URL = "postgresql+psycopg://atlas:atlas@127.0.0.1:55432/atlas"
DEFAULT_FORMS = "10-Q"  # the small profile: ~18k characters of the two companies' 10-Qs
REFUSED = 4  # pytest's exit status when the preflight refuses a run
# Each Phase 2 scenario's outcome, kept by tests/live/conftest.py for the report.
OUTCOMES: dict[str, dict[str, str]] = {}


def live_mode() -> Mode | None:
    """The opt-in mode from `ATLAS_LIVE_TESTS`, or None: the suite is not enabled."""
    value = os.environ.get("ATLAS_LIVE_TESTS", "").strip().lower()
    if value in {"1", "true", "yes", "live"}:
        return "live"
    if value == "rehearse":
        return "rehearse"
    return None


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _number(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    return float(value) if value else default


class Refused(Exception):
    """The preflight found the stack unusable; nothing was sent to a model."""


@dataclass
class Rehearsal:
    """The recorded fakes standing in for Hindsight and the model, served on localhost.

    The fake answers the calls a real run makes with recorded responses (and the derivations
    documented in `tests/fakes/hindsight.py`). Where a real run waits on Hindsight's own work,
    the rehearsal plays it: the cover sections come back with zero facts, consolidation yields
    one observation over both companies' Item 1 facts, and the reflect answer is scripted to
    cite those facts, the observation and a raw chunk, with one verbatim and one paraphrased
    quote.
    """

    fake: RecordedHindsight
    hindsight: Served
    litellm: Served

    # Verbatim in the recorded 10-Q fixtures' Item 1 (the quote rule folds the line break).
    LITE_QUOTE = "LUMENTUM HOLDINGS INC. CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS"
    COHR_QUOTE = "Condensed Consolidated Balance Sheets (Unaudited)"
    PARAPHRASE = "Lumentum's revenue roughly doubled on strong datacenter demand"

    @classmethod
    @contextmanager
    def serving(cls) -> Generator["Rehearsal"]:
        fake = RecordedHindsight()
        fake.derive_memories()
        fake.report_zero_facts(lambda document_id: document_id.endswith(":cover"))
        with serve(fake.transport.handle_request) as hindsight:
            with serve(FakeLiteLLM().handle) as litellm:
                yield cls(fake, hindsight, litellm)
                litellm.raise_errors()
            hindsight.raise_errors()

    def consolidate(self, item_1_documents: Sequence[str]) -> str:
        return self.fake.derive_observation(item_1_documents)

    def script_reflect(self, item_1_documents: Sequence[str], observation: str | None) -> None:
        cited: list[str | ChunkContent] = [self.fake.derived_fact(d) for d in item_1_documents]
        if observation:
            cited.append(observation)
        cited.append(ChunkContent(item_1_documents[0]))
        self.fake.script_reflect(
            f"Lumentum's 10-Q opens its statements with \"{self.LITE_QUOTE}\", and Coherent's "
            f'with "{self.COHR_QUOTE}". One summary claims "{self.PARAPHRASE}".',
            cited,
        )


@dataclass
class LiveStack:
    """Where the suite's Hindsight, LiteLLM and databases are, and how patient it is."""

    mode: Mode
    stop_before_llm: bool
    hindsight_url: str
    litellm_url: str
    litellm_api_key: str
    bank_id: str
    extract_alias: str
    reflect_alias: str
    forms: str
    admin_database_url: str
    keep_database: bool
    retain_deadline_seconds: float
    consolidation_wait_seconds: float
    poll_timeout_seconds: float
    poll_interval_seconds: float
    poll_attempts: int
    idle_sleep_seconds: float
    rehearsal: Rehearsal | None = None
    # Bearer key for an authenticated Hindsight (the cluster's tenant key); None locally.
    hindsight_api_key: str | None = None

    @property
    def aliases(self) -> list[str]:
        return list(dict.fromkeys([self.extract_alias, self.reflect_alias]))

    def gateway(self) -> HindsightGateway:
        return HindsightGateway(self.hindsight_url, self.bank_id, self.hindsight_api_key)

    def preflight(self) -> dict[str, Any]:
        """Check the stack without calling a model; raise `Refused` if it can't be used."""
        if self.mode == "live" and os.environ.get("CI"):
            raise Refused("CI is set: the live suite never runs in CI")
        if self.mode == "live" and not (self.litellm_url and self.litellm_api_key):
            raise Refused("ATLAS_LITELLM_URL and ATLAS_LITELLM_API_KEY are required")
        version_basis = "observed"
        with self.gateway() as gateway:
            try:
                health = gateway.server_health()
                if not health.is_healthy:
                    raise Refused(f"Hindsight at {self.hindsight_url} reports {health.status!r}")
                api_version = gateway.server_version().api_version
            except HindsightNotFound:
                # Behind a route that exposes only /v1 (the home cluster's HTTPRoute sends the
                # rest to the control-plane UI), /health and /version can't be reached. Check
                # liveness and auth with a /v1 read instead, and take the version as declared.
                api_version = self._check_v1_only_route()
                version_basis = "declared (ATLAS_LIVE_HINDSIGHT_VERSION)"
            except HindsightError as error:
                raise Refused(f"Hindsight at {self.hindsight_url} is unusable: {error}") from None
        if api_version != HINDSIGHT_VERSION:
            raise Refused(f"Hindsight is {api_version}, not {HINDSIGHT_VERSION}")
        try:
            with LiteLLMRoutes(self.litellm_url, self.litellm_api_key) as litellm:
                routes = litellm.routes(self.aliases)
        except LiteLLMError as error:
            raise Refused(
                f"LiteLLM: {error} (set ATLAS_LLM_EXTRACT_ALIAS/ATLAS_LLM_REFLECT_ALIAS to "
                "routed aliases, e.g. MiniMax-M3, until atlas-extract/atlas-reflect exist)"
            ) from None
        try:
            admin = create_engine(self.admin_database_url)
            with admin.connect() as connection:
                connection.execute(text("SELECT 1"))
            admin.dispose()
        except Exception as error:
            raise Refused(f"the app Postgres is unreachable: {type(error).__name__}") from None
        return {
            "hindsight_url": self.hindsight_url,
            "hindsight_version": api_version,
            "hindsight_version_basis": version_basis,
            "bank_id": self.bank_id,
            "routed_models": {
                alias: [each.model_dump(mode="json") for each in deployments]
                for alias, deployments in routes.items()
            },
        }

    def _check_v1_only_route(self) -> str:
        """Liveness and auth via `GET /v1/default/banks`; the version from the environment."""
        headers = (
            {"Authorization": f"Bearer {self.hindsight_api_key}"} if self.hindsight_api_key else {}
        )
        try:
            response = httpx2.get(
                f"{self.hindsight_url.rstrip('/')}/v1/default/banks", headers=headers, timeout=15
            )
        except httpx2.HTTPError as error:
            raise Refused(f"Hindsight at {self.hindsight_url} is unreachable: {error}") from None
        if response.status_code != 200:
            raise Refused(
                f"Hindsight at {self.hindsight_url}: GET /v1/default/banks answered "
                f"{response.status_code} (is ATLAS_LIVE_HINDSIGHT_API_KEY set?)"
            )
        declared = os.environ.get("ATLAS_LIVE_HINDSIGHT_VERSION", "")
        if not declared:
            raise Refused(
                f"Hindsight at {self.hindsight_url} exposes only /v1, so its version can't be "
                "read: set ATLAS_LIVE_HINDSIGHT_VERSION to the deployed version (e.g. 0.10.1)"
            )
        return declared

    @contextmanager
    def fresh_database(self) -> Generator[str]:
        """A new, empty app database on the admin URL's server (dropped unless kept)."""
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        name = f"atlas_live_{stamp}_{uuid.uuid4().hex[:6]}"
        admin = create_engine(self.admin_database_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            yield (
                make_url(self.admin_database_url)
                .set(database=name)
                .render_as_string(hide_password=False)
            )
        finally:
            if not self.keep_database:
                with admin.connect() as connection:
                    connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            admin.dispose()

    def wait_for_consolidation(self, item_1_documents: Sequence[str]) -> dict[str, Any]:
        """Let Hindsight consolidate observations: until the count holds steady, or a timeout."""
        if self.rehearsal is not None:
            observation = self.rehearsal.consolidate(item_1_documents)
            return {"observations": 1, "observation_ids": [observation], "waited_seconds": 0}
        started = time.monotonic()
        counts: list[int] = []
        with self.gateway() as gateway:
            while True:
                counts.append(gateway.list_observations(limit=1).total)
                steady = len(counts) >= 2 and counts[-1] == counts[-2] and counts[-1] > 0
                waited = time.monotonic() - started
                if steady or waited >= self.consolidation_wait_seconds:
                    break
                time.sleep(15)
        return {"observations": counts[-1], "counts_seen": counts, "waited_seconds": round(waited)}

    def before_reflect(self, item_1_documents: Sequence[str], observation: str | None) -> None:
        """Live: nothing (the model answers). Rehearsal: script the fake's answer."""
        if self.rehearsal is not None:
            self.rehearsal.script_reflect(item_1_documents, observation)

    def llm_usage(self) -> dict[str, Any] | None:
        """The bank's LLM request counts and tokens from Hindsight (live only)."""
        if self.rehearsal is not None:
            return None
        with self.gateway() as gateway:
            stats = gateway.llm_request_stats(period="1d")
        return stats.model_dump(mode="json")


@contextmanager
def live_stack(mode: Mode) -> Generator[LiveStack]:
    """The configured stack; in rehearsal, the fakes are served for as long as it's open."""
    env = os.environ.get
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    with ExitStack() as stack:
        rehearsal: Rehearsal | None = None
        if mode == "rehearse":
            rehearsal = stack.enter_context(Rehearsal.serving())
            hindsight_url, litellm_url, litellm_key = (
                rehearsal.hindsight.url,
                rehearsal.litellm.url,
                API_KEY,
            )
            # The bank the template recordings were made in, so apply-template replays.
            bank_id = rehearsal.fake.recording("research_template/01-import-dry-run").bank_id
        else:
            hindsight_url = env("ATLAS_LIVE_HINDSIGHT_URL") or DEFAULT_HINDSIGHT_URL
            litellm_url = env("ATLAS_LITELLM_URL", "")
            litellm_key = env("ATLAS_LITELLM_API_KEY", "")
            bank_id = env("ATLAS_LIVE_BANK_ID") or f"atlas-live-{stamp}"
        rehearsing = mode == "rehearse"
        yield LiveStack(
            mode=mode,
            stop_before_llm=_flag("ATLAS_LIVE_STOP_BEFORE_LLM"),
            hindsight_url=hindsight_url,
            litellm_url=litellm_url,
            litellm_api_key=litellm_key,
            bank_id=bank_id,
            extract_alias=env("ATLAS_LLM_EXTRACT_ALIAS") or "atlas-extract",
            reflect_alias=env("ATLAS_LLM_REFLECT_ALIAS") or "atlas-reflect",
            forms=env("ATLAS_LIVE_FORMS") or DEFAULT_FORMS,
            admin_database_url=env("ATLAS_TEST_DATABASE_URL") or DEFAULT_ADMIN_DATABASE_URL,
            keep_database=_flag("ATLAS_LIVE_KEEP_DATABASE"),
            retain_deadline_seconds=_number("ATLAS_LIVE_RETAIN_DEADLINE_SECONDS", 3600),
            consolidation_wait_seconds=_number("ATLAS_LIVE_CONSOLIDATION_WAIT_SECONDS", 300),
            # A poll job waits this long for its operation (below the 300 s job lease) and is
            # retried up to the attempts bound: 15 x 240 s covers the full profile's 10-Ks.
            poll_timeout_seconds=0.3 if rehearsing else 240,
            poll_interval_seconds=0.01 if rehearsing else 5,
            poll_attempts=5 if rehearsing else 15,
            idle_sleep_seconds=0 if rehearsing else 10,
            rehearsal=rehearsal,
            hindsight_api_key=None if rehearsing else (env("ATLAS_LIVE_HINDSIGHT_API_KEY") or None),
        )


@dataclass
class LiveReport:
    """What a run saw, written to `ATLAS_LIVE_RESULTS_DIR` as results.json and summary.md."""

    mode: Mode
    stop_before_llm: bool
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    sections: dict[str, Any] = field(default_factory=dict[str, Any])
    outcomes: dict[str, dict[str, str]] = field(default_factory=lambda: OUTCOMES)

    def add(self, name: str, value: Any) -> None:
        self.sections[name] = value

    def write(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        results = {
            "mode": self.mode,
            "stop_before_llm": self.stop_before_llm,
            "started_at": self.started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "tests": self.outcomes,
            **self.sections,
        }
        (directory / "results.json").write_text(
            json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8"
        )
        (directory / "summary.md").write_text(self.summary(results), encoding="utf-8")

    def summary(self, results: dict[str, Any]) -> str:
        """A Markdown digest to copy into docs/implementation-log.md."""
        kind = {"live": "LIVE (real Hindsight + MiniMax via LiteLLM)", "rehearse": "REHEARSAL"}
        lines = [
            f"# Live Phase 2 gate run: {kind[self.mode]}",
            "",
            f"- started {results['started_at']}, finished {results['finished_at']}",
        ]
        if self.mode == "rehearse":
            lines.append("- rehearsal: the recorded fakes on localhost; **nothing was live**")
        if self.stop_before_llm:
            lines.append("- stopped before any LLM-backed call (ATLAS_LIVE_STOP_BEFORE_LLM)")
        stack = results.get("stack", {})
        for key in (
            "hindsight_url",
            "hindsight_version",
            "hindsight_version_basis",
            "bank_id",
            "forms",
            "database",
        ):
            if key in stack:
                lines.append(f"- {key}: `{stack[key]}`")
        for alias, deployments in stack.get("routed_models", {}).items():
            models = ", ".join(f"{d['model']} ({d['model_id']})" for d in deployments)
            lines.append(f"- alias `{alias}` -> {models}")
        lines += ["", "## Tests", ""]
        for name, outcome in self.outcomes.items():
            detail = f": {outcome['detail']}" if outcome.get("detail") else ""
            lines.append(f"- `{name}`: **{outcome['outcome']}**{detail}")
        for name, render in _SUMMARY_SECTIONS:
            if name in results:
                lines += ["", f"## {name.replace('_', ' ').capitalize()}", ""]
                lines += render(results[name])
        return "\n".join(lines) + "\n"


def _json_lines(value: Any) -> list[str]:
    return ["```json", json.dumps(value, indent=2, default=str), "```"]


_SUMMARY_SECTIONS: list[tuple[str, Callable[[Any], list[str]]]] = [
    (name, _json_lines)
    for name in (
        "template",
        "ingest",
        "retention",
        "consolidation",
        "recall",
        "reflect",
        "zero_fact",
        "llm_usage",
    )
]
