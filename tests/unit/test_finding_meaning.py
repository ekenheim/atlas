"""Findings checked for meaning against their quotes (bottleneck-argument ticket 04).

Seam: `atlas.investigations.meaning.judge_findings`, with the judge and the Editor's rewrite
as the callables the Editor's task hands it (in production, role calls through LiteLLM; the
investigation's end-to-end test drives them through the scripted LiteLLM fake). The quotes
are synthetic, shaped like the pilot's; none is production text.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from atlas.investigations.grounding import CheckedFinding, date_texts
from atlas.investigations.meaning import checked, judge_findings, verify_bases
from atlas.roles.caller import RoleOutputQuarantined, TokenBudgetExhausted
from atlas.roles.contract import QuotedText
from atlas.roles.editor import (
    EDITOR_REVISE,
    CardFindingDraft,
    EditorReviseRequest,
    RevisedFinding,
    RevisedFindings,
)
from atlas.roles.finding_judge import FindingJudgement, FindingJudgeRequest, JudgedClause

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
        "available_at": datetime(2026, 5, 14, 20, 5, tzinfo=UTC),
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
        "available_at": datetime(2025, 11, 5, 21, 30, tzinfo=UTC),
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


def supported(*clauses: JudgedClause) -> FindingJudgement:
    return FindingJudgement(
        clauses=list(clauses), verdict="supported", beyond=[], kinds=[], reason="c2 states it."
    )


def clause(text: str, ref: str | None, basis: str | None) -> JudgedClause:
    return JudgedClause(text=text, ref=ref, basis=basis)


def misstated(
    reason: str = "c1 is an agreement; it does not say supply has begun.",
) -> FindingJudgement:
    return FindingJudgement(
        clauses=[clause("supplies 200G EMLs to Halcyon Networks", None, None)],
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
    assert verdict.judge == "finding_judge.v4"


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


def test_the_revise_request_carries_each_claim_s_source_date_and_the_prompt_is_v2() -> None:
    judge = Judge({MISSTATED_STATEMENT: misstated(), REWRITTEN: supported()})
    asked, revise = revising(("f1", REWRITTEN))

    judge_findings([finding(MISSTATED_STATEMENT, "c1")], CLAIMS, QUESTION, [], judge, revise)

    # The judge and the Editor's rewrite are both sent the day c1's document became available.
    assert [c.source_date for c in judge.asked[0][0].claims] == ["2026-05-14"]
    [request] = asked
    assert [c.source_date for c in request.claims] == ["2026-05-14"]
    assert (EDITOR_REVISE.prompt.name, EDITOR_REVISE.prompt.version) == ("editor-revise", 2)
    assert "source_date" in EDITOR_REVISE.prompt.text


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


def answers(*verdicts: str) -> tuple[list[str], Callable[..., tuple[FindingJudgement, uuid.UUID]]]:
    """A judge answering `verdicts` in order (no clauses), and the verdicts it was asked for."""
    queue = list(verdicts)
    asked: list[str] = []

    def judge(request: FindingJudgeRequest, quotes: Any) -> tuple[FindingJudgement, uuid.UUID]:
        verdict = queue.pop(0)
        asked.append(verdict)
        return (
            FindingJudgement(
                clauses=[],
                verdict=verdict,  # type: ignore[arg-type]
                beyond=["x"] if verdict == "misstated" else [],
                kinds=["unstated"] if verdict == "misstated" else [],
                reason=f"vote {len(asked)}",
            ),
            uuid.uuid4(),
        )

    return asked, judge


def test_under_the_all_rule_a_finding_is_misstated_only_when_every_vote_says_so() -> None:
    from atlas.investigations.meaning import voting

    request: Any = None
    # A spurious flag: the second vote supports, so the finding is supported.
    _, judge = answers("misstated", "supported")
    assert voting(judge, 2, "all")(request, [])[0].verdict == "supported"
    # Both votes misstated: misstated, with the first vote's reason for the rewrite.
    _, judge = answers("misstated", "misstated")
    verdict = voting(judge, 2, "all")(request, [])[0]
    assert (verdict.verdict, verdict.reason) == ("misstated", "vote 1")
    # A supported first vote is the answer: the second is not asked.
    asked, judge = answers("supported", "misstated")
    assert voting(judge, 2, "all")(request, [])[0].verdict == "supported"
    assert asked == ["supported"]
    # One vote: the judge as it is.
    _, judge = answers("misstated")
    assert voting(judge, 1, "all")(request, [])[0].verdict == "misstated"


def test_under_the_any_rule_every_vote_is_asked_and_one_misstated_vote_decides() -> None:
    from atlas.investigations.meaning import voting

    request: Any = None
    # Rule any: both votes asked; the misstated second vote decides, with its reason.
    asked, judge = answers("supported", "misstated")
    verdict = voting(judge, 2, "any")(request, [])[0]
    assert (verdict.verdict, verdict.reason) == ("misstated", "vote 2")
    assert asked == ["supported", "misstated"]
    # Both supported: supported, every vote asked.
    asked, judge = answers("supported", "supported")
    assert voting(judge, 2, "any")(request, [])[0].verdict == "supported"
    assert asked == ["supported", "supported"]
    # Rule all, the same votes: supported, and the second vote is not asked: it is asked only
    # after a misstated first.
    asked, judge = answers("supported", "misstated")
    assert voting(judge, 2, "all")(request, [])[0].verdict == "supported"
    assert asked == ["supported"]
    asked, judge = answers("misstated", "supported")
    assert voting(judge, 2, "all")(request, [])[0].verdict == "supported"
    assert asked == ["misstated", "supported"]

    # On the card each vote is a verdict of its own at the finding's attempt, the deciding one
    # marked; the counts are the findings'.
    _, judge = answers("supported", "misstated", "supported", "supported")
    _, revise = revising(("f1", REWRITTEN_LINE))
    result = judge_findings(
        [finding(SUPPORTED_STATEMENT, "c2")],
        CLAIMS,
        QUESTION,
        [],
        voting(judge, 2, "any"),
        revise,
    )
    assert [(j.attempt, j.vote, j.verdict, j.decided, j.outcome) for j in result.judgements] == [
        (1, 1, "supported", False, "sent_back"),
        (1, 2, "misstated", True, "sent_back"),
        (2, 1, "supported", True, "kept"),
        (2, 2, "supported", False, "kept"),
    ]
    assert result.judgements[1].reason == "vote 2"
    assert (result.counts["supported"], result.counts["misstated"]) == (0, 1)
    assert result.counts["rewritten_kept"] == 1


# --- v3: the judge's basis, clause by clause, checked by code (pilot 0.5.3) ----------------------

# The finding's statement is SUPPORTED_STATEMENT; its rewrite says less.
REWRITTEN_LINE = "Zephyr Optics says demand exceeds its supply."
LINE = "its 6-inch line in Rosemont is producing CW lasers"


def test_a_clause_whose_basis_is_not_in_its_quote_makes_the_finding_misstated() -> None:
    from atlas.investigations.meaning import verify_bases

    # The judge says supported, but its basis for the line is cited to c1, whose quote doesn't
    # hold it (and which the finding doesn't cite), and its basis for the demand is its own
    # paraphrase, not c2's words ("demand exceeds our supply").
    unverified = supported(
        clause("Zephyr Optics says", "c2", "Our"),
        clause(LINE, "c1", "6-inch line in Rosemont"),
        clause("demand outstrips its supply", "c2", "demand outstrips our supply"),
    )
    judge = Judge({SUPPORTED_STATEMENT: unverified, REWRITTEN_LINE: supported()})
    asked, revise = revising(("f1", REWRITTEN_LINE))

    result = judge_findings(
        [finding(SUPPORTED_STATEMENT, "c2")], CLAIMS, QUESTION, [], judge, revise
    )

    quotes = [QuotedText(id="c2", source="v#1-2", text=CALL)]
    assert verify_bases(unverified, quotes) == [LINE, "demand outstrips its supply"]
    first = result.judgements[0]
    assert (first.verdict, first.outcome, first.kinds) == ("misstated", "sent_back", ["unstated"])
    assert first.reason.startswith("basis unverified: ")
    assert LINE in first.reason and "demand outstrips its supply" in first.reason
    assert first.beyond == [LINE, "demand outstrips its supply"]
    assert first.unverified == [LINE, "demand outstrips its supply"]
    assert [(c.text, c.ref, c.basis) for c in first.clauses] == [
        ("Zephyr Optics says", "c2", "Our"),
        (LINE, "c1", "6-inch line in Rosemont"),
        ("demand outstrips its supply", "c2", "demand outstrips our supply"),
    ]
    # It went to the Editor's rewrite like any misstatement, with the clauses named.
    [request] = asked
    [sent] = request.findings
    assert (sent.kinds, sent.beyond) == (["unstated"], [LINE, "demand outstrips its supply"])
    assert sent.reason.startswith("basis unverified: ")
    [outcome] = result.outcomes
    assert (outcome.kept, outcome.draft.statement) == (True, REWRITTEN_LINE)

    # Verbatim bases, modulo case, whitespace, quotation marks and end punctuation: supported.
    verbatim = supported(
        clause("Zephyr Optics says", "c2", "our"),
        clause(LINE, "c2", '"our 6-inch  line in Rosemont is producing CW lasers,"'),
        clause("demand exceeds its supply", "c2", "DEMAND EXCEEDS OUR SUPPLY."),
    )
    kept = judge_findings(
        [finding(SUPPORTED_STATEMENT, "c2")],
        CLAIMS,
        QUESTION,
        [],
        Judge({SUPPORTED_STATEMENT: verbatim}),
        never,
    )
    [verdict] = kept.judgements
    assert (verdict.verdict, verdict.outcome, verdict.unverified) == ("supported", "kept", [])
    assert len(verdict.clauses) == 3
    assert kept.outcomes[0].judged is True


def test_a_vote_whose_basis_is_unverified_counts_as_misstated_under_either_rule() -> None:
    from atlas.investigations.meaning import voting

    quotes = [QuotedText(id="c2", source="v#1-2", text=CALL)]
    wrong = supported(clause("demand outstrips its supply", "c2", "demand outstrips our supply"))
    right = supported(clause("demand exceeds its supply", "c2", "demand exceeds our supply"))
    request: Any = None

    def scripted(*votes: FindingJudgement) -> Callable[..., tuple[FindingJudgement, uuid.UUID]]:
        queue = list(votes)

        def judge(*_: Any) -> tuple[FindingJudgement, uuid.UUID]:
            return queue.pop(0), uuid.uuid4()

        return judge

    for rule in ("any", "all"):
        judged = voting(scripted(wrong, wrong), 2, rule)(request, quotes)[0]
        assert judged.verdict == "misstated"
        assert judged.reason.startswith("basis unverified: ")
    judged = voting(scripted(wrong, right), 2, "all")(request, quotes)[0]
    assert judged.verdict == "supported"


# --- R3-03: a clause naming only its quote's source or date is metadata ---------------------------


def fact_metadata(company: str, title: str, day: str) -> list[str]:
    """A cited Fact's metadata as `judge_findings` builds it: its company, its source's title
    and the ways a statement names its document's date."""
    return [company, title, *date_texts(date.fromisoformat(day))]


def test_a_clause_naming_only_the_quote_s_source_or_date_needs_no_basis() -> None:
    quotes = [QuotedText(id="c2", source="v#1-2", text=CALL)]
    cases = [
        ("(Q3 2026 call)", fact_metadata("Fabrinet", "Q3 2026", "2026-05-04")),
        (
            "In its 10-Q filed August 13, 2026,",
            fact_metadata("Lumentum Holdings", "Lumentum 10-Q", "2026-08-13"),
        ),
        (
            "At the Deutsche Bank 2026 Technology Conference (August 27, 2026), Lumentum's CEO"
            " said:",
            fact_metadata(
                "Lumentum", "Lumentum at the Deutsche Bank 2026 Technology Conference", "2026-08-27"
            ),
        ),
        ("(source_date 2025-11-04)", fact_metadata("AXT", "AXT Q3 2025 call", "2025-11-04")),
    ]
    for text, metadata in cases:
        for ref, basis in ((None, None), ("c2", "a call held in a quarter")):
            vote = supported(
                clause(text, ref, basis),
                clause("demand exceeds its supply", "c2", "demand exceeds our supply"),
            )
            assert verify_bases(vote, quotes, metadata=metadata) == [], text
            assert checked(vote, quotes, metadata) == vote, text
        # Without the cited document's metadata the same clause still needs a basis.
        assert verify_bases(supported(clause(text, None, None)), quotes) == [text]

    # Through `judge_findings`, the metadata is the cited Claims' own: c1's 8-K of May 14, 2026.
    preamble = "In an 8-K filed May 14, 2026, Zephyr Optics disclosed:"
    statement = f"{preamble} an agreement with Halcyon Networks for 200G EMLs."
    vote = supported(
        clause(preamble, None, None),
        clause(
            "an agreement with Halcyon Networks for 200G EMLs",
            "c1",
            "Agreement with Halcyon Networks for 200G EMLs",
        ),
    )
    result = judge_findings(
        [finding(statement, "c1")], CLAIMS, QUESTION, [], Judge({statement: vote}), never
    )
    [verdict] = result.judgements
    assert (verdict.verdict, verdict.outcome, verdict.unverified) == ("supported", "kept", [])
    assert result.outcomes[0].kept


def test_a_clause_with_a_word_beyond_the_metadata_still_needs_a_basis() -> None:
    quotes = [QuotedText(id="c2", source="v#1-2", text=CALL)]
    metadata = fact_metadata("AXT", "AXT Q3 2026 call", "2026-10-30")
    content = "(Q3 2026 call) InP substrate prices rose"
    limitation = "The cited quote does not characterize this as a gross margin compression"
    vote = supported(clause(content, None, None), clause(limitation, None, None))

    assert verify_bases(vote, quotes, metadata=metadata) == [content, limitation]
    assert checked(vote, quotes, metadata).verdict == "misstated"


def test_a_date_or_title_of_a_document_the_finding_does_not_cite_is_not_metadata() -> None:
    quotes = [QuotedText(id="c2", source="v#1-2", text=CALL)]
    # The cited document is of May 14, 2026; the clauses date and name another one.
    metadata = fact_metadata("Lumentum", "Lumentum Q3 2026 call", "2026-05-14")
    for text in ("(August 27, 2026)", "At the Deutsche Bank Technology Conference"):
        vote = supported(clause(text, None, None))
        assert verify_bases(vote, quotes, metadata=metadata) == [text]


def test_a_rewrite_cannot_add_limitations_to_a_finding_that_had_none() -> None:
    added = ["The quote does not say supply has begun."]

    def revise(
        request: EditorReviseRequest, quotes: list[QuotedText]
    ) -> tuple[RevisedFindings, uuid.UUID]:
        return (
            RevisedFindings(
                findings=[
                    RevisedFinding(finding=each.finding, statement=REWRITTEN, limitations=added)
                    for each in request.findings
                ]
            ),
            uuid.uuid4(),
        )

    # An argument statement: drafted with no limitations, judged again with none.
    bare = CheckedFinding(
        CardFindingDraft(
            statement=MISSTATED_STATEMENT, claim_refs=["c1"], limitations=[], open_questions=[]
        ),
        ["c1"],
        [],
    )
    judge = Judge({MISSTATED_STATEMENT: misstated(), REWRITTEN: supported()})
    result = judge_findings([bare], CLAIMS, QUESTION, [], judge, revise)
    second, _ = judge.asked[1]
    assert (second.finding.statement, second.finding.limitations) == (REWRITTEN, [])
    assert result.outcomes[0].draft.limitations == []
    assert result.judgements[-1].limitations == []

    # A default-plan finding with limitations keeps the rewritten ones.
    judge = Judge({MISSTATED_STATEMENT: misstated(), REWRITTEN: supported()})
    result = judge_findings(
        [finding(MISSTATED_STATEMENT, "c1")], CLAIMS, QUESTION, [], judge, revise
    )
    second, _ = judge.asked[1]
    assert second.finding.limitations == added
    assert result.outcomes[0].draft.limitations == added
