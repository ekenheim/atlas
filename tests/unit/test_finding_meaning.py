"""Findings checked for meaning against their quotes (bottleneck-argument ticket 04).

Seam: `atlas.investigations.meaning.judge_findings`, with the judge and the Editor's rewrite
as the callables the Editor's task hands it (in production, role calls through LiteLLM; the
investigation's end-to-end test drives them through the scripted LiteLLM fake). The quotes
are synthetic, shaped like the pilot's; none is production text.
"""

import uuid
from collections.abc import Callable
from typing import Any

from atlas.investigations.grounding import CheckedFinding
from atlas.investigations.meaning import judge_findings
from atlas.roles.caller import RoleOutputQuarantined, TokenBudgetExhausted
from atlas.roles.contract import QuotedText
from atlas.roles.editor import (
    CardFindingDraft,
    EditorReviseRequest,
    RevisedFinding,
    RevisedFindings,
)
from atlas.roles.finding_judge import FindingJudgement, FindingJudgeRequest

QUESTION = "Who holds qualified 200G EML capacity?"
AGREEMENT = (
    "On May 14, 2026, Zephyr Optics Inc. entered into a Master Development and Supply"
    " Agreement with Halcyon Networks for 200G EMLs."
)
CALL = "Our 6-inch line in Rosemont is producing CW lasers, and demand exceeds our supply."
VERSION = uuid.UUID("0b6d5f3e-3a52-4f43-9a51-5f0a5e1d1c01")
CLAIMS: dict[str, dict[str, Any]] = {
    "c1": {
        "id": uuid.UUID("7f1c2b3a-0000-4000-8000-000000000001"),
        "quote": AGREEMENT,
        "subject_name": "Zephyr Optics",
        "object_name": "Halcyon Networks",
        "object_text": None,
        "predicate": "supplies",
        "product": "200G EML",
        "layer": "component",
        "epistemic_type": "company_claim",
        "source_title": "Zephyr Optics 8-K",
        "source_version_id": VERSION,
        "span_start": 10,
        "span_end": 10 + len(AGREEMENT),
    },
    "c2": {
        "id": uuid.UUID("7f1c2b3a-0000-4000-8000-000000000002"),
        "quote": CALL,
        "subject_name": "Zephyr Optics",
        "object_name": None,
        "object_text": "CW lasers",
        "predicate": "capacity_constrained",
        "product": "CW laser",
        "layer": "component",
        "epistemic_type": "company_claim",
        "source_title": "Zephyr Optics Q3 call",
        "source_version_id": VERSION,
        "span_start": 400,
        "span_end": 400 + len(CALL),
    },
}

SUPPORTED_STATEMENT = "Zephyr Optics says its 6-inch line in Rosemont is producing CW lasers."
MISSTATED_STATEMENT = "Zephyr Optics supplies 200G EMLs to Halcyon Networks."
REWRITTEN = (
    "Zephyr Optics entered into a Master Development and Supply Agreement with Halcyon"
    " Networks for 200G EMLs on May 14, 2026."
)


def finding(statement: str, *refs: str) -> CheckedFinding:
    draft = CardFindingDraft(
        statement=statement,
        claim_refs=list(refs),
        limitations=["A company's own statement."],
        open_questions=[],
    )
    return CheckedFinding(draft, list(refs), [])


def supported() -> FindingJudgement:
    return FindingJudgement(verdict="supported", beyond=[], kinds=[], reason="c2 states it.")


def misstated(
    reason: str = "c1 is an agreement; it does not say supply has begun.",
) -> FindingJudgement:
    return FindingJudgement(
        verdict="misstated",
        beyond=["supplies 200G EMLs to Halcyon Networks"],
        kinds=["tense_or_status"],
        reason=reason,
    )


class Judge:
    """The judge's scripted verdicts, by statement; records what it was asked."""

    def __init__(self, verdicts: dict[str, FindingJudgement | Exception]) -> None:
        self.verdicts = verdicts
        self.asked: list[tuple[FindingJudgeRequest, list[QuotedText]]] = []

    def __call__(
        self, request: FindingJudgeRequest, quotes: list[QuotedText]
    ) -> tuple[FindingJudgement, uuid.UUID]:
        self.asked.append((request, quotes))
        verdict = self.verdicts[request.finding.statement]
        if isinstance(verdict, Exception):
            raise verdict
        return verdict, uuid.uuid4()


def revising(
    *answers: tuple[str, str], failure: Exception | None = None
) -> tuple[list[EditorReviseRequest], Callable[..., tuple[RevisedFindings, uuid.UUID]]]:
    asked: list[EditorReviseRequest] = []

    def revise(
        request: EditorReviseRequest, quotes: list[QuotedText]
    ) -> tuple[RevisedFindings, uuid.UUID]:
        asked.append(request)
        if failure is not None:
            raise failure
        return (
            RevisedFindings(
                findings=[
                    RevisedFinding(finding=key, statement=text, limitations=[])
                    for key, text in answers
                ]
            ),
            uuid.uuid4(),
        )

    return asked, revise


def never(*_: Any) -> Any:
    raise AssertionError("not expected to be called")


def test_a_supported_finding_is_kept_and_its_verdict_recorded() -> None:
    judge = Judge({SUPPORTED_STATEMENT: supported()})

    result = judge_findings(
        [finding(SUPPORTED_STATEMENT, "c2")], CLAIMS, QUESTION, [], judge, never
    )

    [outcome] = result.outcomes
    assert (outcome.kept, outcome.judged, outcome.draft.statement) == (
        True,
        True,
        SUPPORTED_STATEMENT,
    )
    # The judge was sent the finding and only its cited Claims' exact quotes.
    [(request, quotes)] = judge.asked
    assert request.research_question == QUESTION
    assert request.finding.limitations == ["A company's own statement."]
    assert [c.ref for c in request.claims] == ["c2"]
    assert [(q.id, q.text, q.trust) for q in quotes] == [("c2", CALL, "low")]
    [verdict] = result.judgements
    assert (verdict.finding, verdict.attempt, verdict.verdict, verdict.outcome) == (
        "f1",
        1,
        "supported",
        "kept",
    )
    assert verdict.claim_ids == [CLAIMS["c2"]["id"]]
    assert verdict.judge == "finding_judge.v2"


def test_a_misstated_finding_is_rewritten_with_the_judge_s_reason_and_kept_when_supported() -> None:
    judge = Judge(
        {
            SUPPORTED_STATEMENT: supported(),
            MISSTATED_STATEMENT: misstated(),
            REWRITTEN: supported(),
        }
    )
    asked, revise = revising(("f2", REWRITTEN))

    result = judge_findings(
        [finding(SUPPORTED_STATEMENT, "c2"), finding(MISSTATED_STATEMENT, "c1")],
        CLAIMS,
        QUESTION,
        [],
        judge,
        revise,
    )

    # The Editor was asked once, for the misstated finding only, with the judge's words.
    [request] = asked
    [sent] = request.findings
    assert (sent.finding, sent.statement, sent.beyond, sent.kinds, sent.reason) == (
        "f2",
        MISSTATED_STATEMENT,
        ["supplies 200G EMLs to Halcyon Networks"],
        ["tense_or_status"],
        "c1 is an agreement; it does not say supply has begun.",
    )
    assert [c.ref for c in request.claims] == ["c1"]
    assert [o.draft.statement for o in result.outcomes if o.kept] == [
        SUPPORTED_STATEMENT,
        REWRITTEN,
    ]
    assert all(o.judged for o in result.outcomes)
    assert [(j.finding, j.attempt, j.verdict, j.outcome) for j in result.judgements] == [
        ("f1", 1, "supported", "kept"),
        ("f2", 1, "misstated", "sent_back"),
        ("f2", 2, "supported", "kept"),
    ]
    assert result.counts["rewritten_kept"] == 1
    assert result.counts["dropped"] == 0


def test_a_finding_still_misstated_after_its_rewrite_is_dropped_with_the_reason() -> None:
    still = "Zephyr Optics is shipping 200G EMLs to Halcyon Networks under its agreement."
    judge = Judge(
        {MISSTATED_STATEMENT: misstated(), still: misstated("c1 does not say it is shipping.")}
    )
    _, revise = revising(("f1", still))

    result = judge_findings(
        [finding(MISSTATED_STATEMENT, "c1")], CLAIMS, QUESTION, [], judge, revise
    )

    [outcome] = result.outcomes
    assert (outcome.kept, outcome.draft.statement) == (False, still)
    assert outcome.reason == "misstated after a rewrite: c1 does not say it is shipping."
    assert [(j.attempt, j.verdict, j.outcome) for j in result.judgements] == [
        (1, "misstated", "sent_back"),
        (2, "misstated", "dropped"),
    ]


def test_a_rewrite_that_brings_in_an_ungrounded_figure_is_dropped_without_judging_it() -> None:
    ungrounded = "Zephyr Optics agreed to supply 400G EMLs to Halcyon Networks."
    judge = Judge({MISSTATED_STATEMENT: misstated()})
    _, revise = revising(("f1", ungrounded))

    result = judge_findings(
        [finding(MISSTATED_STATEMENT, "c1")], CLAIMS, QUESTION, [], judge, revise
    )

    [outcome] = result.outcomes
    assert not outcome.kept
    assert outcome.reason is not None and outcome.reason.endswith(
        "rewritten, then ungrounded: 400G"
    )
    assert len(judge.asked) == 1


def test_a_finding_the_rewrite_leaves_out_or_that_fails_to_be_rewritten_is_dropped() -> None:
    judge = Judge({MISSTATED_STATEMENT: misstated()})
    _, revise = revising()
    left_out = judge_findings(
        [finding(MISSTATED_STATEMENT, "c1")], CLAIMS, QUESTION, [], judge, revise
    )
    [outcome] = left_out.outcomes
    assert not outcome.kept
    assert outcome.reason == (
        "misstated: c1 is an agreement; it does not say supply has begun."
        " (not rewritten: the Editor's rewrite left it out)"
    )

    _, failing = revising(failure=TokenBudgetExhausted(uuid.uuid4(), 1000, 1000))
    failed = judge_findings(
        [finding(MISSTATED_STATEMENT, "c1")], CLAIMS, QUESTION, [], judge, failing
    )
    [outcome] = failed.outcomes
    assert not outcome.kept
    assert failed.revise_failure is not None


def test_a_judge_call_that_fails_leaves_the_finding_unjudged_for_review() -> None:
    call = uuid.uuid4()
    judge = Judge({SUPPORTED_STATEMENT: RoleOutputQuarantined(call, "finding_judge")})

    result = judge_findings(
        [finding(SUPPORTED_STATEMENT, "c2")], CLAIMS, QUESTION, [], judge, never
    )

    [outcome] = result.outcomes
    assert (outcome.kept, outcome.judged) == (True, None)
    [verdict] = result.judgements
    assert (verdict.verdict, verdict.outcome, verdict.role_call_id) == (
        "failed",
        "kept_unjudged",
        call,
    )
    assert result.counts["failed_first"] == 1


def test_a_finding_is_misstated_only_when_every_vote_says_so() -> None:
    from atlas.investigations.meaning import voting

    asked: list[str] = []

    def answers(*verdicts: str) -> Callable[..., tuple[FindingJudgement, uuid.UUID]]:
        queue = list(verdicts)

        def judge(request: FindingJudgeRequest, quotes: Any) -> tuple[FindingJudgement, uuid.UUID]:
            verdict = queue.pop(0)
            asked.append(verdict)
            return (
                FindingJudgement(
                    verdict=verdict,  # type: ignore[arg-type]
                    beyond=["x"] if verdict == "misstated" else [],
                    kinds=["unstated"] if verdict == "misstated" else [],
                    reason=f"vote {len(asked)}",
                ),
                uuid.uuid4(),
            )

        return judge

    request: Any = None
    # A spurious flag: the second vote supports, so the finding is supported.
    assert voting(answers("misstated", "supported"), 2)(request, [])[0].verdict == "supported"
    # Both votes misstated: misstated, with the first vote's reason for the rewrite.
    asked.clear()
    verdict = voting(answers("misstated", "misstated"), 2)(request, [])[0]
    assert (verdict.verdict, verdict.reason) == ("misstated", "vote 1")
    # A supported first vote is the answer: the second is not asked.
    asked.clear()
    assert voting(answers("supported", "misstated"), 2)(request, [])[0].verdict == "supported"
    assert asked == ["supported"]
    # One vote: the judge as it is.
    asked.clear()
    assert voting(answers("misstated"), 1)(request, [])[0].verdict == "misstated"
