"""Research sessions (beliefs ticket 08): open, record Facts into, close and read them.

Seam: the `/api/v1` API on a fresh database holding Lumentum's recorded EDGAR filings, quoting
the recorded Q4 FY26 press release as `test_facts` does. A pipeline investigation appearing as
a session is tested with the argument plan (`test_argument_plan`).
"""

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
ACTOR = "session-test-owner"
REVENUE_QUOTE = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
REVENUE_SPAN = (1604, 1676)
QUESTION = "Is laser capacity the constraint on AI optics?"
NO_SUCH_ID = "00000000-0000-0000-0000-000000000000"


class Atlas:
    def __init__(self, database_url: str, tmp_path: Path) -> None:
        archive = tmp_path / "archive"
        archive.mkdir(exist_ok=True)
        self.engine = create_engine(database_url)
        settings = make_settings(
            archive,
            database_url=database_url,
            actor=ACTOR,
            themes_config=THEMES,
            sec_fixtures_dir=EDGAR_FIXTURES,
        )
        self.api = TestClient(create_app(settings))
        queue = JobQueue(self.engine, actor=Actor(ACTOR))
        queue.enqueue(INGEST_KIND, "lumentum", ingest_payload("lumentum", ["8-K"], None))
        assert Worker(queue, builtin_registry(settings)).run_once() == 1

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def company_id(self) -> str:
        return next(
            c["id"] for c in self.get("/api/v1/companies")["items"] if c["slug"] == "lumentum"
        )

    def fact_body(self, session_id: str | None) -> dict[str, Any]:
        company = self.company_id()
        documents = self.get(f"/api/v1/companies/{company}/sources", limit=100)["items"]
        version = next(d["latest_version_id"] for d in documents if d["canonical_url"] == URL_EX991)
        start, end = REVENUE_SPAN
        return {
            "subject_company_id": company,
            "source_version_id": version,
            "quote": REVENUE_QUOTE,
            "span_start": start,
            "span_end": end,
            "epistemic_type": "company_claim",
            "step": "context",
            "statement": "Lumentum's fourth-quarter fiscal 2026 net revenue was $1.01 billion.",
            "quantity": {"value": 1.01, "unit": "USD billion", "metric": "net revenue"},
            "period": "Q4 FY2026",
            "status": "in_effect",
            "session_id": session_id,
        }

    def open(self, **overrides: Any) -> dict[str, Any]:
        body = {
            "question": QUESTION,
            "theme": "photonics",
            "seed_company_ids": [self.company_id()],
            "as_of": "2026-09-30T00:00:00Z",
            "model": "claude-fable-5-1",
            "actor": "claude-session",
        } | overrides
        response = self.api.post("/api/v1/sessions", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    def actions(self, entity_id: str) -> list[str]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    text("SELECT action FROM audit_event WHERE entity_id = :id ORDER BY id"),
                    {"id": entity_id},
                ).scalars()
            )


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path)
    yield harness
    harness.engine.dispose()


def test_a_session_is_opened_gets_its_facts_and_is_closed_with_its_card(atlas: Atlas) -> None:
    opened = atlas.open()
    assert opened["kind"] == "claude"
    assert opened["actor"] == "claude-session"
    assert opened["finished_at"] is None
    assert opened["facts"] == 0

    recorded = atlas.api.post("/api/v1/facts", json=atlas.fact_body(opened["id"]))
    assert recorded.status_code == 201, recorded.text
    fact_id = recorded.json()["fact"]["id"]
    assert recorded.json()["fact"]["session_id"] == opened["id"]
    assert atlas.get("/api/v1/facts", session_id=opened["id"])["total"] == 1

    card: dict[str, Any] = {
        "steps": [{"step": "constraint", "status": "supported", "statements": []}],
        "open_questions": ["Who else makes InP lasers?"],
    }
    closed = atlas.api.post(
        f"/api/v1/sessions/{opened['id']}/close",
        json={"usage": {"calls": 12, "tokens": 3456}, "card": card, "card_markdown": "# Card"},
    )
    assert closed.status_code == 200, closed.text

    read = atlas.get(f"/api/v1/sessions/{opened['id']}")
    assert read["finished_at"] >= read["started_at"]
    assert read["usage"] == {"calls": 12, "tokens": 3456}
    assert read["card"] == card
    assert read["card_markdown"] == "# Card"
    assert read["facts"] == 1
    assert [fact["id"] for fact in read["fact_items"]] == [fact_id]
    assert atlas.actions(opened["id"]) == ["research_session.opened", "research_session.closed"]


def test_the_list_filters_by_theme_and_lists_newest_first(atlas: Atlas) -> None:
    first = atlas.open()
    second = atlas.open(theme="robotics", question="Who limits actuator supply?")

    everything = atlas.get("/api/v1/sessions")
    photonics = atlas.get("/api/v1/sessions", theme="photonics")

    assert [s["id"] for s in everything["items"]] == [second["id"], first["id"]]
    assert [s["id"] for s in photonics["items"]] == [first["id"]]
    assert photonics["total"] == 1


def test_a_closed_session_cannot_be_closed_again_and_unknown_ones_are_not_found(
    atlas: Atlas,
) -> None:
    opened = atlas.open()
    assert atlas.api.post(f"/api/v1/sessions/{opened['id']}/close", json={}).status_code == 200

    again = atlas.api.post(f"/api/v1/sessions/{opened['id']}/close", json={})

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "session_closed"
    assert atlas.api.get(f"/api/v1/sessions/{NO_SUCH_ID}").status_code == 404
    assert atlas.api.post(f"/api/v1/sessions/{NO_SUCH_ID}/close", json={}).status_code == 404


def test_a_fact_for_an_unknown_session_or_a_session_with_an_unknown_seed_is_refused(
    atlas: Atlas,
) -> None:
    fact = atlas.api.post("/api/v1/facts", json=atlas.fact_body(NO_SUCH_ID))
    seed = atlas.api.post(
        "/api/v1/sessions",
        json={
            "question": QUESTION,
            "theme": "photonics",
            "seed_company_ids": [NO_SUCH_ID],
            "as_of": "2026-09-30T00:00:00Z",
        },
    )

    assert fact.status_code == 422
    assert fact.json()["error"]["code"] == "unknown_session"
    assert seed.status_code == 422
    assert seed.json()["error"]["code"] == "unknown_company"
