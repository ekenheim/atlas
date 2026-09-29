"""The shared test harness: settings for tests, the Atlas harness (a fresh database, the CLI,
single worker passes and the API, with Hindsight served on localhost), a controllable clock,
and the fixture paths, URLs and values more than one test module uses.

Test modules import from here (or from `tests.fakes`), never from each other.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import create_engine

from atlas.api.app import create_app
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.settings import Settings
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import API_KEY

REPO = Path(__file__).parents[1]
THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"
TEMPLATE = REPO / "configs" / "hindsight" / "bank-template.json"
EDGAR_FIXTURES = REPO / "tests" / "fixtures" / "edgar"
# The bank the template recordings were made in, so `apply-template` replays as recorded.
BANK = RecordedHindsight().recording("research_template/01-import-dry-run").bank_id

# A database URL nothing listens on, for settings whose database is never reached.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://atlas:atlas@127.0.0.1:1/atlas"

LITE_10K = "https://www.sec.gov/Archives/edgar/data/1633978/000162828026057358/lite-20260627.htm"
# The Item headings of the fixtures' 10-Ks (both trimmed after Item 7).
TEN_K_ANCHORS = [
    "cover",
    "part-i-item-1",
    "part-i-item-1a",
    "part-i-item-1b",
    "part-i-item-1c",
    "part-i-item-2",
    "part-i-item-3",
    "part-i-item-4",
    "part-ii-item-5",
    "part-ii-item-6",
    "part-ii-item-7",
]
ITEM_1 = "part-i-item-1"
# From the Lumentum FY2026 10-K's Item 1 (the recorded fixture's parsed text): a passage with
# a typographic apostrophe.
LITE_APOSTROPHE = (
    "Components represent foundational parts that support or enable that system\u2019s operation"
)

# What LiteLLM (behind Hindsight's `openai` provider) reports when MiniMax is capped out.
QUOTA_ERROR = (
    "Error code: 429 - {'error': {'message': 'litellm.RateLimitError: RateLimitError:"
    " MinimaxException - rate limit exceeded', 'type': None, 'param': None, 'code': '429'}}"
)


def make_settings(archive_root: Path, **overrides: Any) -> Settings:
    """Settings from these values only (no environment, no .env): an unreachable database
    and the `local-researcher` actor unless `overrides` say otherwise."""
    return Settings.model_validate(
        {
            "database_url": UNREACHABLE_DATABASE_URL,
            "actor": "local-researcher",
            "archive_root": archive_root,
            **overrides,
        }
    )


@dataclass
class Clock:
    """A controllable clock: the pacing clock, or the application clock of a handler."""

    now: datetime

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def at(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


type Metrics = dict[tuple[str, frozenset[tuple[str, str]]], float]


def scrape_metrics(api: TestClient) -> Metrics:
    """The API's `/metrics` as {(sample name, labels): value}."""
    response = api.get("/metrics")
    assert response.status_code == 200
    return {
        (sample.name, frozenset(sample.labels.items())): sample.value
        for family in text_string_to_metric_families(response.text)
        for sample in family.samples
    }


class Atlas:
    """A migrated database, the `atlas` CLI, single worker passes and the API, with Hindsight
    (and optionally LiteLLM) served at the given URLs. `overrides` are extra settings."""

    def __init__(
        self,
        database_url: str,
        tmp_path: Path,
        hindsight_url: str,
        litellm_url: str | None = None,
        **overrides: Any,
    ) -> None:
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.archive = tmp_path / "archive"
        self.archive.mkdir(exist_ok=True)
        self.fixtures = EDGAR_FIXTURES
        self.hindsight_url = hindsight_url
        self.litellm_url = litellm_url
        self.overrides = overrides
        self.engine = create_engine(database_url)
        self.api = TestClient(create_app(self.settings()))

    def settings(self) -> Settings:
        providers: dict[str, Any] = {}
        if self.litellm_url is not None:
            providers = {"litellm_url": self.litellm_url, "litellm_api_key": API_KEY}
        values: dict[str, Any] = {
            "database_url": self.database_url,
            "themes_config": THEMES,
            "sec_fixtures_dir": self.fixtures,
            "hindsight_url": self.hindsight_url,
            "hindsight_bank_id": BANK,
            "retain_poll_timeout_seconds": 0.3,
            "retain_poll_interval_seconds": 0.01,
        }
        return make_settings(self.archive, **(values | providers | self.overrides))

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp_path),
            "ATLAS_DATABASE_URL": self.database_url,
            "ATLAS_ACTOR": "local-researcher",
            "ATLAS_ARCHIVE_ROOT": str(self.archive),
            "ATLAS_THEMES_CONFIG": str(THEMES),
            "ATLAS_SEC_FIXTURES_DIR": str(self.fixtures),
            "ATLAS_HINDSIGHT_URL": self.hindsight_url,
            "ATLAS_HINDSIGHT_BANK_ID": BANK,
            "ATLAS_HINDSIGHT_TEMPLATE_PATH": str(TEMPLATE),
        }
        return subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=self.tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def apply_template(self) -> None:
        applied = self.cli("hindsight", "apply-template")
        assert applied.returncode == 0, applied.stderr

    def worker_pass(self) -> int:
        return Worker(JobQueue(self.engine), builtin_registry(self.settings())).run_once()

    def enqueue(self, *args: str) -> str:
        enqueued = self.cli(*args)
        assert enqueued.returncode == 0, enqueued.stderr
        return json.loads(enqueued.stdout)["id"]

    def ingest(self, key: str, company: str = "lumentum") -> dict[str, Any]:
        """`atlas ingest`, then one worker pass (which also runs the retention jobs)."""
        job_id = self.enqueue("ingest", "--company", company, "--key", key)
        self.worker_pass()
        return self.get(f"/api/v1/jobs/{job_id}")

    def ingest_company(self, company: str) -> None:
        """Ingest the company (keyed by its slug) and check the ingest job succeeded."""
        job = self.ingest(company, company)
        assert job["status"] == "succeeded", job["failures"]

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def company(self, slug: str) -> dict[str, Any]:
        companies = self.get("/api/v1/companies")["items"]
        return next(company for company in companies if company["slug"] == slug)

    def versions(self, url: str, company: str = "lumentum") -> list[dict[str, Any]]:
        sources = self.get(f"/api/v1/companies/{self.company(company)['id']}/sources", limit=100)
        source = next(s for s in sources["items"] if s["canonical_url"] == url)
        return self.get(f"/api/v1/sources/{source['id']}/versions")["items"]

    def version(self, url: str, company: str = "lumentum") -> dict[str, Any]:
        (version,) = self.versions(url, company)
        return self.get(f"/api/v1/source-versions/{version['id']}")

    def memory(self, version_id: str) -> dict[str, Any]:
        return self.get(f"/api/v1/source-versions/{version_id}/memory")

    def section(self, url: str, company: str, anchor: str = ITEM_1) -> dict[str, Any]:
        """The section's memory document, with its Source Version."""
        version = self.version(url, company)
        memory = self.memory(version["id"])
        document = next(d for d in memory["documents"] if d["section_anchor"] == anchor)
        return document | {"version": version}

    def parsed(self, version_id: str) -> str:
        response = self.api.get(
            f"/api/v1/source-versions/{version_id}/content", params={"kind": "parsed"}
        )
        assert response.status_code == 200, response.text
        return response.text

    def recall(self, query: str, **scope: Any) -> Any:
        response = self.api.post("/api/v1/memory/recall", json={"query": query, "scope": scope})
        assert response.status_code == 200, response.text
        return response.json()

    def ask(self, question: str, **body: Any) -> dict[str, Any]:
        """POST a reflect question; returns the accepted response."""
        scope = body.pop("scope", {"theme_ids": ["photonics"]})
        response = self.api.post(
            "/api/v1/memory/reflect", json={"question": question, "scope": scope, **body}
        )
        assert response.status_code == 202, response.text
        return response.json()

    def metrics(self) -> Metrics:
        return scrape_metrics(self.api)

    def reflect(self, question: str, **body: Any) -> dict[str, Any]:
        """Ask, run the worker, and return the stored answer."""
        accepted = self.ask(question, **body)
        self.worker_pass()
        return self.get(f"/api/v1/memory/reflect/{accepted['research_answer']['id']}")


def assert_source(source: dict[str, Any], section: dict[str, Any], company: dict[str, Any]):
    """The citation source is exactly this section of this Source Version."""
    version = section["version"]
    assert source["document_id"] == section["document_id"]
    assert source["source_version_id"] == version["id"]
    assert source["source_document_id"] == version["source_document"]["id"]
    assert source["company_id"] == company["id"]
    assert source["section_anchor"] == section["section_anchor"]
    assert source["section_char_start"] == section["char_start"]
    assert source["section_char_end"] == section["char_end"]
    assert source["available_at"] == version["available_at"]
    assert source["available_at_basis"] == "sec_acceptance"
