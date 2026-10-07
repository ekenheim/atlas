"""Facts: a quote with an argument step, a quantity, a period and a status (ticket 02).

Seam: the `/api/v1` API on a fresh database holding Lumentum's recorded EDGAR filings (the
fixture ingest path), quoting the recorded Q4 FY26 press release as parsed by `text-v3`
(offsets pinned by `tests/fixtures/parser/golden.json`, as in `test_assertions`).
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from atlas.api.app import create_app
from atlas.audit import Actor
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from tests.harness import EDGAR_FIXTURES, THEMES, make_settings

URL_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
ACTOR = "fact-test-reviewer"
REVENUE_QUOTE = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
REVENUE_SPAN = (1604, 1676)
NO_SUCH_ID = "00000000-0000-0000-0000-000000000000"


class Atlas:
    def __init__(self, database_url: str, tmp_path: Path) -> None:
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.archive = tmp_path / "archive"
        self.archive.mkdir(exist_ok=True)
        self.engine = create_engine(database_url)
        self.settings = make_settings(
            self.archive,
            database_url=database_url,
            actor=ACTOR,
            themes_config=THEMES,
            sec_fixtures_dir=EDGAR_FIXTURES,
        )
        self.api = TestClient(create_app(self.settings))
        queue = JobQueue(self.engine, actor=Actor(ACTOR))
        queue.enqueue(INGEST_KIND, "lumentum", ingest_payload("lumentum", ["8-K"], None))
        assert Worker(queue, builtin_registry(self.settings)).run_once() == 1

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def company_id(self) -> str:
        companies = self.get("/api/v1/companies")["items"]
        return next(c["id"] for c in companies if c["slug"] == "lumentum")

    def version_id(self) -> str:
        documents = self.get(f"/api/v1/companies/{self.company_id()}/sources", limit=100)
        return next(
            d["latest_version_id"] for d in documents["items"] if d["canonical_url"] == URL_EX991
        )

    def body(self, **overrides: Any) -> dict[str, Any]:
        start, end = REVENUE_SPAN
        body: dict[str, Any] = {
            "subject_company_id": self.company_id(),
            "source_version_id": self.version_id(),
            "quote": REVENUE_QUOTE,
            "span_start": start,
            "span_end": end,
            "epistemic_type": "company_claim",
            "step": "context",
            "statement": "Lumentum's fourth-quarter fiscal 2026 net revenue was $1.01 billion.",
            "quantity": {"value": 1.01, "unit": "USD billion", "metric": "net revenue"},
            "period": "Q4 FY2026",
            "status": "in_effect",
        }
        return body | overrides

    def create(self, **overrides: Any) -> dict[str, Any]:
        response = self.api.post("/api/v1/facts", json=self.body(**overrides))
        assert response.status_code == 201, response.text
        return response.json()["fact"]

    def audit_actions(self, entity_type: str, entity_id: str) -> list[str]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT action FROM audit_event"
                    " WHERE entity_type = :type AND entity_id = :id ORDER BY id"
                ),
                {"type": entity_type, "id": entity_id},
            )
            return [row.action for row in rows]

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp_path),
            "ATLAS_DATABASE_URL": self.database_url,
            "ATLAS_ACTOR": ACTOR,
            "ATLAS_ARCHIVE_ROOT": str(self.archive),
            "ATLAS_THEMES_CONFIG": str(THEMES),
        }
        return subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=self.tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path)
    yield harness
    harness.engine.dispose()


def error_code(response: Any) -> str:
    assert response.status_code == 422, response.text
    return response.json()["error"]["code"]


def test_a_fact_with_a_quantity_a_period_and_a_status_is_recorded_and_read(atlas: Atlas) -> None:
    body = atlas.body()

    response = atlas.api.post("/api/v1/facts", json=body)

    assert response.status_code == 201, response.text
    fact = response.json()["fact"]
    assert isinstance(response.json()["audit_event_id"], int)
    assert (fact["step"], fact["status"], fact["period"]) == ("context", "in_effect", "Q4 FY2026")
    assert fact["quantity"] == body["quantity"]
    assert fact["statement"] == body["statement"]
    underlying = fact["assertion"]
    assert underlying["id"] == fact["id"]
    assert underlying["predicate"] == "fact"
    assert underlying["quote"] == REVENUE_QUOTE
    assert underlying["review_state"] == "unreviewed"
    assert underlying["value_json"]["status"] == "in_effect"
    assert atlas.get(f"/api/v1/facts/{fact['id']}") == fact
    assert atlas.get(f"/api/v1/assertions/{fact['id']}") == underlying
    assert atlas.audit_actions("fact", fact["id"]) == ["fact.created"]
    assert atlas.audit_actions("assertion", fact["id"]) == ["assertion.created"]


def test_a_fact_without_a_quantity_or_period_is_recorded(atlas: Atlas) -> None:
    fact = atlas.create(quantity=None, period=None, status="hedged", step="invalidation")

    assert fact["quantity"] is None
    assert fact["period"] is None
    assert (fact["step"], fact["status"]) == ("invalidation", "hedged")


def test_facts_are_read_by_company_step_and_investigation(atlas: Atlas) -> None:
    constraint = atlas.create(step="constraint")
    relief = atlas.create(step="relief")

    assert {f["id"] for f in atlas.get("/api/v1/facts")["items"]} == {
        constraint["id"],
        relief["id"],
    }
    by_step = atlas.get("/api/v1/facts", step="relief")
    assert [f["id"] for f in by_step["items"]] == [relief["id"]]
    assert by_step["total"] == 1
    assert atlas.get("/api/v1/facts", company_id=atlas.company_id())["total"] == 2
    assert atlas.get("/api/v1/facts", company_id=NO_SUCH_ID)["total"] == 0
    assert atlas.get("/api/v1/facts", investigation_id=NO_SUCH_ID)["total"] == 0
    assert atlas.api.get(f"/api/v1/facts/{NO_SUCH_ID}").status_code == 404


@pytest.mark.parametrize(("field", "value"), [("step", "moat"), ("status", "rumoured")])
def test_an_unknown_step_or_status_is_refused(atlas: Atlas, field: str, value: str) -> None:
    response = atlas.api.post("/api/v1/facts", json=atlas.body(**{field: value}))

    assert error_code(response) == "invalid_request"
    assert atlas.get("/api/v1/facts")["total"] == 0


def test_a_quantity_whose_number_is_not_in_the_quote_is_refused_and_nothing_is_recorded(
    atlas: Atlas,
) -> None:
    quantity = {"value": 2.5, "unit": "USD billion", "metric": "net revenue"}

    response = atlas.api.post("/api/v1/facts", json=atlas.body(quantity=quantity))

    assert error_code(response) == "quantity_not_in_quote"
    assert atlas.get("/api/v1/facts")["total"] == 0
    assert atlas.get("/api/v1/assertions")["total"] == 0


def test_a_quote_that_is_not_at_its_span_is_refused(atlas: Atlas) -> None:
    response = atlas.api.post("/api/v1/facts", json=atlas.body(span_start=0, span_end=72))

    assert error_code(response) == "quote_mismatch"
    assert atlas.get("/api/v1/facts")["total"] == 0


def test_an_unknown_investigation_is_refused(atlas: Atlas) -> None:
    response = atlas.api.post("/api/v1/facts", json=atlas.body(investigation_id=NO_SUCH_ID))

    assert error_code(response) == "unknown_investigation"


def test_a_fact_cannot_be_recorded_as_a_plain_assertion(atlas: Atlas) -> None:
    shared = atlas.body()
    body = {
        key: shared[key]
        for key in (
            "subject_company_id",
            "source_version_id",
            "quote",
            "span_start",
            "span_end",
            "epistemic_type",
        )
    } | {"predicate": "fact", "value_json": {"step": "nonsense"}}

    response = atlas.api.post("/api/v1/assertions", json=body)

    assert error_code(response) == "use_facts"


def test_the_relationship_review_makes_no_edge_from_a_fact(atlas: Atlas) -> None:
    fact = atlas.create()
    payload = json.dumps({"assertion_ids": [fact["id"]]})

    enqueued = atlas.cli(
        "jobs", "enqueue", "review_relationships", "--key", "facts", "--payload", payload
    )
    assert enqueued.returncode == 0, enqueued.stderr
    worked = atlas.cli("worker", "--once")
    assert worked.returncode == 0, worked.stderr

    assert atlas.get("/api/v1/relationships")["total"] == 0
    with atlas.engine.connect() as connection:
        edges = connection.execute(
            text("SELECT count(*) FROM relationship_assertion WHERE assertion_id = :id"),
            {"id": fact["id"]},
        ).scalar_one()
    assert edges == 0
