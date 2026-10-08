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

Every verdict is recorded on the card (`ResearchCard.judged`), each vote its own.

The judge shows its basis (`finding_judge.v3`, pilot 0.5.3): the statement split into clauses,
each tied to a cited quote by that quote's own words. Code checks every basis
(`verify_bases`): a `supported` verdict with a clause whose reference isn't cited or whose
words aren't its quote's is a misstatement (`unstated`, the clauses `beyond`), rewritten like
any other. It applies to every vote, before the votes are counted (`voting`). A clause that
names only a cited quote's source or date ("(Q3 2026 call)", "In its 10-Q filed August 13,
2026,") needs no basis: the Editor is told to write it and no quote holds it (`metadata_only`,
R3-03). A rewrite cannot add limitations to a statement drafted without them.
"""

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from atlas.claims.predicates import fold
from atlas.investigations.grounding import (
    CheckedFinding,
    claim_grounds,
    date_texts,
    phrase_occurs,
    source_date_text,
    source_day,
    ungrounded,
)
from atlas.investigations.model import CardClause, CardJudgement
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


type VoteRule = Literal["any", "all"]


# The words a clause naming only a quote's source or date may use besides the cited documents'
# own metadata (their companies, titles and dates): verbs of attribution, kinds of document and
# event, the officers who speak, company suffixes and the forms' names (R3-03).
METADATA_WORDS = (
    *("says", "said", "states", "stated", "reports", "reported", "notes", "noted"),
    *("disclosed", "according", "in", "its", "the", "on", "a", "an", "at", "their", "to"),
    *("that", "also", "separately", "earlier", "later", "by", "then"),
    *("call", "conference", "filing", "filed", "transcript", "release", "results", "earnings"),
    *("quarter", "fiscal", "calendar", "year", "annual", "half"),
    *("first", "second", "third", "fourth", "with", "of", "and", "for", "from"),
    *("ceo", "cfo", "cto", "coo", "president", "chairman", "executive", "officer", "chief"),
    *("vp", "inc", "corp", "corporation", "holdings", "ltd", "plc", "co", "company"),
    *("10-k", "10-q", "8-k", "20-f", "6-k"),
)
_METADATA_WORDS = frozenset(METADATA_WORDS)
_MONTH_NAMES = (
    *("january", "february", "march", "april", "may", "june", "july", "august"),
    *("september", "october", "november", "december"),
)
# A month's name, or its three- or four-letter abbreviation, as the month's full name.
_MONTH = {
    **{name[:3]: name for name in _MONTH_NAMES},
    **{name[:4]: name for name in _MONTH_NAMES},
    **{name: name for name in _MONTH_NAMES},
}
_PERIOD = re.compile(r"(?:fy|cy)(?:\d{2}|\d{4})?|q[1-4]|h[12]")
_DAY = re.compile(r"((?:[1-9]|[12]\d|3[01]))(?:st|nd|rd|th)?")


def _metadata_tokens(text: str) -> list[str]:
    """`text`'s words as a metadata clause is read: folded, lower case, a trailing `'s`
    dropped, runs of letters, digits, `-` and `.` (and `_`, for `source_date`) with the
    punctuation at their ends dropped, a month's abbreviation as its full name and a day
    number without its `st`/`nd`/`rd`/`th`."""
    flat = re.sub(r"'s\b", "", fold(text).lower())
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9_][a-z0-9_.\-]*", flat):
        word = word.strip(".-")
        if not word:
            continue
        day = _DAY.fullmatch(word)
        if day is not None:
            word = day.group(1)
        tokens.append(_MONTH.get(word) or word)
    return tokens


def metadata_only(text: str, metadata: Sequence[str]) -> bool:
    """Whether a judge's clause names only a cited quote's source or date, so needs no basis
    (R3-03): every word of it is a word of the cited documents' `metadata` (their companies,
    titles and dates, as `date_texts` writes them), `source_date`, a fiscal or quarter period
    (`fy`, `q3`, `h1`, `fy2026`) or one of `METADATA_WORDS`. A month, day, year or ISO date
    is not a word of its own: it must be a cited document's (the date of a document the
    finding does not cite is a claim, which its quotes must hold). An empty clause names
    nothing beyond them."""
    allowed = {token for each in metadata for token in _metadata_tokens(each)}
    return all(
        word in allowed
        or word in _METADATA_WORDS
        or word == "source_date"
        or _PERIOD.fullmatch(word) is not None
        for word in _metadata_tokens(text)
    )


def verify_bases(
    judgement: FindingJudgement, quotes: Sequence[QuotedText], *, metadata: Sequence[str] = ()
) -> list[str]:
    """The judge's clauses whose basis code can't verify, as it wrote them, in order: a clause
    whose `ref` is not one of the cited quotes' (`quotes`, by `id`), or whose `basis` does not
    occur in that quote (folded, lower case, whitespace single, quotation marks and end
    punctuation dropped: `atlas.investigations.grounding.phrase_occurs`). A clause with no
    reference or basis (one the judge says goes beyond the quotes) is among them, unless it
    names only a cited quote's source or date (`metadata_only`, `metadata` the cited
    documents' companies, titles and dates): the Editor is told to name them, and no quote
    holds them (R3-03)."""
    texts = {quote.id: quote.text for quote in quotes}
    return [
        clause.text
        for clause in judgement.clauses
        if (
            clause.ref is None
            or clause.ref not in texts
            or clause.basis is None
            or not phrase_occurs(clause.basis, texts[clause.ref])
        )
        and not metadata_only(clause.text, metadata)
    ]


def finding_metadata(refs: Sequence[str], claims: Mapping[str, Mapping[Any, Any]]) -> list[str]:
    """The metadata of the documents a finding cites, for `verify_bases`: each cited Claim's
    or Fact's subject, source title and the ways a statement names its document's date
    (`atlas.investigations.grounding.date_texts`)."""
    texts: list[str] = []
    for ref in refs:
        claim = claims[ref]
        texts.extend(str(claim[key]) for key in ("subject_name", "source_title") if claim.get(key))
        day = source_day(claim)
        if day is not None:
            texts.extend(date_texts(day))
    return texts


def checked(
    judgement: FindingJudgement, quotes: Sequence[QuotedText], metadata: Sequence[str] = ()
) -> FindingJudgement:
    """`judgement` with its bases checked: a `supported` verdict with an unverified clause is
    `misstated` (`unstated`, the clauses `beyond`, the reason naming them); any other is as
    the judge gave it. A clause naming only a cited document's source or date (`metadata`)
    needs no basis."""
    if judgement.verdict != "supported":
        return judgement
    unverified = verify_bases(judgement, quotes, metadata=metadata)
    if not unverified:
        return judgement
    named = "; ".join(f'"{text}"' for text in unverified)
    return judgement.model_copy(
        update={
            "verdict": "misstated",
            "beyond": unverified,
            "kinds": ["unstated"],
            "reason": (
                f"basis unverified: {named}: no cited quote holds the words the judge gave as"
                f" the basis of each (the judge's reason: {judgement.reason})"
            ),
        }
    )


@dataclass(frozen=True)
class Ballot:
    """What the judge answered about one statement: every vote asked, in order, each with its
    bases checked, and which one decides."""

    votes: list[tuple[FindingJudgement, uuid.UUID]]
    decided: int


class Voting:
    """A judge asked up to `votes` times about each statement, decided by `rule` (see
    `voting`). Called, it answers the deciding vote; `ballot` gives every vote."""

    def __init__(self, judge: Judge, votes: int, rule: VoteRule) -> None:
        self.judge = judge
        self.votes = max(1, votes)
        self.rule: VoteRule = rule

    def ballot(
        self,
        request: FindingJudgeRequest,
        quotes: list[QuotedText],
        metadata: Sequence[str] = (),
    ) -> Ballot:
        asked: list[tuple[FindingJudgement, uuid.UUID]] = []
        for _ in range(self.votes):
            judgement, role_call_id = self.judge(request, quotes)
            asked.append((checked(judgement, quotes, metadata), role_call_id))
            if self.rule == "all" and asked[-1][0].verdict == "supported":
                break
        wanted = "misstated" if self.rule == "any" else "supported"
        decided = next((i for i, (each, _) in enumerate(asked) if each.verdict == wanted), 0)
        return Ballot(asked, decided)

    def __call__(
        self,
        request: FindingJudgeRequest,
        quotes: list[QuotedText],
        metadata: Sequence[str] = (),
    ) -> tuple[FindingJudgement, uuid.UUID]:
        ballot = self.ballot(request, quotes, metadata)
        return ballot.votes[ballot.decided]


def voting(judge: Judge, votes: int, rule: VoteRule) -> Voting:
    """`judge` asked up to `votes` times about a statement, each vote's bases checked
    (`checked`), decided by `rule`:

    - `any` (the setting's default, `ATLAS_FINDING_JUDGE_VOTE_RULE`): every vote is asked, and
      the statement is misstated when any vote says so (the first misstated vote, with its
      reason for the rewrite); else supported. On pilot 0.5.3's 130 statements the judge
      missed 17 of 17 misstatements: a second look that can only add a flag is the cheaper
      error.
    - `all`: misstated only when every vote says so. The first supported vote is the answer
      (later votes are not asked); if none, the first misstated vote. Measured on the 18
      labelled 0.4.6 findings with two votes: 8 of 9 misstatements caught, 1 of 9 supported
      flagged; the judge then erred on the strict side at random.

    (docs/decisions.md, "Findings checked for meaning")"""
    return Voting(judge, votes, rule)


def _ballot(
    judge: Judge,
    request: FindingJudgeRequest,
    quotes: list[QuotedText],
    metadata: Sequence[str] = (),
) -> Ballot:
    if isinstance(judge, Voting):
        return judge.ballot(request, quotes, metadata)
    judgement, role_call_id = judge(request, quotes)
    return Ballot([(checked(judgement, quotes, metadata), role_call_id)], 0)


# What the card says of the trust gate when the judge ran (beside `GROUNDING_LIMIT`).
JUDGE_LIMIT = (
    " Each finding that passed was then compared with its quotes by a judge model for tense"
    " and status, direction, figures and dates, attribution and merged facts, clause by"
    " clause, each clause tied to the quote words that state it, and code checked that every"
    " such basis occurs in its quote (the card's `judged`, every vote; a clause naming only a"
    " cited quote's source or date needs no basis); a misstated finding,"
    " or one with a clause whose basis code could not find, was rewritten once and dropped if"
    " still misstated. The judge is a model: a finding it passed can still be wrong."
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


def judged_claim(ref: str, claim: Mapping[Any, Any]) -> JudgedClaim:
    """A cited Claim as the judge is sent it (a Fact's reading is the argument plan's, added
    by `atlas.investigations.tasks`)."""
    return JudgedClaim(
        ref=ref,
        subject=claim["subject_name"],
        predicate=claim["predicate"],
        object=_object(claim),
        epistemic_type=claim["epistemic_type"],
        source_title=claim["source_title"],
        source_date=source_date_text(claim),
    )


def judge_findings(
    findings: Sequence[CheckedFinding],
    claims: Mapping[str, Mapping[Any, Any]],
    question: str,
    aliases: Sequence[Sequence[str]],
    judge: Judge,
    revise: Revise,
    describe: Callable[[str, Mapping[Any, Any]], JudgedClaim] = judged_claim,
) -> JudgedFindings:
    """Judge each of `findings` (grounded ones: their drafts and cited references, each a key
    of `claims`, described to the judge by `describe`), have the misstated ones rewritten
    once, and judge the rewrites (see the module). Every vote of a `Voting` judge is
    recorded."""
    judgements: list[CardJudgement] = []
    keys = [f"f{index + 1}" for index in range(len(findings))]

    def ask(
        draft: CardFindingDraft, cited: list[str]
    ) -> tuple[FindingJudgement | None, uuid.UUID | None, str | None, Ballot | None]:
        request = FindingJudgeRequest(
            research_question=question,
            finding=JudgedFinding(
                statement=draft.statement, limitations=draft.limitations, claim_refs=cited
            ),
            claims=[describe(ref, claims[ref]) for ref in cited],
        )
        try:
            ballot = _ballot(
                judge, request, _quotes(cited, claims), finding_metadata(cited, claims)
            )
        except RoleOutputQuarantined as failure:
            return None, failure.role_call_id, str(failure), None
        except TokenBudgetExhausted as failure:
            return None, None, str(failure), None
        verdict, role_call_id = ballot.votes[ballot.decided]
        return verdict, role_call_id, None, ballot

    def record(
        key: str,
        attempt: Literal[1, 2],
        draft: CardFindingDraft,
        cited: list[str],
        answer: tuple[FindingJudgement | None, uuid.UUID | None, str | None, Ballot | None],
        outcome: Literal["kept", "sent_back", "dropped", "kept_unjudged"],
    ) -> None:
        _, role_call_id, failure, ballot = answer
        claim_ids = [claims[ref]["id"] for ref in cited]
        if ballot is None:
            judgements.append(
                CardJudgement(
                    finding=key,
                    attempt=attempt,
                    statement=draft.statement,
                    limitations=draft.limitations,
                    claim_ids=claim_ids,
                    verdict="failed",
                    beyond=[],
                    kinds=[],
                    reason=str(failure),
                    outcome=outcome,
                    role_call_id=role_call_id,
                    judge=FINDING_JUDGE_VERSION,
                )
            )
            return
        quotes = _quotes(cited, claims)
        metadata = finding_metadata(cited, claims)
        for index, (verdict, vote_call_id) in enumerate(ballot.votes):
            judgements.append(
                CardJudgement(
                    finding=key,
                    attempt=attempt,
                    statement=draft.statement,
                    limitations=draft.limitations,
                    claim_ids=claim_ids,
                    verdict=verdict.verdict,
                    beyond=verdict.beyond,
                    kinds=list(verdict.kinds),
                    reason=verdict.reason,
                    outcome=outcome,
                    role_call_id=vote_call_id,
                    judge=FINDING_JUDGE_VERSION,
                    vote=index + 1,
                    decided=index == ballot.decided,
                    clauses=[
                        CardClause(text=each.text, ref=each.ref, basis=each.basis)
                        for each in verdict.clauses
                    ],
                    unverified=verify_bases(verdict, quotes, metadata=metadata),
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
                    source_date=source_date_text(claims[ref]),
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
        # A rewrite cannot add limitations: a statement drafted without (the argument plan's;
        # its card never shows them) is judged again without; the default plan's keep theirs.
        if not findings[index].draft.limitations:
            limitations = []
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
    decided = [j for j in judgements if j.decided]  # one per finding and attempt
    counts = {
        "judged": len(findings),
        "supported": sum(1 for j in decided if j.attempt == 1 and j.verdict == "supported"),
        "misstated": len(misstated),
        "failed": sum(1 for j in decided if j.verdict == "failed"),
        "failed_first": sum(1 for j in decided if j.attempt == 1 and j.verdict == "failed"),
        "rewritten_kept": sum(1 for j in decided if j.attempt == 2 and j.outcome == "kept"),
        "dropped": sum(1 for each in done if not each.kept),
    }
    return JudgedFindings(done, judgements, revise_call, revise_failure, counts)
