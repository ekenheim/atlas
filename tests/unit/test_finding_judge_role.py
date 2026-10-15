"""The finding judge's role (pilot 0.5.3's fix T2): v3 shows its basis clause by clause and is
sent how a cited Fact was read.

Seam: the role definition (`atlas.roles.finding_judge.FINDING_JUDGE`): its prompt, the strict
schema LiteLLM enforces, and the request as it is serialised for the call.
"""

import hashlib

from atlas.roles.contract import PROMPTS_DIR
from atlas.roles.finding_judge import (
    FINDING_JUDGE,
    FINDING_JUDGE_VERSION,
    THESIS_JUDGE,
    THESIS_JUDGE_VERSION,
    FindingJudgeRequest,
    JudgedClaim,
    JudgedFinding,
    judge_role,
)


def test_the_role_is_v4_and_its_strict_schema_requires_the_clauses() -> None:
    assert (FINDING_JUDGE.name, FINDING_JUDGE.prompt.name, FINDING_JUDGE.prompt.version) == (
        "finding_judge",
        "finding_judge",
        4,
    )
    assert FINDING_JUDGE_VERSION == "finding_judge.v4"
    schema = FINDING_JUDGE.response_schema()
    assert sorted(schema["required"]) == ["beyond", "clauses", "kinds", "reason", "verdict"]
    clause = schema["$defs"]["JudgedClause"]
    assert clause["additionalProperties"] is False
    assert sorted(clause["required"]) == ["basis", "ref", "text"]
    # The protocol is the prompt's: clauses, their bases, `beyond` for a clause with none.
    assert "basis" in FINDING_JUDGE.prompt.text
    assert "status" in FINDING_JUDGE.prompt.text


def test_a_judged_fact_carries_its_status_period_quantity_and_reading() -> None:
    fact = JudgedClaim(
        ref="c1",
        subject="Zephyr Optics",
        predicate="fact",
        object="",
        epistemic_type="company_claim",
        source_title="Zephyr Optics Q3 call",
        status="planned",
        period="by the end of 2027",
        quantity="2 x (capacity multiple)",
        reading="Zephyr Optics plans to double its InP capacity by the end of 2027.",
    )
    claim = JudgedClaim(
        ref="c2",
        subject="Zephyr Optics",
        predicate="supplies",
        object="Halcyon Networks",
        epistemic_type="company_claim",
        source_title="Zephyr Optics 8-K",
    )
    request = FindingJudgeRequest(
        research_question="Who holds InP capacity?",
        finding=JudgedFinding(statement="s", limitations=[], claim_refs=["c1", "c2"]),
        claims=[fact, claim],
    )

    sent = request.model_dump(mode="json")["claims"]
    assert {k: sent[0][k] for k in ("status", "period", "quantity", "reading")} == {
        "status": "planned",
        "period": "by the end of 2027",
        "quantity": "2 x (capacity multiple)",
        "reading": "Zephyr Optics plans to double its InP capacity by the end of 2027.",
    }
    # A Claim has no reading: the fields are sent, empty.
    assert {k: sent[1][k] for k in ("status", "period", "quantity", "reading")} == {
        "status": None,
        "period": None,
        "quantity": None,
        "reading": None,
    }


def test_a_judged_claim_carries_its_source_date_and_the_prompt_is_v4() -> None:
    claim_schema = FindingJudgeRequest.model_json_schema()["$defs"]["JudgedClaim"]
    assert "source_date" in claim_schema["properties"]
    assert FINDING_JUDGE_VERSION == "finding_judge.v4"
    assert "source_date" in FINDING_JUDGE.prompt.text
    assert "90 days" in FINDING_JUDGE.prompt.text
    claim = JudgedClaim(
        ref="c1",
        subject="Zephyr Optics",
        predicate="capacity_constrained",
        object="CW lasers",
        epistemic_type="company_claim",
        source_title="Q3 2026",
        source_date="2025-11-05",
    )
    request = FindingJudgeRequest(
        research_question="q",
        finding=JudgedFinding(statement="s", limitations=[], claim_refs=["c1"]),
        claims=[claim],
    )
    assert request.model_dump(mode="json")["claims"][0]["source_date"] == "2025-11-05"


def test_only_a_thesis_is_judged_by_v5_and_a_finding_s_request_is_v4_s() -> None:
    """The judge's behaviour on every statement but a thesis does not change unmeasured
    (integration of ticket 24): a request without the thesis flag goes to the v4 prompt, byte
    for byte, with no `thesis` key; a thesis goes to v5, the same role name."""
    v4 = (PROMPTS_DIR / "finding_judge.v4.md").read_bytes()
    finding = FindingJudgeRequest(
        research_question="q",
        finding=JudgedFinding(statement="s", limitations=[], claim_refs=["c1"]),
        claims=[],
    )
    thesis = FindingJudgeRequest(
        research_question="q",
        finding=JudgedFinding(statement="s", limitations=[], claim_refs=["c1"], thesis=True),
        claims=[],
    )

    assert judge_role(finding) is FINDING_JUDGE
    assert FINDING_JUDGE.prompt.text.encode("utf-8") == v4
    assert FINDING_JUDGE.prompt.sha256 == hashlib.sha256(v4).hexdigest()
    assert finding.model_dump(mode="json")["finding"] == {
        "statement": "s",
        "limitations": [],
        "claim_refs": ["c1"],
    }
    assert judge_role(thesis) is THESIS_JUDGE
    assert (THESIS_JUDGE.name, THESIS_JUDGE.prompt.version) == ("finding_judge", 5)
    assert THESIS_JUDGE_VERSION == "finding_judge.v5"
    assert thesis.model_dump(mode="json")["finding"]["thesis"] is True
    assert "**A thesis.**" in THESIS_JUDGE.prompt.text
    assert "**A thesis.**" not in FINDING_JUDGE.prompt.text
