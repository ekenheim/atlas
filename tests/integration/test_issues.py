"""Issues (beliefs ticket 04): the research frontier.

Seam: the `/api/v1` API on a fresh database holding Lumentum's recorded EDGAR filings (a Fact
to attach as a product is quoted from the recorded Q4 FY26 press release, as in `test_sessions`).
The next action is observed through `GET /issues/next`; the Issues a session's close creates
through `GET /issues`.
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
ACTOR = "issue-test-owner"
REVENUE_QUOTE = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
REVENUE_SPAN = (1604, 1676)
QUESTION = "Is laser capacity the constraint on AI optics?"
THEME = "photonics"
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

    def issue(self, title: str, **overrides: Any) -> dict[str, Any]:
        body = {"title": title, "theme": THEME} | overrides
        response = self.api.post("/api/v1/issues", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    def next(self) -> dict[str, Any]:
        return self.get("/api/v1/issues/next", theme=THEME)

    def record_fact(self) -> str:
        company = self.company_id()
        documents = self.get(f"/api/v1/companies/{company}/sources", limit=100)["items"]
        version = next(d["latest_version_id"] for d in documents if d["canonical_url"] == URL_EX991)
        start, end = REVENUE_SPAN
        response = self.api.post(
            "/api/v1/facts",
            json={
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
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["fact"]["id"]

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


def test_an_issue_narrows_and_requires_others_and_every_write_is_audited(atlas: Atlas) -> None:
    root = atlas.issue(QUESTION, kind="question", company_ids=[atlas.company_id()])
    assert root["status"] == "active"
    assert root["parent_id"] is None
    step = atlas.issue("Constraint", kind="step", narrows=root["id"], priority=1)
    prerequisite = atlas.issue("Read the 10-K", narrows=step["id"])
    dependent = atlas.issue(
        "Compare with Coherent", narrows=step["id"], requires=[prerequisite["id"]]
    )

    assert step["parent_id"] == root["id"]
    assert step["parent_title"] == QUESTION
    assert dependent["requires"] == [prerequisite["id"]]
    assert dependent["blocked"] is True
    assert prerequisite["blocked"] is False
    assert atlas.get(f"/api/v1/issues/{step['id']}")["open_children"] == 2
    listed = atlas.get("/api/v1/issues", theme=THEME)
    assert [i["title"] for i in listed["items"]] == [
        QUESTION,
        "Constraint",
        "Read the 10-K",
        "Compare with Coherent",
    ]
    assert atlas.get("/api/v1/issues", theme="robotics")["total"] == 0
    assert atlas.actions(dependent["id"]) == [
        "issue.created",
        "issue.edge_added",
        "issue.edge_added",
    ]


def test_an_issue_read_by_id_shows_its_edges_from_both_ends(atlas: Atlas) -> None:
    parent = atlas.issue("Parent", kind="question")
    first = atlas.issue("First sub-question", narrows=parent["id"])
    second = atlas.issue("Second sub-question", narrows=parent["id"])
    gate = atlas.issue("Gate")
    atlas.api.post(
        f"/api/v1/issues/{second['id']}/edges", json={"kind": "requires", "parent_id": gate["id"]}
    ).raise_for_status()
    atlas.api.post(f"/api/v1/issues/{gate['id']}/complete").raise_for_status()

    def edges(issue_id: str) -> list[tuple[str, str, str, str, str]]:
        read = atlas.get(f"/api/v1/issues/{issue_id}")
        return [
            (e["kind"], e["direction"], e["issue_id"], e["title"], e["status"])
            for e in read["edges"]
        ]

    assert edges(parent["id"]) == [
        ("narrows", "child", first["id"], "First sub-question", "active"),
        ("narrows", "child", second["id"], "Second sub-question", "active"),
    ]
    assert edges(first["id"]) == [("narrows", "parent", parent["id"], "Parent", "active")]
    assert edges(second["id"]) == [
        ("narrows", "parent", parent["id"], "Parent", "active"),
        ("requires", "parent", gate["id"], "Gate", "complete"),
    ]
    assert edges(gate["id"]) == [
        ("requires", "child", second["id"], "Second sub-question", "active")
    ]
    assert edges(atlas.issue("Alone")["id"]) == []
    # The list is as it was: no edges there, the parent's fields as before.
    listed = {i["id"]: i for i in atlas.get("/api/v1/issues", theme=THEME)["items"]}
    assert "edges" not in listed[parent["id"]]
    assert listed[second["id"]]["parent_id"] == parent["id"]
    assert listed[second["id"]]["requires"] == [gate["id"]]


def test_an_edge_that_would_close_a_cycle_is_refused(atlas: Atlas) -> None:
    a = atlas.issue("A")
    b = atlas.issue("B", requires=[a["id"]])
    c = atlas.issue("C", narrows=b["id"])

    for child, kind, parent in (
        (a["id"], "requires", b["id"]),  # a requires b requires a
        (a["id"], "narrows", c["id"]),  # a under c under b requiring a, across kinds
        (a["id"], "requires", a["id"]),  # itself
    ):
        refused = atlas.api.post(
            f"/api/v1/issues/{child}/edges", json={"kind": kind, "parent_id": parent}
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "issue_cycle"
    assert atlas.get(f"/api/v1/issues/{a['id']}")["requires"] == []

    allowed = atlas.api.post(
        f"/api/v1/issues/{c['id']}/edges", json={"kind": "requires", "parent_id": a["id"]}
    )
    assert allowed.status_code == 200, allowed.text
    assert a["id"] in allowed.json()["requires"]
    missing = atlas.api.post(
        f"/api/v1/issues/{a['id']}/edges", json={"kind": "requires", "parent_id": NO_SUCH_ID}
    )
    assert missing.status_code == 404


def test_complete_and_abandon_close_an_active_issue_once_and_unblock_what_it_gates(
    atlas: Atlas,
) -> None:
    gate = atlas.issue("Gate")
    after = atlas.issue("After", requires=[gate["id"]], priority=9)
    assert atlas.next()["issue"]["id"] == gate["id"]

    done = atlas.api.post(f"/api/v1/issues/{gate['id']}/complete")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "complete"
    assert done.json()["closed_at"] is not None
    assert atlas.next()["issue"]["id"] == after["id"]
    assert atlas.get(f"/api/v1/issues/{after['id']}")["blocked"] is False

    again = atlas.api.post(f"/api/v1/issues/{gate['id']}/abandon")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "issue_not_active"
    dropped = atlas.api.post(f"/api/v1/issues/{after['id']}/abandon")
    assert dropped.json()["status"] == "abandoned"
    assert atlas.next() == {"issue": None, "reason": None}
    assert atlas.get("/api/v1/issues", status="active")["total"] == 0
    assert atlas.actions(gate["id"]) == ["issue.created", "issue.completed"]
    assert atlas.api.post(f"/api/v1/issues/{NO_SUCH_ID}/complete").status_code == 404


def test_an_issue_records_the_belief_or_fact_it_produced(atlas: Atlas) -> None:
    issue = atlas.issue("Constraint", kind="step")
    fact_id = atlas.record_fact()
    belief_id = NO_SUCH_ID

    with_fact = atlas.api.post(f"/api/v1/issues/{issue['id']}/produced", json={"fact_id": fact_id})
    assert with_fact.status_code == 200, with_fact.text
    with_belief = atlas.api.post(
        f"/api/v1/issues/{issue['id']}/produced", json={"belief_id": belief_id}
    )
    assert [(p["belief_id"], p["fact_id"]) for p in with_belief.json()["products"]] == [
        (None, fact_id),
        (belief_id, None),
    ]
    read = atlas.get(f"/api/v1/issues/{issue['id']}")["products"]
    assert [(p["kind"], p["id"]) for p in read] == [("fact", fact_id), ("belief", belief_id)]
    assert all(p["actor"] == ACTOR and p["created_at"] for p in read)
    for body in ({}, {"fact_id": fact_id, "belief_id": belief_id}):
        refused = atlas.api.post(f"/api/v1/issues/{issue['id']}/produced", json=body)
        assert refused.status_code == 422
    unknown = atlas.api.post(f"/api/v1/issues/{issue['id']}/produced", json={"fact_id": NO_SUCH_ID})
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "unknown_product"
    assert atlas.actions(issue["id"]) == [
        "issue.created",
        "issue.product_recorded",
        "issue.product_recorded",
    ]


def test_next_takes_priority_then_the_oldest(atlas: Atlas) -> None:
    assert atlas.next() == {"issue": None, "reason": None}
    first = atlas.issue("First", priority=1)
    atlas.issue("Second", priority=1)
    assert atlas.next()["issue"]["id"] == first["id"]
    urgent = atlas.issue("Urgent", priority=5)
    answer = atlas.next()
    assert (answer["issue"]["id"], answer["reason"]) == (urgent["id"], "priority")


def test_next_prefers_flagged_or_disputed_over_priority(atlas: Atlas) -> None:
    atlas.issue("Urgent", priority=9)
    disputed = atlas.issue("Constraint again", body="Step disputed by a judged contradiction.")
    answer = atlas.next()
    assert (answer["issue"]["id"], answer["reason"]) == (disputed["id"], "flagged_or_disputed")


def test_next_takes_a_step_with_no_belief_first_until_one_is_produced(atlas: Atlas) -> None:
    flagged = atlas.issue("Flagged read", body="flagged: source revised", priority=9)
    step = atlas.issue("Relief", kind="step")
    answer = atlas.next()
    assert (answer["issue"]["id"], answer["reason"]) == (step["id"], "step_without_belief")

    atlas.api.post(f"/api/v1/issues/{step['id']}/produced", json={"belief_id": NO_SUCH_ID})
    answer = atlas.next()
    assert (answer["issue"]["id"], answer["reason"]) == (flagged["id"], "flagged_or_disputed")
    # A Fact alone is not a Belief: it does not take the step out of the first rule.
    other = atlas.issue("Control", kind="step")
    atlas.api.post(f"/api/v1/issues/{other['id']}/produced", json={"fact_id": atlas.record_fact()})
    assert atlas.next()["issue"]["id"] == other["id"]


def test_next_skips_blocked_issues_and_questions_whose_work_is_in_their_children(
    atlas: Atlas,
) -> None:
    root = atlas.issue(QUESTION, kind="question", priority=9)
    gate = atlas.issue("Gate", narrows=root["id"], priority=0)
    atlas.issue("Blocked step", kind="step", narrows=root["id"], requires=[gate["id"]])
    assert atlas.next()["issue"]["id"] == gate["id"]
    atlas.api.post(f"/api/v1/issues/{gate['id']}/complete")
    assert atlas.next()["issue"]["title"] == "Blocked step"


def test_a_sessions_close_creates_its_question_steps_open_questions_and_unread_companies(
    atlas: Atlas,
) -> None:
    company = atlas.company_id()
    opened = atlas.api.post(
        "/api/v1/sessions",
        json={
            "question": QUESTION,
            "theme": THEME,
            "seed_company_ids": [company],
            "as_of": "2026-09-30T00:00:00Z",
        },
    ).json()
    card = {
        "steps": [
            {"step": "constraint", "title": "The constraint", "status": "supported"},
            {"step": "relief", "status": "disputed"},
            {"step": "control", "status": "unknown"},
        ],
        "open_questions": ["Who else makes InP lasers?"],
        "not_read": [
            {"company_id": company, "company_name": "Lumentum"},
            {"company_name": "Nobody"},
        ],
    }
    closed = atlas.api.post(f"/api/v1/sessions/{opened['id']}/close", json={"card": card})
    assert closed.status_code == 200, closed.text

    items = atlas.get("/api/v1/issues", theme=THEME)["items"]
    by_title = {i["title"]: i for i in items}
    root = by_title[QUESTION]
    assert (root["kind"], root["status"], root["produced_by"]) == (
        "question",
        "active",
        opened["id"],
    )
    assert root["company_ids"] == [company]
    steps = [i for i in items if i["kind"] == "step"]
    assert sorted((i["title"], i["status"]) for i in steps) == [
        ("The constraint: " + QUESTION, "complete"),
        ("control: " + QUESTION, "active"),
        ("relief: " + QUESTION, "active"),
    ]
    assert {i["parent_id"] for i in steps} == {root["id"]}
    question = by_title["Who else makes InP lasers?"]
    assert (question["kind"], question["parent_id"]) == ("question", root["id"])
    read = by_title["Read Lumentum"]
    assert (read["kind"], read["company_ids"], read["parent_title"]) == (
        "read",
        [company],
        QUESTION,
    )
    assert by_title["Read Nobody"]["company_ids"] == []
    assert len(items) == 1 + 3 + 1 + 2

    # The frontier: the disputed step (priority 2) before the unknown one (1); both lack a Belief.
    answer = atlas.next()
    assert (answer["issue"]["title"], answer["reason"]) == (
        "relief: " + QUESTION,
        "step_without_belief",
    )
    assert "issue.created" in atlas.actions(root["id"])
