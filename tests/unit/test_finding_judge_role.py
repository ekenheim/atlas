"""The finding judge's role (pilot 0.5.3's fix T2): v3 shows its basis clause by clause and is
sent how a cited Fact was read.

Seam: the role definition (`atlas.roles.finding_judge.FINDING_JUDGE`): its prompt, the strict
schema LiteLLM enforces, and the request as it is serialised for the call.
"""

from atlas.roles.finding_judge import (
    FINDING_JUDGE,
    FINDING_JUDGE_VERSION,
    FindingJudgeRequest,
    JudgedClaim,
    JudgedFinding,
)


def test_the_role_is_v3_and_its_strict_schema_requires_the_clauses() -> None:
    assert (FINDING_JUDGE.name, FINDING_JUDGE.prompt.name, FINDING_JUDGE.prompt.version) == (
        "finding_judge",
        "finding_judge",
        3,
    )
    assert FINDING_JUDGE_VERSION == "finding_judge.v3"
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
