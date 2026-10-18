"""Beliefs (beliefs ticket 02): propose, cite, judge, supersede, flag, read.

Seam: the `/api/v1` API on a fresh database holding Lumentum's recorded EDGAR filings (an
editable copy of the fixtures, so a test can revise a document and ingest it again), quoting
the recorded Q4 FY26 press release. Facts are recorded through `POST /facts`; flags are raised
by the triggers that already see Assertion reviews and new Source Versions.
"""

import json
import shutil
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
ACTOR = "belief-test-owner"
QUARTER = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
YEAR = "Net revenue for fiscal year 2026 was $3.01 billion"
INCOME = "Non-GAAP net income for fiscal year 2026 was $782.3 million"
STATEMENTS = {
    QUARTER: ("Lumentum's fourth-quarter fiscal 2026 net revenue was $1.01 billion.", 1.01),
    YEAR: ("Lumentum's fiscal 2026 net revenue was $3.01 billion.", 3.01),
    INCOME: ("Lumentum's fiscal 2026 non-GAAP net income was $782.3 million.", 782.3),
}
BELIEF = "Lumentum's revenue is growing fast enough to strain its laser capacity."
NO_SUCH_ID = "00000000-0000-0000-0000-000000000000"


class Atlas:
    def __init__(self, database_url: str, tmp_path: Path) -> None:
        archive = tmp_path / "archive"
        archive.mkdir(exist_ok=True)
        self.fixtures = tmp_path / "edgar"
        shutil.copytree(EDGAR_FIXTURES, self.fixtures)
        self.engine = create_engine(database_url)
        self.settings = make_settings(
            archive,
            database_url=database_url,
            actor=ACTOR,
            themes_config=THEMES,
            sec_fixtures_dir=self.fixtures,
        )
        self.api = TestClient(create_app(self.settings))
        self.ingest("first")

    def ingest(self, key: str) -> None:
        queue = JobQueue(self.engine, actor=Actor(ACTOR))
        queue.enqueue(INGEST_KIND, key, ingest_payload("lumentum", ["8-K"], None))
        worker = Worker(queue, builtin_registry(self.settings))
        assert worker.run_once() >= 1
        worker.run_once()  # a revision enqueues the contradiction check, which flags Beliefs

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def post(self, path: str, body: dict[str, Any], status: int = 200) -> Any:
        response = self.api.post(path, json=body)
        assert response.status_code == status, response.text
        return response.json()

    def company_id(self) -> str:
        return next(
            c["id"] for c in self.get("/api/v1/companies")["items"] if c["slug"] == "lumentum"
        )

    def version_id(self) -> str:
        documents = self.get(f"/api/v1/companies/{self.company_id()}/sources", limit=100)["items"]
        return next(d["latest_version_id"] for d in documents if d["canonical_url"] == URL_EX991)

    def fact(self, quote: str = QUARTER) -> str:
        """Record a Fact quoting `quote` of the press release; its ID."""
        version = self.version_id()
        parsed = self.api.get(
            f"/api/v1/source-versions/{version}/content", params={"kind": "parsed"}
        ).text
        start = parsed.index(quote)
        statement, value = STATEMENTS[quote]
        recorded = self.post(
            "/api/v1/facts",
            {
                "subject_company_id": self.company_id(),
                "source_version_id": version,
                "quote": quote,
                "span_start": start,
                "span_end": start + len(quote),
                "epistemic_type": "company_claim",
                "step": "context",
                "statement": statement,
                "quantity": {"value": value, "unit": "USD", "metric": "figure"},
                "period": "FY2026",
                "status": "in_effect",
            },
            status=201,
        )
        return recorded["fact"]["id"]

    def session(self) -> str:
        return self.post(
            "/api/v1/sessions",
            {
                "question": "Is laser capacity the constraint on AI optics?",
                "theme": "photonics",
                "as_of": "2026-09-30T00:00:00Z",
                "actor": "claude-session",
            },
            status=201,
        )["id"]

    def propose(self, fact: str, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "statement": BELIEF,
            "theme": "photonics",
            "step": "constraint",
            "company_ids": [self.company_id()],
            "as_of": "2026-09-30T00:00:00Z",
            "actor": "claude-session",
            "citations": [
                {"ref_id": fact, "valence": 0.9, "weight": "load_bearing", "note": "the figure"}
            ],
        } | overrides
        return self.post("/api/v1/beliefs", body, status=201)

    def judge(self, belief: str, **overrides: Any) -> dict[str, Any]:
        body = {
            "actor": "owner",
            "judgement": "proven",
            "confidence": 0.8,
            "reason": "two filings agree",
        } | overrides
        return self.post(f"/api/v1/beliefs/{belief}/judge", body)

    def actions(self, entity_id: str) -> list[str]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    text("SELECT action FROM audit_event WHERE entity_id = :id ORDER BY id"),
                    {"id": entity_id},
                ).scalars()
            )

    def revise(self, old: str, new: str) -> None:
        """Serve revised bytes for the press release, with a new Last-Modified, and ingest."""
        path = self.fixtures / "lumentum" / "manifest.json"
        manifest = json.loads(path.read_text())
        entry = next(e for e in manifest["responses"] if e["url"] == URL_EX991)
        entry["headers"]["last-modified"] = "Tue, 18 Aug 2026 20:24:36 GMT"
        path.write_text(json.dumps(manifest, indent=2))
        body = self.fixtures / "lumentum" / entry["file"]
        original = body.read_bytes()
        assert original.count(old.encode()) == 1
        body.write_bytes(original.replace(old.encode(), new.encode()))
        self.ingest("second")


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path)
    yield harness
    harness.engine.dispose()


def test_a_belief_is_proposed_unproven_with_its_citations_and_audited(atlas: Atlas) -> None:
    fact = atlas.fact()
    session = atlas.session()

    belief = atlas.propose(fact, session_id=session)

    assert belief["statement"] == BELIEF
    assert belief["step"] == "constraint"
    assert belief["status"] == "active"
    assert [c["display_name"] for c in belief["companies"]] == ["Lumentum"]
    assert belief["judgement"]["judgement"] == "unproven"
    assert belief["judgement"]["actor"] == "claude-session"
    assert belief["open_flags"] == 0
    [citation] = belief["citations"]
    assert citation["ref_id"] == fact
    assert citation["quote"] == QUARTER
    assert citation["valence"] == 0.9
    assert citation["weight"] == "load_bearing"
    assert citation["statement"].startswith("Lumentum's fourth-quarter")
    assert citation["available_at"] <= "2026-09-30"
    assert citation["stands"] is True
    assert belief["session"]["id"] == session
    assert atlas.get(f"/api/v1/beliefs/{belief['id']}")["id"] == belief["id"]
    assert atlas.actions(belief["id"]) == ["belief.proposed"]


def test_a_belief_shows_the_newest_document_its_load_bearing_citations_rest_on(
    atlas: Atlas,
) -> None:
    fact = atlas.fact()
    belief = atlas.propose(fact)
    [citation] = belief["citations"]

    # The date is the cited document's `available_at`, read apart from the Belief.
    assert belief["newest_evidence_at"] == citation["available_at"]
    assert (
        atlas.get(f"/api/v1/beliefs/{belief['id']}")["newest_evidence_at"]
        == (citation["available_at"])
    )
    [listed] = atlas.get("/api/v1/beliefs", theme="photonics")["items"]
    assert listed["newest_evidence_at"] == citation["available_at"]


def test_a_belief_without_a_load_bearing_positive_citation_is_refused(atlas: Atlas) -> None:
    fact = atlas.fact()
    body = {
        "statement": BELIEF,
        "theme": "photonics",
        "step": "constraint",
        "company_ids": [atlas.company_id()],
        "as_of": "2026-09-30T00:00:00Z",
    }
    cases = {
        "none": [],
        "context only": [{"ref_id": fact, "valence": 0.9, "weight": "context"}],
        "load-bearing against": [{"ref_id": fact, "valence": -0.5, "weight": "load_bearing"}],
    }

    for citations in cases.values():
        refused = atlas.api.post("/api/v1/beliefs", json=body | {"citations": citations})
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == "no_load_bearing_citation"

    assert atlas.get("/api/v1/beliefs")["total"] == 0


def test_unknown_references_and_inputs_are_refused(atlas: Atlas) -> None:
    fact = atlas.fact()
    good = {"ref_id": fact, "valence": 0.9, "weight": "load_bearing"}
    base: dict[str, Any] = {
        "statement": BELIEF,
        "theme": "photonics",
        "step": "constraint",
        "as_of": "2026-09-30T00:00:00Z",
        "citations": [good],
    }

    unknown_fact = atlas.api.post(
        "/api/v1/beliefs", json=base | {"citations": [good | {"ref_id": NO_SUCH_ID}]}
    )
    unknown_company = atlas.api.post("/api/v1/beliefs", json=base | {"company_ids": [NO_SUCH_ID]})
    unknown_session = atlas.api.post("/api/v1/beliefs", json=base | {"session_id": NO_SUCH_ID})
    no_sign = atlas.api.post("/api/v1/beliefs", json=base | {"citations": [{"ref_id": fact}]})
    bad_step = atlas.api.post("/api/v1/beliefs", json=base | {"step": "vibes"})

    assert unknown_fact.json()["error"]["code"] == "unknown_citation"
    assert unknown_company.json()["error"]["code"] == "unknown_company"
    assert unknown_session.json()["error"]["code"] == "unknown_session"
    assert no_sign.json()["error"]["code"] == "invalid_request"
    assert bad_step.json()["error"]["code"] == "invalid_request"
    assert atlas.api.get(f"/api/v1/beliefs/{NO_SUCH_ID}").status_code == 404
    assert atlas.get("/api/v1/beliefs")["total"] == 0


def test_a_citation_is_added_with_a_valence_or_a_counter_judge_relation(atlas: Atlas) -> None:
    belief = atlas.propose(atlas.fact())
    year, income = atlas.fact(YEAR), atlas.fact(INCOME)

    by_valence = atlas.post(
        f"/api/v1/beliefs/{belief['id']}/cite", {"ref_id": year, "valence": 0.4, "note": "also"}
    )
    by_relation = atlas.post(
        f"/api/v1/beliefs/{belief['id']}/cite", {"ref_id": income, "relation": "limits"}
    )
    again = atlas.api.post(
        f"/api/v1/beliefs/{belief['id']}/cite", json={"ref_id": year, "valence": 0.4}
    )

    assert by_valence["citation_count"] == 2
    assert by_relation["citation_count"] == 3
    weights = {c["ref_id"]: (c["valence"], c["weight"]) for c in by_relation["citations"]}
    assert weights[year] == (0.4, "context")
    assert weights[income] == (-0.5, "context")
    assert [c["ref_id"] for c in by_relation["counterevidence"]] == [income]
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_cited"
    assert atlas.actions(belief["id"]) == ["belief.proposed", "belief.cited", "belief.cited"]


def test_a_judgement_records_who_set_it_and_the_history_keeps_every_one(atlas: Atlas) -> None:
    belief = atlas.propose(atlas.fact())

    proven = atlas.judge(belief["id"])
    disproven = atlas.judge(
        belief["id"], actor="claude-session", judgement="disproven", confidence=0.3, reason="x"
    )

    assert proven["judgement"]["judgement"] == "proven"
    assert proven["judgement"]["actor"] == "owner"
    assert proven["judgement"]["reason"] == "two filings agree"
    assert disproven["judgement"]["judgement"] == "disproven"
    assert [(h["judgement"], h["actor"]) for h in disproven["history"]] == [
        ("unproven", "claude-session"),
        ("proven", "owner"),
        ("disproven", "claude-session"),
    ]
    assert atlas.actions(belief["id"]) == ["belief.proposed", "belief.judged", "belief.judged"]
    refused = atlas.api.post(
        f"/api/v1/beliefs/{belief['id']}/judge",
        json={"judgement": "proven", "confidence": 0.5, "reason": "r"},
    )
    out_of_range = atlas.api.post(
        f"/api/v1/beliefs/{belief['id']}/judge",
        json={"actor": "owner", "judgement": "proven", "confidence": 1.5, "reason": "r"},
    )
    assert refused.status_code == 422 and out_of_range.status_code == 422
    assert (
        atlas.api.post(
            f"/api/v1/beliefs/{NO_SUCH_ID}/judge",
            json={"actor": "owner", "judgement": "proven", "confidence": 0.5, "reason": "r"},
        ).status_code
        == 404
    )


def test_a_past_judgement_is_read_as_of_its_time(atlas: Atlas) -> None:
    belief = atlas.propose(atlas.fact())
    first = atlas.judge(belief["id"], judgement="proven", confidence=0.6)
    second = atlas.judge(belief["id"], judgement="disproven", confidence=0.9, reason="refuted")
    proposed_at = belief["judgement"]["at"]
    first_at, second_at = first["judgement"]["at"], second["judgement"]["at"]
    assert proposed_at < first_at < second_at

    now = atlas.get("/api/v1/beliefs")["items"][0]["judgement"]
    then = atlas.get("/api/v1/beliefs", as_of=first_at)["items"][0]["judgement"]
    born = atlas.get("/api/v1/beliefs", as_of=proposed_at)["items"][0]["judgement"]
    detail = atlas.get(f"/api/v1/beliefs/{belief['id']}", as_of=first_at)
    before_it_existed = atlas.get("/api/v1/beliefs", as_of="2020-01-01T00:00:00Z")

    assert (now["judgement"], now["confidence"]) == ("disproven", 0.9)
    assert (then["judgement"], then["confidence"]) == ("proven", 0.6)
    assert born["judgement"] == "unproven"
    assert detail["judgement"]["judgement"] == "proven"
    assert len(detail["history"]) == 3
    assert before_it_existed["total"] == 0


def test_superseding_keeps_the_old_belief_whole_and_names_its_successors(atlas: Atlas) -> None:
    fact = atlas.fact()
    old = atlas.propose(fact)
    atlas.judge(old["id"])
    new = atlas.propose(fact, statement="Lumentum's capacity is the constraint, not demand.")
    other = atlas.propose(fact, statement="Coherent shares the constraint.")

    superseded = atlas.post(
        f"/api/v1/beliefs/{old['id']}/supersede",
        {"by": [new["id"], other["id"]], "reason": "split in two", "actor": "claude-session"},
    )

    assert superseded["status"] == "superseded"
    assert superseded["judgement"]["judgement"] == "proven"
    assert [c["ref_id"] for c in superseded["citations"]] == [fact]
    assert len(superseded["history"]) == 2
    assert {link["id"] for link in superseded["superseded_by"]} == {new["id"], other["id"]}
    assert superseded["superseded_by"][0]["reason"] == "split in two"
    successor = atlas.get(f"/api/v1/beliefs/{new['id']}")
    assert [link["id"] for link in successor["supersedes"]] == [old["id"]]
    assert atlas.get("/api/v1/beliefs", status="superseded")["total"] == 1
    assert atlas.get("/api/v1/beliefs", status="active")["total"] == 2
    assert atlas.actions(old["id"]) == ["belief.proposed", "belief.judged", "belief.superseded"]

    for path, body in {
        "cite": {"ref_id": atlas.fact(YEAR), "valence": 0.5},
        "judge": {"actor": "o", "judgement": "proven", "confidence": 0.5, "reason": "r"},
        "supersede": {"by": [new["id"]], "reason": "again"},
    }.items():
        refused = atlas.api.post(f"/api/v1/beliefs/{old['id']}/{path}", json=body)
        assert refused.status_code == 409, path
        assert refused.json()["error"]["code"] == "belief_not_active"


def test_a_supersession_names_real_active_other_beliefs(atlas: Atlas) -> None:
    fact = atlas.fact()
    belief = atlas.propose(fact)
    dead = atlas.propose(fact, statement="Another.")
    atlas.post(f"/api/v1/beliefs/{dead['id']}/supersede", {"by": [belief["id"]], "reason": "r"})

    for by in ([belief["id"]], [NO_SUCH_ID], [dead["id"]]):
        refused = atlas.api.post(
            f"/api/v1/beliefs/{belief['id']}/supersede", json={"by": by, "reason": "r"}
        )
        assert refused.status_code == 422, by
        assert refused.json()["error"]["code"] == "invalid_successor"
    assert atlas.get(f"/api/v1/beliefs/{belief['id']}")["status"] == "active"


def test_the_list_filters_by_theme_step_company_judgement_and_flags(atlas: Atlas) -> None:
    fact = atlas.fact()
    constraint = atlas.propose(fact)
    relief = atlas.propose(fact, step="relief", statement="Relief.", company_ids=[])
    robotics = atlas.propose(fact, theme="robotics", statement="Actuators.")
    atlas.judge(constraint["id"], judgement="proven")

    def ids(**params: Any) -> list[str]:
        return [each["id"] for each in atlas.get("/api/v1/beliefs", **params)["items"]]

    assert ids() == [constraint["id"], relief["id"], robotics["id"]]
    assert ids(theme="photonics") == [constraint["id"], relief["id"]]
    assert ids(step="relief") == [relief["id"]]
    assert ids(company_id=atlas.company_id()) == [constraint["id"], robotics["id"]]
    assert ids(judgement="proven") == [constraint["id"]]
    assert ids(judgement="unproven") == [relief["id"], robotics["id"]]
    assert ids(flagged="true") == []
    assert ids(flagged="false") == [constraint["id"], relief["id"], robotics["id"]]
    assert atlas.get("/api/v1/beliefs", limit=1, offset=1)["items"][0]["id"] == relief["id"]


def test_a_load_bearing_citation_at_or_below_minus_three_quarters_flags_counterevidence(
    atlas: Atlas,
) -> None:
    belief = atlas.propose(atlas.fact())
    limits, denies = atlas.fact(YEAR), atlas.fact(INCOME)

    # -0.5 load-bearing, and -1 as context only, flag nothing.
    atlas.post(
        f"/api/v1/beliefs/{belief['id']}/cite",
        {"ref_id": limits, "valence": -0.5, "weight": "load_bearing"},
    )
    assert atlas.get(f"/api/v1/beliefs/{belief['id']}")["open_flags"] == 0
    # The counter-judge's "contradicts" is -1: load-bearing, it flags.
    flagged = atlas.post(
        f"/api/v1/beliefs/{belief['id']}/cite",
        {"ref_id": denies, "relation": "contradicts", "weight": "load_bearing"},
    )

    assert flagged["open_flags"] == 1
    [flag] = flagged["flags"]
    assert flag["kind"] == "counterevidence_stands"
    assert flag["ref_id"] == denies
    assert flag["cleared_by"] is None
    assert atlas.get("/api/v1/beliefs", flagged="true")["total"] == 1
    assert "belief.flagged" in atlas.actions(belief["id"])

    # An author's judgement clears the flag and records which judgement did.
    judged = atlas.judge(belief["id"], judgement="undecidable", reason="seen, unresolved")
    assert judged["open_flags"] == 0
    assert judged["flags"][0]["cleared_by"] == judged["judgement"]["id"]


def test_a_context_citation_at_minus_one_does_not_flag(atlas: Atlas) -> None:
    belief = atlas.propose(atlas.fact())

    cited = atlas.post(
        f"/api/v1/beliefs/{belief['id']}/cite",
        {"ref_id": atlas.fact(YEAR), "valence": -1, "weight": "context"},
    )

    assert cited["open_flags"] == 0
    assert cited["counterevidence"][0]["valence"] == -1


def test_reviewing_a_cited_assertion_flags_its_beliefs(atlas: Atlas) -> None:
    fact, other = atlas.fact(), atlas.fact(YEAR)
    belief = atlas.propose(fact)
    successor = atlas.propose(other, statement="Unrelated.")
    quiet = atlas.propose(other, statement="Cites the other only.")
    atlas.post(f"/api/v1/beliefs/{belief['id']}/cite", {"ref_id": other, "valence": 0.5})

    disputed = atlas.post(f"/api/v1/assertions/{fact}/review", {"review_state": "disputed"})
    assert disputed["assertion"]["review_state"] == "disputed"
    superseded = atlas.post(
        f"/api/v1/assertions/{other}/review",
        {"review_state": "superseded", "superseded_by": fact},
    )
    assert superseded["assertion"]["review_state"] == "superseded"

    read = atlas.get(f"/api/v1/beliefs/{belief['id']}")
    assert {(f["kind"], f["ref_id"]) for f in read["flags"]} == {
        ("assertion_reviewed", fact),
        ("fact_superseded", other),
    }
    assert all(not c["stands"] for c in read["citations"])
    assert atlas.get(f"/api/v1/beliefs/{successor['id']}")["open_flags"] == 1
    assert atlas.get(f"/api/v1/beliefs/{quiet['id']}")["open_flags"] == 1
    assert atlas.get("/api/v1/beliefs", flagged="true")["total"] == 3


def test_a_review_that_does_not_contradict_flags_nothing(atlas: Atlas) -> None:
    fact = atlas.fact()
    belief = atlas.propose(fact)

    atlas.post(f"/api/v1/assertions/{fact}/review", {"review_state": "corroborated"})

    assert atlas.get(f"/api/v1/beliefs/{belief['id']}")["open_flags"] == 0


def test_a_revised_source_that_lost_the_quote_flags_the_belief_and_one_that_kept_it_does_not(
    atlas: Atlas,
) -> None:
    quarter, income = atlas.fact(), atlas.fact(INCOME)
    belief = atlas.propose(quarter)
    kept = atlas.propose(income, statement="Income held.")

    atlas.revise("$1.01 billion, with GAAP net loss", "$1.02 billion, with GAAP net loss")

    read = atlas.get(f"/api/v1/beliefs/{belief['id']}")
    assert [(f["kind"], f["ref_id"]) for f in read["flags"]] == [("source_revised", quarter)]
    assert read["judgement"]["judgement"] == "unproven"  # flagged, never silently changed
    assert [c["quote"] for c in read["citations"]] == [QUARTER]
    assert atlas.get(f"/api/v1/beliefs/{kept['id']}")["open_flags"] == 0
    assert "belief.flagged" in atlas.actions(belief["id"])
