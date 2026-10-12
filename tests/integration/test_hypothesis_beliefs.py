"""A Hypothesis over Beliefs (atlas-beliefs ticket 14): drafted from a theme's proven Beliefs,
its steps each with the Beliefs they rest on, behind the publish gate's Belief rule, frozen in
the Research Snapshot with each Belief's judgement at publication.

Seam: the `/api/v1` API and single worker passes on a fresh database holding Lumentum's recorded
EDGAR press release. Facts are recorded through `POST /facts`, Beliefs through `POST /beliefs`;
LiteLLM is the scripted chat fake (**every role's answer is written here**: the Editor cites the
Beliefs it is sent by their short references, the finding judge answers supported or misstated),
Hindsight the recorded fake. Nothing live is called; the CLI is not used (the bank template is
applied in process).
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy import text

from atlas.audit import Actor
from atlas.cli import run_apply_template
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.harness import BANK, EDGAR_FIXTURES, TEMPLATE, THEMES, Atlas, make_settings

URL_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
QUARTER = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
YEAR = "Net revenue for fiscal year 2026 was $3.01 billion"
INCOME = "Non-GAAP net income for fiscal year 2026 was $782.3 million"
FACTS = {
    QUARTER: ("Lumentum's fourth-quarter fiscal 2026 net revenue was $1.01 billion.", 1.01),
    YEAR: ("Lumentum's fiscal 2026 net revenue was $3.01 billion.", 3.01),
    INCOME: ("Lumentum's fiscal 2026 non-GAAP net income was $782.3 million.", 782.3),
}
CONSTRAINT = "Lumentum's revenue is growing fast enough to strain its laser capacity."
CAPTURE = "Lumentum captures a growing share of the value in its laser supply chain."
UNPROVEN = "Lumentum earns an excess return on its capacity."
CONSTRAINT_STATEMENT = (
    "Lumentum reported net revenue of $1.01 billion for the fourth quarter of fiscal year 2026."
)
CAPTURE_STATEMENT = "Lumentum reported net revenue of $3.01 billion for fiscal year 2026."
REWRITTEN = "Lumentum reported net revenue of $3.01 billion in fiscal year 2026, up sharply."
THESIS = "Laser capacity may bind AI optics, and Lumentum may capture the value of that."
ACTOR = "claude-session"


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


@pytest.fixture
def llm() -> FakeLiteLLM:
    return FakeLiteLLM()


@pytest.fixture
def litellm(llm: FakeLiteLLM) -> Iterator[Served]:
    with serve(llm.handle) as served:
        yield served
        served.raise_errors()


class Beliefs:
    """Atlas with Lumentum's press release ingested, Facts and Beliefs recorded through the
    API, and a Hypothesis drafted from them."""

    def __init__(
        self, database_url: str, tmp_path: Path, hindsight_url: str, litellm_url: str
    ) -> None:
        self.atlas = Atlas(
            database_url,
            tmp_path,
            hindsight_url,
            litellm_url,
            finding_judge=True,
            hindsight_template_path=TEMPLATE,
        )
        self.engine = self.atlas.engine
        self.api: TestClient = self.atlas.api
        assert run_apply_template(self.atlas.settings(), None) == 0
        # The ingest runs without Hindsight, so it enqueues no retains to run before the draft.
        plain = make_settings(
            self.atlas.archive,
            database_url=database_url,
            actor=ACTOR,
            themes_config=THEMES,
            sec_fixtures_dir=EDGAR_FIXTURES,
        )
        queue = JobQueue(self.engine, actor=Actor(ACTOR))
        queue.enqueue(INGEST_KIND, "lumentum", ingest_payload("lumentum", ["8-K"], None))
        worker = Worker(queue, builtin_registry(plain))
        assert worker.run_once() >= 1

    def get(self, path: str, **params: Any) -> Any:
        return self.atlas.get(path, **params)

    def post(self, path: str, body: dict[str, Any], status: int = 200) -> Any:
        response = self.api.post(path, json=body)
        assert response.status_code == status, response.text
        return response.json()

    def company_id(self) -> str:
        return self.atlas.company("lumentum")["id"]

    def fact(self, quote: str) -> str:
        version = self.atlas.version(URL_EX991)["id"]
        parsed = self.api.get(
            f"/api/v1/source-versions/{version}/content", params={"kind": "parsed"}
        ).text
        start = parsed.index(quote)
        statement, value = FACTS[quote]
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

    def belief(
        self, statement: str, step: str, quote: str, *, judged: str | None = "proven"
    ) -> dict[str, Any]:
        belief = self.post(
            "/api/v1/beliefs",
            {
                "statement": statement,
                "theme": "photonics",
                "step": step,
                "company_ids": [self.company_id()],
                "as_of": "2026-09-30T00:00:00Z",
                "actor": ACTOR,
                "citations": [
                    {
                        "ref_id": self.fact(quote),
                        "valence": 0.9,
                        "weight": "load_bearing",
                        "note": "the figure",
                    }
                ],
            },
            status=201,
        )
        if judged is not None:
            self.judge(belief["id"], judged)
        return belief

    def judge(self, belief_id: str, judgement: str, confidence: float = 0.8) -> None:
        self.post(
            f"/api/v1/beliefs/{belief_id}/judge",
            {
                "actor": "owner",
                "judgement": judgement,
                "confidence": confidence,
                "reason": "the figures agree",
            },
        )

    def create(self, **body: Any) -> dict[str, Any]:
        return self.post("/api/v1/hypotheses", {"theme": "photonics"} | body, status=202)

    def worker_pass(self) -> int:
        return self.atlas.worker_pass()

    def hypothesis(self, hypothesis_id: str) -> dict[str, Any]:
        return self.get(f"/api/v1/hypotheses/{hypothesis_id}")


@pytest.fixture
def beliefs(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
) -> Iterator[Beliefs]:
    assert BANK
    started = Beliefs(database_url, tmp_path, hindsight[1].url, litellm.url)
    yield started
    started.engine.dispose()


def asked(body: dict[str, Any]) -> dict[str, Any]:
    """The user message of a chat request: `{"request": ..., "retrieved_data": [...]}`."""
    return json.loads(body["messages"][1]["content"])


def editor(statements: dict[str, str]) -> Callable[[dict[str, Any]], JsonValue]:
    """The Hypothesis Editor: it cites, per step, the Belief it is sent for that step by its
    short reference, with the statement written for that step in `statements`."""

    def respond(body: dict[str, Any]) -> JsonValue:
        request = asked(body)["request"]
        by_step = {each["step"]: each["ref"] for each in request["beliefs"]}
        first = next(iter(by_step.values()))
        answer: dict[str, JsonValue] = {
            "thesis_statement": THESIS,
            "thesis_belief_refs": [first],
            "mechanism": {
                "demand_driver": "AI optics deployments",
                "possible_constraint": "laser capacity",
                "economic_capture_question": None,
            },
            "measurable_predictions": ["Lead times stay long"],
            "catalysts": ["New supply agreements"],
            "falsifiers": ["Qualified second-source capacity comes online"],
            "required_evidence": ["Capacity figures from an original document"],
            "alternative_explanations": ["Inventory build"],
            "unresolved_questions": ["Does revenue growth reflect scarcity or volume?"],
            "steps": [
                {"step": step, "statement": statement, "belief_refs": [by_step[step]]}
                for step, statement in statements.items()
                if step in by_step
            ],
        }
        return answer

    return respond


def supporting(body: dict[str, Any]) -> JsonValue:
    """The finding judge (`finding_judge.v4`): supported, the statement one clause whose basis
    is the first cited quote, whole."""
    request = asked(body)
    statement = request["request"]["finding"]["statement"]
    quote = request["retrieved_data"][0]
    return {
        "clauses": [{"text": statement, "ref": quote["id"], "basis": quote["text"]}],
        "verdict": "supported",
        "beyond": [],
        "kinds": [],
        "reason": "the quotes state it",
    }


def misstating(body: dict[str, Any]) -> JsonValue:
    return {
        "clauses": [{"text": "the figure", "ref": None, "basis": None}],
        "verdict": "misstated",
        "beyond": ["the figure"],
        "kinds": ["figure_or_date"],
        "reason": "the quote states another period",
    }


def rewriting(statement: str) -> Callable[[dict[str, Any]], JsonValue]:
    def respond(body: dict[str, Any]) -> JsonValue:
        findings = asked(body)["request"]["findings"]
        return {
            "findings": [
                {"finding": each["finding"], "statement": statement, "limitations": []}
                for each in findings
            ]
        }

    return respond


def roles(llm: FakeLiteLLM) -> list[str]:
    return [body["metadata"]["role"] for body in llm.chat_requests()]


def ready(
    beliefs: Beliefs,
    llm: FakeLiteLLM,
    *,
    draft: Callable[[dict[str, Any]], JsonValue] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Two proven Beliefs (constraint, capture) and one unproven, and the Hypothesis drafted
    from them with both statements supported."""
    constraint = beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    capture = beliefs.belief(CAPTURE, "capture", YEAR)
    beliefs.belief(UNPROVEN, "control", INCOME, judged=None)
    llm.script_role(
        "editor",
        ChatReply.answer(
            draft or editor({"constraint": CONSTRAINT_STATEMENT, "capture": CAPTURE_STATEMENT}),
            tokens=(3000, 700),
        ),
    )
    llm.script_role("finding_judge", *(ChatReply.answer(supporting, tokens=(400, 40)),) * 2)
    saved = beliefs.create()
    beliefs.worker_pass()
    return beliefs.hypothesis(saved["id"]), constraint, capture


# --- the draft ------------------------------------------------------------------------------------


def test_a_hypothesis_is_drafted_from_proven_beliefs_with_steps_grounded_and_judged(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    hypothesis, constraint, capture = ready(beliefs, llm)

    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    assert (hypothesis["investigation_id"], hypothesis["status"]) == (None, "draft")
    assert hypothesis["as_of"].startswith("2026-09-30")
    [version] = hypothesis["versions"]
    content = version["content"]
    # The unproven Belief was not sent: two Beliefs, by short reference, in argument order.
    [request] = [
        asked(body)["request"]
        for body in llm.chat_requests()
        if body["metadata"]["role"] == "editor"
    ]
    assert [(each["ref"], each["step"], each["judgement"]) for each in request["beliefs"]] == [
        ("b1", "constraint", "proven"),
        ("b2", "capture", "proven"),
    ]
    assert content["findings"] == []
    assert [str(each) for each in content["thesis_belief_ids"]] == [constraint["id"]]
    # The steps: each with the Belief it rests on, its judgement and the Fact's words at the span.
    assert [step["step"] for step in content["steps"]] == ["constraint", "capture"]
    first, second = content["steps"]
    assert (first["statement"], first["statement_belief_ids"], first["judged"]) == (
        CONSTRAINT_STATEMENT,
        [constraint["id"]],
        True,
    )
    assert (second["statement"], second["statement_belief_ids"]) == (
        CAPTURE_STATEMENT,
        [capture["id"]],
    )
    [rests_on] = first["beliefs"]
    assert (rests_on["belief_id"], rests_on["statement"], rests_on["judgement"]) == (
        constraint["id"],
        CONSTRAINT,
        "proven",
    )
    assert rests_on["confidence"] == 0.8
    [citation] = rests_on["citations"]
    assert citation["quote"] == QUARTER
    assert citation["span_end"] - citation["span_start"] == len(QUARTER)
    assert content["unsupported_findings"] == []
    # One judge call per statement; the draft's provenance names the Beliefs it was sent.
    assert roles(llm) == ["editor", "finding_judge", "finding_judge"]
    provenance = version["provenance"]
    assert provenance["investigation_id"] is None
    assert provenance["belief_ids"] == [constraint["id"], capture["id"]]
    # The read returns the same steps.
    assert (
        beliefs.hypothesis(hypothesis["id"])["versions"][0]["content"]["steps"]
        == (content["steps"])
    )


def test_a_statement_citing_no_belief_it_was_sent_or_misstating_its_quotes_is_set_aside(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    def citing_badly(body: dict[str, Any]) -> JsonValue:
        answer = editor({"constraint": CONSTRAINT_STATEMENT, "capture": CAPTURE_STATEMENT})(body)
        assert isinstance(answer, dict)
        answer["steps"] = [  # type: ignore[index]
            *answer["steps"],  # type: ignore[misc]
            {"step": "relief", "statement": "Capacity relief arrives.", "belief_refs": ["b9"]},
            {"step": "control", "statement": "Lumentum controls it.", "belief_refs": []},
        ]
        return answer

    beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    beliefs.belief(CAPTURE, "capture", YEAR)
    llm.script_role(
        "editor",
        ChatReply.answer(citing_badly, tokens=(3000, 700)),
        # The rewrite of the misstated capture statement, grounded but judged misstated again.
        ChatReply.answer(rewriting(REWRITTEN), tokens=(800, 80)),
    )
    # constraint: supported; capture: misstated, rewritten, misstated again.
    llm.script_role(
        "finding_judge",
        ChatReply.answer(supporting, tokens=(400, 40)),
        ChatReply.answer(misstating, tokens=(400, 40)),
        ChatReply.answer(misstating, tokens=(400, 40)),
    )
    saved = beliefs.create()
    beliefs.worker_pass()

    hypothesis = beliefs.hypothesis(saved["id"])
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    content = hypothesis["versions"][0]["content"]
    by_step = {step["step"]: step for step in content["steps"]}
    # Both Beliefs stay on their steps; only the constraint step keeps a statement.
    assert by_step["constraint"]["statement"] == CONSTRAINT_STATEMENT
    assert by_step["capture"]["statement"] is None
    assert len(by_step["capture"]["beliefs"]) == 1
    reasons = {each["statement"]: each["reason"] for each in content["unsupported_findings"]}
    assert reasons["Capacity relief arrives."].startswith("cites what isn't a Belief it was sent")
    assert reasons["Lumentum controls it."] == "cites no Belief"
    assert reasons[REWRITTEN] == "misstated after a rewrite: the quote states another period"
    assert roles(llm) == ["editor", "finding_judge", "finding_judge", "editor", "finding_judge"]


def test_a_theme_with_no_proven_belief_is_not_drafted_and_one_basis_is_required(
    beliefs: Beliefs,
) -> None:
    beliefs.belief(UNPROVEN, "control", INCOME, judged=None)

    nothing = beliefs.api.post("/api/v1/hypotheses", json={"theme": "photonics"})
    assert nothing.status_code == 409, nothing.text
    assert "proven Belief" in nothing.json()["error"]["message"]
    both = beliefs.api.post(
        "/api/v1/hypotheses",
        json={"theme": "photonics", "investigation_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert both.status_code == 422
    assert beliefs.api.post("/api/v1/hypotheses", json={}).status_code == 422


def test_a_draft_can_be_limited_to_the_beliefs_of_named_sessions(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    session = beliefs.post(
        "/api/v1/sessions",
        {
            "question": "Is laser capacity the constraint on AI optics?",
            "theme": "photonics",
            "as_of": "2026-09-30T00:00:00Z",
            "actor": ACTOR,
        },
        status=201,
    )["id"]
    beliefs.belief(CONSTRAINT, "constraint", QUARTER)  # produced by no session
    ours = beliefs.post(
        "/api/v1/beliefs",
        {
            "statement": CAPTURE,
            "theme": "photonics",
            "step": "capture",
            "company_ids": [beliefs.company_id()],
            "as_of": "2026-09-30T00:00:00Z",
            "session_id": session,
            "actor": ACTOR,
            "citations": [{"ref_id": beliefs.fact(YEAR), "valence": 0.9, "weight": "load_bearing"}],
        },
        status=201,
    )
    beliefs.judge(ours["id"], "proven")
    llm.script_role(
        "editor", ChatReply.answer(editor({"capture": CAPTURE_STATEMENT}), tokens=(3000, 700))
    )
    llm.script_role("finding_judge", ChatReply.answer(supporting, tokens=(400, 40)))

    saved = beliefs.create(session_ids=[session])
    beliefs.worker_pass()

    hypothesis = beliefs.hypothesis(saved["id"])
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    assert hypothesis["session_ids"] == [session]
    assert hypothesis["question"] == "Is laser capacity the constraint on AI optics?"
    [step] = hypothesis["versions"][0]["content"]["steps"]
    assert [each["belief_id"] for each in step["beliefs"]] == [ours["id"]]


# --- the gate and the snapshot ------------------------------------------------------------------


def publish(beliefs: Beliefs, hypothesis_id: str, **body: Any) -> Any:
    return beliefs.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/publish-version", json={"version": 1, **body}
    )


def test_the_gate_holds_a_step_belief_no_longer_proven_and_the_owner_may_override(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    hypothesis, constraint, capture = ready(beliefs, llm)
    hypothesis_id = hypothesis["id"]
    moved = beliefs.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/transitions", json={"to": "evidence_ready"}
    )
    assert moved.status_code == 200, moved.text
    # Proven when drafted and still proven: the gate has nothing to say about it.
    read = beliefs.get(f"/api/v1/hypotheses/{hypothesis_id}/publish-gate")
    assert read["failures"] == [], read

    beliefs.judge(constraint["id"], "unproven", 0.4)

    read = beliefs.get(f"/api/v1/hypotheses/{hypothesis_id}/publish-gate")
    assert [(each["code"], each["belief_ids"]) for each in read["failures"]] == [
        ("belief_not_proven", [constraint["id"]])
    ]
    refused = publish(beliefs, hypothesis_id)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "publish_gate_failed"
    assert beliefs.get("/api/v1/snapshots", hypothesis_id=hypothesis_id)["items"] == []

    reason = "the owner reads the figure as enough"
    overridden = publish(beliefs, hypothesis_id, override_beliefs=True, override_reason=reason)

    assert overridden.status_code == 200, overridden.text
    with beliefs.engine.connect() as connection:
        [(recorded, belief_ids)] = connection.execute(
            text("SELECT reason, belief_ids FROM hypothesis_belief_override")
        ).all()
        rows = connection.execute(
            text(
                "SELECT belief_id::text, load_bearing, judgement"
                " FROM hypothesis_version_belief ORDER BY judgement"
            )
        ).all()
    assert (recorded, [str(each) for each in belief_ids]) == (reason, [constraint["id"]])
    assert [tuple(row) for row in rows] == [
        (capture["id"], True, "proven"),
        (constraint["id"], True, "unproven"),
    ]


def test_the_snapshot_carries_the_steps_with_each_belief_as_judged_at_publication(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    hypothesis, constraint, capture = ready(beliefs, llm)
    hypothesis_id = hypothesis["id"]
    beliefs.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/transitions", json={"to": "evidence_ready"}
    )
    # Re-judged proven with another confidence after the draft: the content keeps 0.8.
    beliefs.judge(constraint["id"], "proven", 0.95)

    published = publish(beliefs, hypothesis_id)

    assert published.status_code == 200, published.text
    [record] = beliefs.get("/api/v1/snapshots", hypothesis_id=hypothesis_id)["items"]
    snapshot = beliefs.get(f"/api/v1/snapshots/{record['id']}")
    assert snapshot["verified"] is True
    content = snapshot["content"]
    assert content["hypothesis"]["investigation_id"] is None
    assert content["cutoff"]["as_of"].startswith("2026-09-30")
    assert content["cutoff"]["question"] == hypothesis["question"]
    assert [step["step"] for step in content["steps"]] == ["constraint", "capture"]
    [frozen] = content["steps"][0]["beliefs"]
    assert (frozen["belief_id"], frozen["judgement"], frozen["confidence"]) == (
        constraint["id"],
        "proven",
        0.95,
    )
    assert (frozen["drafted_judgement"], frozen["drafted_confidence"]) == ("proven", 0.8)
    assert frozen["judged_by"] == "owner"
    [citation] = frozen["citations"]
    assert citation["quote"] == QUARTER
    assert citation["span_end"] - citation["span_start"] == len(QUARTER)
    # The Fact's Assertion and its Source Version are in the snapshot, so the quote can be read
    # at its span.
    assert citation["ref_id"] in {each["id"] for each in content["assertions"]}
    assert citation["source_version_id"] in {each["id"] for each in content["source_versions"]}
    assert content["outputs"]["content"]["steps"][0]["beliefs"][0]["confidence"] == 0.8
    assert content["outputs"]["content"]["thesis_belief_ids"] == [constraint["id"]]
    [second] = content["steps"][1]["beliefs"]
    assert second["belief_id"] == capture["id"]
    # Published: the version is frozen, and the dossier exports without an investigation.
    exported = beliefs.get(f"/api/v1/hypotheses/{hypothesis_id}/export", format="json")
    assert exported["run_metadata"]["investigation"] is None
    markdown = beliefs.api.get(
        f"/api/v1/hypotheses/{hypothesis_id}/export", params={"format": "markdown"}
    )
    assert markdown.status_code == 200
    assert QUARTER in markdown.text and "## Steps" in markdown.text


def test_a_superseded_step_belief_holds_the_gate(beliefs: Beliefs, llm: FakeLiteLLM) -> None:
    hypothesis, constraint, capture = ready(beliefs, llm)
    hypothesis_id = hypothesis["id"]
    beliefs.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/transitions", json={"to": "evidence_ready"}
    )
    beliefs.post(
        f"/api/v1/beliefs/{capture['id']}/supersede",
        {"by": [constraint["id"]], "reason": "restated", "actor": ACTOR},
    )

    read = beliefs.get(f"/api/v1/hypotheses/{hypothesis_id}/publish-gate")

    [failure] = read["failures"]
    assert (failure["code"], failure["belief_ids"]) == ("belief_not_proven", [capture["id"]])
    assert f"{capture['id']} (superseded)" in failure["message"]
