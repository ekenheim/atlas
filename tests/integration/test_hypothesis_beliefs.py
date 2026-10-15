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
import shutil
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
THESIS = "Lumentum may be straining its laser capacity as its revenue grows in fiscal year 2026."
ACTOR = "claude-session"
DRAFTER = "hypothesis_editor"  # the Belief draft's role; its asks again and rewrites carry it too


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
        self.fixtures = tmp_path / "edgar"
        shutil.copytree(EDGAR_FIXTURES, self.fixtures)
        self.atlas = Atlas(
            database_url,
            tmp_path,
            hindsight_url,
            litellm_url,
            finding_judge=True,
            hindsight_template_path=TEMPLATE,
        )
        self.atlas.fixtures = self.fixtures
        self.engine = self.atlas.engine
        self.api: TestClient = self.atlas.api
        assert run_apply_template(self.atlas.settings(), None) == 0
        # The ingest runs without Hindsight, so it enqueues no retains to run before the draft.
        plain = make_settings(
            self.atlas.archive,
            database_url=database_url,
            actor=ACTOR,
            themes_config=THEMES,
            sec_fixtures_dir=self.fixtures,
        )
        self.plain = plain
        self.queue = JobQueue(self.engine, actor=Actor(ACTOR))
        self.queue.enqueue(INGEST_KIND, "lumentum", ingest_payload("lumentum", ["8-K"], None))
        assert Worker(self.queue, builtin_registry(plain)).run_once() >= 1

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

    def revise(self, old: str, new: str) -> None:
        """Serve revised bytes for the press release, with a new Last-Modified, ingest it and
        let every job it starts run (the contradiction check, the Beliefs' flags, their
        proposed updates)."""
        path = self.fixtures / "lumentum" / "manifest.json"
        manifest = json.loads(path.read_text())
        entry = next(e for e in manifest["responses"] if e["url"] == URL_EX991)
        entry["headers"]["last-modified"] = "Tue, 18 Aug 2026 20:24:36 GMT"
        path.write_text(json.dumps(manifest, indent=2))
        body = self.fixtures / "lumentum" / entry["file"]
        original = body.read_bytes()
        assert original.count(old.encode()) == 1
        body.write_bytes(original.replace(old.encode(), new.encode()))
        self.queue.enqueue(INGEST_KIND, "second", ingest_payload("lumentum", ["8-K"], None))
        self.settle()

    def settle(self) -> None:
        worker = Worker(self.queue, builtin_registry(self.plain))
        for _ in range(12):
            if worker.run_once() == 0:
                return

    def draft_artifacts(self) -> dict[str, Any]:
        with self.engine.connect() as connection:
            return connection.execute(
                text("SELECT artifacts FROM job WHERE kind = 'draft_hypothesis'")
            ).scalar_one()

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


def editor(
    statements: dict[str, str | list[str]],
    *,
    thesis: str = THESIS,
    thesis_extra: tuple[str, ...] = (),
) -> Callable[[dict[str, Any]], JsonValue]:
    """The Hypothesis Editor: it cites, per step, the Belief it is sent for that step by its
    short reference, with the statement written for that step in `statements`."""

    def respond(body: dict[str, Any]) -> JsonValue:
        request = asked(body)["request"]
        by_step = {each["step"]: each["ref"] for each in request["beliefs"]}
        first = next(iter(by_step.values()))
        answer: dict[str, JsonValue] = {
            "thesis_statement": thesis,
            "thesis_belief_refs": [first, *thesis_extra],
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
                {"step": step, "statement": each, "belief_refs": [by_step[step]]}
                for step, said in statements.items()
                for each in ([said] if isinstance(said, str) else said)
                if step in by_step
            ],
        }
        return answer

    return respond


def supporting(body: dict[str, Any]) -> JsonValue:
    """The finding judge (`finding_judge.v5`): supported, the statement one clause whose basis
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
        DRAFTER,
        ChatReply.answer(
            draft or editor({"constraint": CONSTRAINT_STATEMENT, "capture": CAPTURE_STATEMENT}),
            tokens=(3000, 700),
        ),
    )
    llm.script_role("finding_judge", *(ChatReply.answer(supporting, tokens=(400, 40)),) * 3)
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
        if body["metadata"]["role"] == DRAFTER
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
    # One judge call per statement, the thesis first (ticket 24); the draft's provenance names
    # the Beliefs it was sent.
    assert roles(llm) == [DRAFTER, "finding_judge", "finding_judge", "finding_judge"]
    assert [
        asked(body)["request"]["finding"]["statement"]
        for body in llm.chat_requests()
        if body["metadata"]["role"] == "finding_judge"
    ] == [THESIS, CONSTRAINT_STATEMENT, CAPTURE_STATEMENT]
    assert (content["thesis_statement"], content["thesis_judged"]) == (THESIS, "supported")
    assert content["thesis_misstated_reason"] is None
    provenance = version["provenance"]
    # The draft is the v2 prompt, under its own role name; statements carry no quotation marks.
    [drafted] = [
        each
        for each in beliefs.get(f"/api/v1/runs/{provenance['draft_run_id']}/role-calls")[
            "role_calls"
        ]
        if each["role"] == DRAFTER
    ]
    assert (drafted["prompt_name"], drafted["prompt_version"]) == ("editor-hypothesis-beliefs", 2)
    assert [each["statement"] for each in content["steps"]] == [
        CONSTRAINT_STATEMENT,
        CAPTURE_STATEMENT,
    ]
    assert not any('"' in each["statement"] for each in content["steps"])
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
    llm.script_role(DRAFTER, ChatReply.answer(citing_badly, tokens=(3000, 700)))
    # The rewrite of the misstated capture statement, grounded but judged misstated again.
    llm.script_role(DRAFTER, ChatReply.answer(rewriting(REWRITTEN), tokens=(800, 80)))
    # thesis and constraint: supported; capture: misstated, rewritten, misstated again.
    llm.script_role(
        "finding_judge",
        ChatReply.answer(supporting, tokens=(400, 40)),
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
    assert roles(llm) == [
        DRAFTER,
        *["finding_judge"] * 3,
        DRAFTER,
        "finding_judge",
    ]


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
        DRAFTER, ChatReply.answer(editor({"capture": CAPTURE_STATEMENT}), tokens=(3000, 700))
    )
    llm.script_role("finding_judge", *(ChatReply.answer(supporting, tokens=(400, 40)),) * 2)

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


# --- review fixes: several statements, the thesis, the cutoff, references ------------------------

SECOND_POINT = "Lumentum's fiscal 2026 fourth-quarter net revenue was $1.01 billion."
REWORDED = "Lumentum reported net revenue of $1.01 billion, up sharply, in fiscal year 2026."


def test_several_statements_of_a_step_are_kept_and_a_rejected_one_is_recorded(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    llm.script_role(
        DRAFTER,
        ChatReply.answer(
            editor(
                {
                    "constraint": [
                        CONSTRAINT_STATEMENT,
                        SECOND_POINT,
                        "Lumentum reported $1.01 billion.",
                    ]
                }
            ),
            tokens=(3000, 700),
        ),
    )
    llm.script_role(DRAFTER, ChatReply.answer(rewriting(REWORDED), tokens=(800, 80)))
    # The thesis and the first two points are supported; the third is misstated, rewritten and
    # misstated again.
    llm.script_role(
        "finding_judge",
        ChatReply.answer(supporting, tokens=(400, 40)),
        ChatReply.answer(supporting, tokens=(400, 40)),
        ChatReply.answer(supporting, tokens=(400, 40)),
        ChatReply.answer(misstating, tokens=(400, 40)),
        ChatReply.answer(misstating, tokens=(400, 40)),
    )
    saved = beliefs.create()
    beliefs.worker_pass()

    hypothesis = beliefs.hypothesis(saved["id"])
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    content = hypothesis["versions"][0]["content"]
    [step] = content["steps"]
    assert [each["statement"] for each in step["statements"]] == [
        CONSTRAINT_STATEMENT,
        SECOND_POINT,
    ]
    assert [each["judged"] for each in step["statements"]] == [True, True]
    assert step["statement"] == CONSTRAINT_STATEMENT  # the first, for the single form
    [dropped] = content["unsupported_findings"]
    assert dropped["statement"] == REWORDED
    assert dropped["reason"].startswith("misstated after a rewrite")


def test_an_ungrounded_thesis_is_asked_again_once_and_then_the_draft_is_refused(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    llm.script_role(
        DRAFTER,
        ChatReply.answer(
            editor({"constraint": CONSTRAINT_STATEMENT}, thesis="Lumentum may earn $9.99 billion."),
            tokens=(3000, 700),
        ),
    )
    llm.script_role(
        DRAFTER, ChatReply.answer(rewriting("Lumentum may earn $8.88 billion."), tokens=(800, 80))
    )
    saved = beliefs.create()
    beliefs.worker_pass()

    hypothesis = beliefs.hypothesis(saved["id"])
    assert hypothesis["draft_status"] == "failed"
    assert "thesis statement is ungrounded" in hypothesis["draft_error"]
    assert hypothesis["versions"] == []
    assert roles(llm) == [DRAFTER, DRAFTER]  # the draft, and the one ask again
    # The ask again is the draft's own (ticket 25): under the draft's role name, saying the
    # draft's rules (no quotation marks), and told that the statement is the thesis.
    _, again = llm.chat_requests()
    assert "drafting a Hypothesis" in again["messages"][0]["content"]
    assert "Write no quotation marks" in again["messages"][0]["content"]
    [ungrounded] = asked(again)["request"]["findings"]
    assert (ungrounded["finding"], ungrounded["thesis"]) == ("f1", True)


def test_a_thesis_the_editor_repairs_when_asked_again_is_kept(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    repaired = "Lumentum may be straining its capacity as revenue reached $1.01 billion."
    llm.script_role(
        DRAFTER,
        ChatReply.answer(
            editor({"constraint": CONSTRAINT_STATEMENT}, thesis="Lumentum may earn $9.99 billion."),
            tokens=(3000, 700),
        ),
    )
    llm.script_role(DRAFTER, ChatReply.answer(rewriting(repaired), tokens=(800, 80)))
    llm.script_role("finding_judge", *(ChatReply.answer(supporting, tokens=(400, 40)),) * 2)
    saved = beliefs.create()
    beliefs.worker_pass()

    hypothesis = beliefs.hypothesis(saved["id"])
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    assert hypothesis["versions"][0]["content"]["thesis_statement"] == repaired


# --- the thesis is judged (ticket 24) ---------------------------------------------------------

BROAD_THESIS = "Lumentum may be straining its laser capacity in the merchant market in fiscal 2026."
STILL_BROAD = (
    "Lumentum may be straining its merchant laser capacity as revenue grows in fiscal 2026."
)
HEDGED = "Lumentum may be straining its laser capacity as net revenue reached $1.01 billion."


def judged_statements(llm: FakeLiteLLM) -> list[str]:
    return [
        asked(body)["request"]["finding"]["statement"]
        for body in llm.chat_requests()
        if body["metadata"]["role"] == "finding_judge"
    ]


def test_a_thesis_with_an_unsupported_qualifier_is_held_at_the_gate_after_one_rewrite(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    constraint = beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    llm.script_role(
        DRAFTER,
        ChatReply.answer(
            editor({"constraint": CONSTRAINT_STATEMENT}, thesis=BROAD_THESIS), tokens=(3000, 700)
        ),
    )
    llm.script_role(DRAFTER, ChatReply.answer(rewriting(STILL_BROAD), tokens=(800, 80)))
    # The thesis: misstated, rewritten, misstated again. The step statement: supported.
    llm.script_role(
        "finding_judge",
        ChatReply.answer(misstating, tokens=(400, 40)),
        ChatReply.answer(supporting, tokens=(400, 40)),
        ChatReply.answer(misstating, tokens=(400, 40)),
    )
    saved = beliefs.create()
    beliefs.worker_pass()

    hypothesis = beliefs.hypothesis(saved["id"])
    # Stored, not refused: the thesis as last judged (the Editor's rewrite), flagged with the
    # judge's reason for it.
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    content = hypothesis["versions"][0]["content"]
    assert content["thesis_statement"] == STILL_BROAD
    assert content["thesis_judged"] == "misstated"
    assert content["thesis_misstated_reason"] == (
        "misstated after a rewrite: the quote states another period"
    )
    assert content["steps"][0]["statement"] == CONSTRAINT_STATEMENT
    assert content["unsupported_findings"] == []
    assert roles(llm) == [DRAFTER, "finding_judge", "finding_judge", DRAFTER, "finding_judge"]
    assert judged_statements(llm) == [BROAD_THESIS, CONSTRAINT_STATEMENT, STILL_BROAD]
    assert beliefs.draft_artifacts()["thesis_judged"] == "misstated"

    # The owner sees it at the gate, and the Belief override does not cover it.
    beliefs.post(f"/api/v1/hypotheses/{saved['id']}/transitions", {"to": "evidence_ready"})
    read = beliefs.get(f"/api/v1/hypotheses/{saved['id']}/publish-gate")
    [failure] = read["failures"]
    assert (failure["code"], failure["belief_ids"]) == ("thesis_misstated", [constraint["id"]])
    assert "misstated after a rewrite: the quote states another period" in failure["message"]
    assert read["publishable"] is False
    refused = publish(beliefs, saved["id"], override_beliefs=True, override_reason="reviewed")
    assert refused.status_code == 422
    assert [each["code"] for each in refused.json()["error"]["failures"]] == ["thesis_misstated"]

    # A correction that rewrites the thesis is no longer the thesis the judge saw.
    beliefs.post(
        f"/api/v1/hypotheses/{saved['id']}/versions",
        {"based_on_version": 1, "note": "drops the qualifier", "thesis_statement": THESIS},
        status=201,
    )
    assert beliefs.get(f"/api/v1/hypotheses/{saved['id']}/publish-gate")["failures"] == []
    [_, second] = beliefs.hypothesis(saved["id"])["versions"]
    assert (second["content"]["thesis_judged"], second["content"]["thesis_misstated_reason"]) == (
        None,
        None,
    )
    assert publish(beliefs, saved["id"], version=2).status_code == 200


def test_a_hedged_thesis_passes_and_a_misstated_one_the_editor_repairs_is_kept(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    llm.script_role(
        DRAFTER,
        ChatReply.answer(
            editor({"constraint": CONSTRAINT_STATEMENT}, thesis=BROAD_THESIS), tokens=(3000, 700)
        ),
    )
    # The rewrite keeps the "may" the Beliefs do not carry: caution is not a claim beyond the
    # quotes, so the judge supports it.
    llm.script_role(DRAFTER, ChatReply.answer(rewriting(HEDGED), tokens=(800, 80)))
    llm.script_role(
        "finding_judge",
        ChatReply.answer(misstating, tokens=(400, 40)),
        ChatReply.answer(supporting, tokens=(400, 40)),
        ChatReply.answer(supporting, tokens=(400, 40)),
    )
    saved = beliefs.create()
    beliefs.worker_pass()

    version = beliefs.hypothesis(saved["id"])["versions"][0]
    content = version["content"]
    assert (content["thesis_statement"], content["thesis_judged"]) == (HEDGED, "supported")
    assert content["thesis_misstated_reason"] is None
    assert '"' not in content["thesis_statement"]
    assert judged_statements(llm) == [BROAD_THESIS, CONSTRAINT_STATEMENT, HEDGED]
    # The rewrite of the misstated thesis is recorded under the draft's role name, with the
    # draft's rules (ticket 25), not as the card Editor's `editor` call; it is told what it
    # rewrites is the thesis, and the statement it is given is not.
    calls = beliefs.get(f"/api/v1/runs/{version['provenance']['draft_run_id']}/role-calls")[
        "role_calls"
    ]
    assert [(each["role"], each["prompt_name"], each["prompt_version"]) for each in calls] == [
        (DRAFTER, "editor-hypothesis-beliefs", 2),
        ("finding_judge", "finding_judge", 5),  # the thesis
        ("finding_judge", "finding_judge", 4),  # the constraint statement
        (DRAFTER, "editor-hypothesis-revise", 1),
        ("finding_judge", "finding_judge", 5),  # the rewritten thesis
    ]
    [_, revise] = [b for b in llm.chat_requests() if b["metadata"]["role"] == DRAFTER]
    [misstated] = asked(revise)["request"]["findings"]
    assert (misstated["finding"], misstated["thesis"], misstated["statement"]) == (
        "f1",
        True,
        BROAD_THESIS,
    )
    beliefs.post(f"/api/v1/hypotheses/{saved['id']}/transitions", {"to": "evidence_ready"})
    assert beliefs.get(f"/api/v1/hypotheses/{saved['id']}/publish-gate")["failures"] == []


def clausing(*, scope: bool = False) -> Callable[[dict[str, Any]], JsonValue]:
    """The finding judge as `finding_judge.v5` asks it to behave on a thesis: it answers
    `supported`, splitting the statement at " as " into the hedged proposition (no quote states
    it: no reference, no basis) and the clause a quote does state. `scope`: it also splits out
    the scope word "merchant", which no quote states, and still says `supported` (a judge's
    slip code must catch). It answers as it does only when told the statement is a thesis."""

    def respond(body: dict[str, Any]) -> JsonValue:
        request = asked(body)
        assert request["request"]["finding"]["thesis"] is True
        statement = request["request"]["finding"]["statement"]
        quote = request["retrieved_data"][0]
        proposition, _, rest = statement.partition(" as ")
        clauses: list[JsonValue] = [{"text": proposition, "ref": None, "basis": None}]
        if scope:
            clauses = [
                {
                    "text": "Lumentum may be straining its laser capacity",
                    "ref": None,
                    "basis": None,
                },
                {"text": "in the merchant market", "ref": None, "basis": None},
            ]
        return {
            "clauses": [
                *clauses,
                {"text": f"as {rest}", "ref": quote["id"], "basis": "$1.01 billion"},
            ],
            "verdict": "supported",
            "beyond": [],
            "kinds": [],
            "reason": "the proposition is hedged and the figure is the quote's",
        }

    return respond


def test_a_hedged_proposition_with_no_quote_basis_leaves_the_thesis_supported(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    """A judge that follows `finding_judge.v5` gives a thesis's bare hedged proposition no
    basis; code does not turn that into `unstated` for a thesis (it still does for a step)."""
    beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    llm.script_role(
        DRAFTER,
        ChatReply.answer(
            editor({"constraint": CONSTRAINT_STATEMENT}, thesis=HEDGED), tokens=(3000, 700)
        ),
    )
    llm.script_role(
        "finding_judge",
        ChatReply.answer(clausing(), tokens=(400, 40)),
        ChatReply.answer(supporting, tokens=(400, 40)),
    )
    saved = beliefs.create()
    beliefs.worker_pass()

    content = beliefs.hypothesis(saved["id"])["versions"][0]["content"]
    assert (content["thesis_statement"], content["thesis_judged"]) == (HEDGED, "supported")
    assert content["thesis_misstated_reason"] is None
    # Only the thesis's request says so, and only it is judged by v5; the step's request is
    # v4's, byte for byte (no `thesis` key), judged by the v4 prompt.
    flags = [
        asked(body)["request"]["finding"].get("thesis")
        for body in llm.chat_requests()
        if body["metadata"]["role"] == "finding_judge"
    ]
    assert flags == [True, None]
    run = beliefs.hypothesis(saved["id"])["versions"][0]["provenance"]["draft_run_id"]
    judged = [
        (each["prompt_name"], each["prompt_version"])
        for each in beliefs.get(f"/api/v1/runs/{run}/role-calls")["role_calls"]
        if each["role"] == "finding_judge"
    ]
    assert sorted(judged) == [("finding_judge", 4), ("finding_judge", 5)]
    systems = [
        body["messages"][0]["content"]
        for body in llm.chat_requests()
        if body["metadata"]["role"] == "finding_judge"
    ]
    assert ["**A thesis.**" in each for each in systems] == [True, False]
    beliefs.post(f"/api/v1/hypotheses/{saved['id']}/transitions", {"to": "evidence_ready"})
    assert beliefs.get(f"/api/v1/hypotheses/{saved['id']}/publish-gate")["failures"] == []


def test_a_scope_word_no_quote_states_still_makes_the_thesis_misstated(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    """The hedge excuses only the bare proposition: "merchant" has no basis, so a `supported`
    vote is `misstated` (`unstated`), the Editor rewrites once, and the thesis is held."""
    beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    llm.script_role(
        DRAFTER,
        ChatReply.answer(
            editor({"constraint": CONSTRAINT_STATEMENT}, thesis=BROAD_THESIS), tokens=(3000, 700)
        ),
    )
    llm.script_role(DRAFTER, ChatReply.answer(rewriting(BROAD_THESIS), tokens=(800, 80)))
    llm.script_role(
        "finding_judge",
        ChatReply.answer(clausing(scope=True), tokens=(400, 40)),
        ChatReply.answer(supporting, tokens=(400, 40)),
        ChatReply.answer(clausing(scope=True), tokens=(400, 40)),
    )
    saved = beliefs.create()
    beliefs.worker_pass()

    content = beliefs.hypothesis(saved["id"])["versions"][0]["content"]
    assert (content["thesis_statement"], content["thesis_judged"]) == (BROAD_THESIS, "misstated")
    reason = content["thesis_misstated_reason"]
    assert reason.startswith(
        'misstated after a rewrite: basis unverified: "in the merchant market"'
    )
    assert "may be straining" not in reason.split("(the judge's reason")[0]
    assert content["steps"][0]["statement"] == CONSTRAINT_STATEMENT


def test_a_thesis_is_stored_unjudged_when_the_judge_is_off_or_its_call_fails(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    llm.script_role(
        DRAFTER,
        ChatReply.answer(editor({"constraint": CONSTRAINT_STATEMENT}), tokens=(3000, 700)),
    )
    # The thesis judge call is answered with something that is not the judge's schema, twice
    # (the call and its one repair): quarantined, so the thesis stays unjudged; the step's passes.
    llm.script_role(
        "finding_judge",
        ChatReply.text("not json"),
        ChatReply.text("not json"),
        ChatReply.answer(supporting, tokens=(400, 40)),
    )
    saved = beliefs.create()
    beliefs.worker_pass()

    hypothesis = beliefs.hypothesis(saved["id"])
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    content = hypothesis["versions"][0]["content"]
    assert (content["thesis_statement"], content["thesis_judged"]) == (THESIS, None)
    assert content["steps"][0]["statement"] == CONSTRAINT_STATEMENT


def test_the_belief_draft_routes_by_its_own_role_name(beliefs: Beliefs, llm: FakeLiteLLM) -> None:
    beliefs.atlas.overrides["llm_role_models"] = {"hypothesis_editor": "judge-model"}
    beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    llm.script_role(
        DRAFTER,
        ChatReply.answer(editor({"constraint": CONSTRAINT_STATEMENT}), tokens=(3000, 700)),
    )
    llm.script_role("finding_judge", *(ChatReply.answer(supporting, tokens=(400, 40)),) * 2)
    saved = beliefs.create()
    beliefs.worker_pass()

    hypothesis = beliefs.hypothesis(saved["id"])
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    assert [(body["metadata"]["role"], body["model"]) for body in llm.chat_requests()] == [
        (DRAFTER, "judge-model"),
        ("finding_judge", "MiniMax-M3"),
        ("finding_judge", "MiniMax-M3"),
    ]
    run = hypothesis["versions"][0]["provenance"]["draft_run_id"]
    recorded = {
        each["role"]: each["model"]
        for each in beliefs.get(f"/api/v1/runs/{run}/role-calls")["role_calls"]
    }
    assert recorded == {DRAFTER: "judge-model", "finding_judge": "MiniMax-M3"}


def test_a_reference_the_editor_was_not_sent_is_recorded_in_the_drafts_artifacts(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    llm.script_role(
        DRAFTER,
        ChatReply.answer(
            editor({"constraint": CONSTRAINT_STATEMENT}, thesis_extra=("b9",)),
            tokens=(3000, 700),
        ),
    )
    llm.script_role("finding_judge", *(ChatReply.answer(supporting, tokens=(400, 40)),) * 2)
    saved = beliefs.create()
    beliefs.worker_pass()

    hypothesis = beliefs.hypothesis(saved["id"])
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    assert len(hypothesis["versions"][0]["content"]["thesis_belief_ids"]) == 1
    assert beliefs.draft_artifacts()["unresolved_refs"] == ["b9"]


def test_the_draft_takes_only_beliefs_as_of_the_versions_cutoff(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    beliefs.belief(CONSTRAINT, "constraint", QUARTER)
    later = beliefs.post(
        "/api/v1/beliefs",
        {
            "statement": CAPTURE,
            "theme": "photonics",
            "step": "capture",
            "company_ids": [beliefs.company_id()],
            "as_of": "2026-10-20T00:00:00Z",
            "actor": ACTOR,
            "citations": [{"ref_id": beliefs.fact(YEAR), "valence": 0.9, "weight": "load_bearing"}],
        },
        status=201,
    )
    beliefs.judge(later["id"], "proven")
    llm.script_role(
        DRAFTER,
        ChatReply.answer(editor({"constraint": CONSTRAINT_STATEMENT}), tokens=(3000, 700)),
    )
    llm.script_role("finding_judge", *(ChatReply.answer(supporting, tokens=(400, 40)),) * 2)

    saved = beliefs.create(as_of="2026-10-01T00:00:00Z")
    beliefs.worker_pass()

    hypothesis = beliefs.hypothesis(saved["id"])
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    assert hypothesis["as_of"].startswith("2026-10-01")
    [request] = [
        asked(body)["request"]
        for body in llm.chat_requests()
        if body["metadata"]["role"] == DRAFTER
    ]
    assert [each["step"] for each in request["beliefs"]] == ["constraint"]
    # Nothing as of that time and proven: nothing to draft from.
    nothing = beliefs.api.post(
        "/api/v1/hypotheses", json={"theme": "photonics", "as_of": "2026-01-01T00:00:00Z"}
    )
    assert nothing.status_code == 409


def test_an_open_flag_on_a_step_belief_holds_the_gate_and_the_override_covers_it(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    hypothesis, constraint, _ = ready(beliefs, llm)
    hypothesis_id = hypothesis["id"]
    beliefs.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/transitions", json={"to": "evidence_ready"}
    )
    fact = beliefs.get(f"/api/v1/beliefs/{constraint['id']}")["citations"][0]["ref_id"]
    beliefs.post(f"/api/v1/assertions/{fact}/review", {"review_state": "disputed"})

    read = beliefs.get(f"/api/v1/hypotheses/{hypothesis_id}/publish-gate")

    [failure] = read["failures"]
    assert (failure["code"], failure["belief_ids"]) == ("belief_flagged", [constraint["id"]])
    refused = publish(beliefs, hypothesis_id)
    assert refused.status_code == 422
    assert [each["code"] for each in refused.json()["error"]["failures"]] == ["belief_flagged"]

    overridden = publish(
        beliefs, hypothesis_id, override_beliefs=True, override_reason="the dispute is noise"
    )

    assert overridden.status_code == 200, overridden.text
    with beliefs.engine.connect() as connection:
        [belief_ids] = connection.execute(
            text("SELECT belief_ids FROM hypothesis_belief_override")
        ).scalars()
    assert [str(each) for each in belief_ids] == [constraint["id"]]


def test_scenarios_on_a_hypothesis_over_beliefs_have_no_analyst_proposal(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    hypothesis, _, _ = ready(beliefs, llm)

    response = beliefs.api.post(
        f"/api/v1/hypotheses/{hypothesis['id']}/scenarios", json={"version": 1}
    )

    assert response.status_code == 409, response.text


# --- a published version depends on its Beliefs --------------------------------------------------


def published(beliefs: Beliefs, llm: FakeLiteLLM) -> tuple[str, dict[str, Any], dict[str, Any]]:
    hypothesis, constraint, capture = ready(beliefs, llm)
    beliefs.api.post(
        f"/api/v1/hypotheses/{hypothesis['id']}/transitions", json={"to": "evidence_ready"}
    )
    assert publish(beliefs, hypothesis["id"]).status_code == 200
    return hypothesis["id"], constraint, capture


def updates(beliefs: Beliefs, hypothesis_id: str) -> list[dict[str, Any]]:
    return beliefs.get(f"/api/v1/hypotheses/{hypothesis_id}/proposed-updates")["items"]


def test_a_belief_flagged_by_a_revised_source_proposes_an_update_to_the_published_version(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    hypothesis_id, constraint, capture = published(beliefs, llm)
    assert updates(beliefs, hypothesis_id) == []

    beliefs.revise("$1.01 billion, with GAAP net loss", "$1.02 billion, with GAAP net loss")

    [update] = updates(beliefs, hypothesis_id)
    assert (update["trigger"], update["state"], update["hypothesis_version"]) == (
        "belief_changed",
        "open",
        1,
    )
    [evidence] = update["evidence"]
    assert (evidence["kind"], evidence["id"]) == ("belief", constraint["id"])
    assert "flagged" in evidence["description"] and CONSTRAINT in evidence["description"]
    # The steps the Belief is in; the other Belief's step is not.
    [affected] = update["affected_findings"]
    assert affected["claim_text"].startswith("constraint:")
    assert affected["assertion_ids"] == []
    assert update["summary"].startswith("A Belief version 1 rests on changed")
    assert beliefs.get(f"/api/v1/beliefs/{capture['id']}")["open_flags"] == 0
    # The published version is untouched.
    assert beliefs.hypothesis(hypothesis_id)["versions"][0]["published"] is True


def test_a_published_versions_belief_judged_otherwise_or_superseded_proposes_an_update(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    hypothesis_id, constraint, capture = published(beliefs, llm)

    # Judged again as it was: nothing changed, nothing proposed.
    beliefs.judge(constraint["id"], "proven", 0.9)
    beliefs.settle()
    assert updates(beliefs, hypothesis_id) == []

    beliefs.judge(constraint["id"], "unproven", 0.3)
    beliefs.post(
        f"/api/v1/beliefs/{capture['id']}/supersede",
        {"by": [constraint["id"]], "reason": "restated", "actor": ACTOR},
    )
    beliefs.settle()

    found = {each["evidence"][0]["id"]: each for each in updates(beliefs, hypothesis_id)}
    assert set(found) == {constraint["id"], capture["id"]}
    assert (
        "judged unproven (it was proven)" in found[constraint["id"]]["evidence"][0]["description"]
    )
    assert "superseded" in found[capture["id"]]["evidence"][0]["description"]
    # Each event once: a retried job adds nothing.
    beliefs.settle()
    assert len(updates(beliefs, hypothesis_id)) == 2


def test_the_mcp_get_hypothesis_reads_the_drafted_steps_and_the_gate_after_a_rejudgement(
    beliefs: Beliefs, llm: FakeLiteLLM
) -> None:
    """The Editor prompt's read side (ticket 16): `get_hypothesis` over the drafted version."""
    hypothesis, constraint, capture = ready(beliefs, llm)
    opened = beliefs.post(
        "/api/v1/sessions",
        {
            "question": "Editor: draft a Hypothesis from photonics' proven Beliefs",
            "theme": "photonics",
            "seed_company_ids": [],
            "as_of": "2026-10-01T00:00:00Z",
            "kind": "claude",
            "model": "claude-editor",
            "actor": ACTOR,
        },
        status=201,
    )

    def read() -> dict[str, Any]:
        reply = beliefs.api.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_hypothesis",
                    "arguments": {"session_id": opened["id"], "hypothesis_id": hypothesis["id"]},
                },
            },
        ).json()["result"]
        assert not reply["isError"], reply
        return reply["structuredContent"]

    drafted = read()
    assert (drafted["draft_status"], drafted["draft_error"]) == ("drafted", None)
    version = drafted["version"]
    assert version["thesis_belief_ids"] == [constraint["id"]]
    assert (version["thesis_judged"], version["thesis_misstated_reason"]) == ("supported", None)
    assert [step["step"] for step in version["steps"]] == ["constraint", "capture"]
    [first] = version["steps"][0]["statements"]
    assert (first["statement"], first["belief_ids"], first["judged"]) == (
        CONSTRAINT_STATEMENT,
        [constraint["id"]],
        True,
    )
    [rests_on] = version["steps"][0]["beliefs"]
    assert (rests_on["belief_id"], rests_on["judgement"], rests_on["confidence"]) == (
        constraint["id"],
        "proven",
        0.8,
    )
    assert version["steps_without_statement"] == []
    assert version["unsupported_findings"] == []
    # A fresh draft is `draft`, not yet `evidence_ready`: blocked whatever the checks say.
    assert drafted["publish_gate"]["blocked"] == "status_not_publishable"
    assert drafted["publish_gate"]["failures"] == []

    # The owner rejudges a Belief the draft rests on: the gate holds, and says which Belief.
    beliefs.judge(capture["id"], "unproven")
    held = read()["publish_gate"]
    assert held["publishable"] is False
    [failure] = held["failures"]
    assert failure["code"] == "belief_not_proven"
    assert failure["belief_ids"] == [capture["id"]]
    # The edges and Assertions a failure names are read too (empty for this code).
    assert (failure["relationship_ids"], failure["assertion_ids"]) == ([], [])
