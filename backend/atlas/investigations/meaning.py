"""A finding is checked for meaning against its quotes (bottleneck-argument ticket 04).

The trust gate has two halves. The first is code's: every quote verbatim at its archived span
(the Assertions), and every name, figure and quoted phrase of a finding found in the Claims it
cites (`atlas.investigations.grounding`). The second is the finding judge's
(`atlas.roles.finding_judge`): what the sentence does with them (tense and status, direction,
figures and dates as quoted, two facts merged into one). The grounding check runs first; only
a grounded finding is judged.

The flow, per research card:
1. Each grounded finding is judged, one call each, with its statement, its limitations and
   its cited Claims' exact quotes. `supported`: kept.
2. Every `misstated` finding goes back to the Editor in one call (`EDITOR_REVISE`), with the
   judge's words and reason; each rewrite is grounding-checked like the first statement, then
   judged again. `supported`: kept (rewritten). Anything else (still misstated, ungrounded,
   left out of the Editor's answer, the rewrite or its judging failed): dropped, kept on the
   card under `unsupported_findings` with the reason.
3. A judge call that fails on a first statement (quarantined, cut off, or the run's token
   budget spent) leaves the finding on the card unjudged (`judged` None), and the card needs
   review: the judge's failure is not the finding's.

Every verdict is recorded on the card (`ResearchCard.judged`).
"""

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from atlas.investigations.grounding import CheckedFinding, claim_grounds, ungrounded
from atlas.investigations.model import CardJudgement
from atlas.roles.caller import RoleOutputQuarantined, TokenBudgetExhausted
from atlas.roles.contract import QuotedText
from atlas.roles.editor import (
    CardFindingDraft,
    EditorCardClaim,
    EditorMisstatedFinding,
    EditorReviseRequest,
    RevisedFindings,
)
from atlas.roles.finding_judge import (
    FINDING_JUDGE_VERSION,
    FindingJudgement,
    FindingJudgeRequest,
    JudgedClaim,
    JudgedFinding,
)

type Judge = Callable[[FindingJudgeRequest, list[QuotedText]], tuple[FindingJudgement, uuid.UUID]]
type Revise = Callable[[EditorReviseRequest, list[QuotedText]], tuple[RevisedFindings, uuid.UUID]]

# What the card says of the trust gate when the judge ran (beside `GROUNDING_LIMIT`).
JUDGE_LIMIT = (
    " Each finding that passed was then compared with its quotes by a judge model for tense"
    " and status, direction, figures and dates, and merged facts (the card's `judged`); a"
    " misstated finding was rewritten once and dropped if still misstated. The judge is a"
    " model: a finding it passed can still be wrong."
)


@dataclass(frozen=True)
class JudgedOutcome:
    """What came of one grounded finding."""

    draft: CardFindingDraft  # the statement and limitations kept (rewritten, if it was)
    cited: list[str]  # its Claims' references
    kept: bool
    judged: bool | None  # True: supported; None: kept unjudged (its judge call failed)
    reason: str | None  # why it was dropped


@dataclass(frozen=True)
class JudgedFindings:
    outcomes: list[JudgedOutcome]  # in the findings' order
    judgements: list[CardJudgement]  # every verdict, in order
    revise_role_call_id: uuid.UUID | None
    revise_failure: str | None
    counts: dict[str, int] = field(default_factory=dict[str, int])


def _quotes(refs: Sequence[str], claims: Mapping[str, Mapping[Any, Any]]) -> list[QuotedText]:
    return [
        QuotedText(
            id=ref,
            source=(
                f"{claims[ref]['source_version_id']}"
                f"#{claims[ref]['span_start']}-{claims[ref]['span_end']}"
            ),
            text=claims[ref]["quote"],
        )
        for ref in refs
    ]


def _object(claim: Mapping[Any, Any]) -> str:
    return claim["object_name"] or claim["object_text"] or ""


def judge_findings(
    findings: Sequence[CheckedFinding],
    claims: Mapping[str, Mapping[Any, Any]],
    question: str,
    aliases: Sequence[Sequence[str]],
    judge: Judge,
    revise: Revise,
) -> JudgedFindings:
    """Judge each of `findings` (grounded ones: their drafts and cited references, each a key
    of `claims`), have the misstated ones rewritten once, and judge the rewrites (see the
    module)."""
    judgements: list[CardJudgement] = []
    keys = [f"f{index + 1}" for index in range(len(findings))]

    def ask(
        draft: CardFindingDraft, cited: list[str]
    ) -> tuple[FindingJudgement | None, uuid.UUID | None, str | None]:
        request = FindingJudgeRequest(
            research_question=question,
            finding=JudgedFinding(
                statement=draft.statement, limitations=draft.limitations, claim_refs=cited
            ),
            claims=[
                JudgedClaim(
                    ref=ref,
                    subject=claims[ref]["subject_name"],
                    predicate=claims[ref]["predicate"],
                    object=_object(claims[ref]),
                    epistemic_type=claims[ref]["epistemic_type"],
                    source_title=claims[ref]["source_title"],
                )
                for ref in cited
            ],
        )
        try:
            verdict, role_call_id = judge(request, _quotes(cited, claims))
        except RoleOutputQuarantined as failure:
            return None, failure.role_call_id, str(failure)
        except TokenBudgetExhausted as failure:
            return None, None, str(failure)
        return verdict, role_call_id, None

    def record(
        key: str,
        attempt: Literal[1, 2],
        draft: CardFindingDraft,
        cited: list[str],
        answer: tuple[FindingJudgement | None, uuid.UUID | None, str | None],
        outcome: Literal["kept", "sent_back", "dropped", "kept_unjudged"],
    ) -> None:
        verdict, role_call_id, failure = answer
        judgements.append(
            CardJudgement(
                finding=key,
                attempt=attempt,
                statement=draft.statement,
                limitations=draft.limitations,
                claim_ids=[claims[ref]["id"] for ref in cited],
                verdict=verdict.verdict if verdict is not None else "failed",
                beyond=verdict.beyond if verdict is not None else [],
                kinds=list(verdict.kinds) if verdict is not None else [],
                reason=verdict.reason if verdict is not None else str(failure),
                outcome=outcome,
                role_call_id=role_call_id,
                judge=FINDING_JUDGE_VERSION,
            )
        )

    outcomes: list[JudgedOutcome | None] = [None] * len(findings)
    misstated: dict[str, tuple[int, FindingJudgement]] = {}
    for index, (key, each) in enumerate(zip(keys, findings, strict=True)):
        answer = ask(each.draft, each.cited)
        verdict = answer[0]
        if verdict is None:
            record(key, 1, each.draft, each.cited, answer, "kept_unjudged")
            outcomes[index] = JudgedOutcome(each.draft, each.cited, True, None, None)
        elif verdict.verdict == "supported":
            record(key, 1, each.draft, each.cited, answer, "kept")
            outcomes[index] = JudgedOutcome(each.draft, each.cited, True, True, None)
        else:
            record(key, 1, each.draft, each.cited, answer, "sent_back")
            misstated[key] = (index, verdict)

    revise_call: uuid.UUID | None = None
    revise_failure: str | None = None
    revised: dict[str, tuple[str, list[str]]] = {}
    if misstated:
        refs = list(
            dict.fromkeys(ref for index, _ in misstated.values() for ref in findings[index].cited)
        )
        request = EditorReviseRequest(
            research_question=question,
            findings=[
                EditorMisstatedFinding(
                    finding=key,
                    statement=findings[index].draft.statement,
                    limitations=findings[index].draft.limitations,
                    claim_refs=findings[index].cited,
                    beyond=verdict.beyond,
                    kinds=list(verdict.kinds),
                    reason=verdict.reason,
                )
                for key, (index, verdict) in misstated.items()
            ],
            claims=[
                EditorCardClaim(
                    ref=ref,
                    subject=claims[ref]["subject_name"],
                    predicate=claims[ref]["predicate"],
                    object=_object(claims[ref]),
                    product=claims[ref]["product"],
                    layer=claims[ref]["layer"],
                    epistemic_type=claims[ref]["epistemic_type"],
                    source_title=claims[ref]["source_title"],
                    source_version_id=str(claims[ref]["source_version_id"]),
                )
                for ref in refs
            ],
        )
        try:
            answer, revise_call = revise(request, _quotes(refs, claims))
        except RoleOutputQuarantined as failure:
            revise_call, revise_failure = failure.role_call_id, str(failure)
        except TokenBudgetExhausted as failure:
            revise_failure = str(failure)
        else:
            for each in answer.findings:
                if each.finding in misstated and each.finding not in revised:
                    revised[each.finding] = (each.statement, each.limitations)

    for key, (index, first) in misstated.items():
        cited = findings[index].cited
        dropped = f"misstated: {first.reason}"
        if key not in revised:
            why = revise_failure or "the Editor's rewrite left it out"
            outcomes[index] = JudgedOutcome(
                findings[index].draft, cited, False, None, f"{dropped} (not rewritten: {why})"
            )
            continue
        statement, limitations = revised[key]
        draft = findings[index].draft.model_copy(
            update={"statement": statement, "limitations": limitations}
        )
        terms = ungrounded(
            statement, claim_grounds(question, [claims[ref] for ref in cited], aliases)
        )
        if terms:
            outcomes[index] = JudgedOutcome(
                draft,
                cited,
                False,
                None,
                f"{dropped}; rewritten, then ungrounded: " + ", ".join(terms),
            )
            continue
        second = ask(draft, cited)
        verdict = second[0]
        if verdict is not None and verdict.verdict == "supported":
            record(key, 2, draft, cited, second, "kept")
            outcomes[index] = JudgedOutcome(draft, cited, True, True, None)
            continue
        record(key, 2, draft, cited, second, "dropped")
        if verdict is None:
            reason = f"{dropped}; the rewrite could not be judged: {second[2]}"
        else:
            reason = f"misstated after a rewrite: {verdict.reason}"
        outcomes[index] = JudgedOutcome(draft, cited, False, None, reason)

    done = [each for each in outcomes if each is not None]
    counts = {
        "judged": len(findings),
        "supported": sum(1 for j in judgements if j.attempt == 1 and j.verdict == "supported"),
        "misstated": len(misstated),
        "failed": sum(1 for j in judgements if j.verdict == "failed"),
        "failed_first": sum(1 for j in judgements if j.attempt == 1 and j.verdict == "failed"),
        "rewritten_kept": sum(1 for j in judgements if j.attempt == 2 and j.outcome == "kept"),
        "dropped": sum(1 for each in done if not each.kept),
    }
    return JudgedFindings(done, judgements, revise_call, revise_failure, counts)
