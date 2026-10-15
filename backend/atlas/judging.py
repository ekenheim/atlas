"""A statement judged where it is written down (atlas-beliefs ticket 23).

The MCP session of 2026-10-15 kept the trust gate at 4% and left Fact precision at 92%: the
three wrong Facts had a clause from the context in their statement, six of eleven Beliefs were
compound, and the thesis sentence, never judged, misstated a tense. Rules in the skill reduce
these errors; the judge stops them where it is applied. Three places call it, over the one
judge `POST /statements/judge` asks (`finding_judge.v4` on the role's model, the votes and the
vote rule of the settings, every basis checked by code, `atlas.investigations.meaning`):

- a Fact recorded in a research session is judged against its own quote, the source title and
  the document's date (`statement_beyond_quote` when misstated; recorded with its verdict when
  supported; recorded and marked `unjudged` when the judge cannot be reached: a judge's
  failure is not the Fact's);
- a session's card thesis is judged against the Facts the card's statements cite when the
  session closes (the verdict goes on the card; a misstated thesis is flagged, not refused);
- a session's Belief is judged against its load-bearing positive Facts' quotes and held to one
  claim, one period and one actor (`atlas.beliefs.atomicity`) when proposed.

`ATLAS_FACT_STATEMENT_JUDGE` (`sessions` by default, `always`, `off`) says where: `sessions`
for a research session's Facts, thesis and Beliefs; `always` also for a Fact recorded without
a session (the pipeline's Readers among them); `off` for none.

The calls are recorded under a run of their own, as `/statements/judge` records its calls.
"""

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx2
from sqlalchemy import Connection, Engine, text

from atlas.facts.service import FactCreate, FactJudgement, FactValue
from atlas.hindsight import HindsightError
from atlas.investigations.meaning import finding_metadata, verify_bases, voting
from atlas.jobs.pacing import TransientFailure
from atlas.llm_routes import LiteLLMError
from atlas.roles import QuotedText
from atlas.roles.caller import RoleCaller, RoleCallFailed, TokenBudgetExhausted
from atlas.roles.finding_judge import (
    FINDING_JUDGE,
    FINDING_JUDGE_VERSION,
    FindingJudgeRequest,
    JudgedFinding,
)
from atlas.runs import RunNotStartable, RunRecorder
from atlas.settings import Settings

# The longest list of Facts a thesis is judged against (its statements' Facts, in card order).
MAX_THESIS_FACTS = 12  # the route's cap on `fact_ids`: a longer card is judged on its first 12


class JudgeUnavailable(Exception):
    """The judge could not give a verdict (LiteLLM or Hindsight not configured or down, a quota,
    a quarantined or cut-off answer, a spent token budget). `reason` says which; the Fact is
    recorded unjudged, the thesis is marked so, a Belief waits."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Verdict:
    """What the judge decided about one statement (the deciding vote's, bases checked)."""

    verdict: Literal["supported", "misstated"]
    reason: str
    beyond: list[str]
    kinds: list[str]
    unverified: list[str]  # the clauses whose basis code could not find in the cited quote
    judge: str
    run_id: uuid.UUID
    role_call_id: uuid.UUID

    @property
    def supported(self) -> bool:
        return self.verdict == "supported"

    def detail(self) -> dict[str, Any]:
        """What a refusal tells the agent beside its message."""
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "beyond": self.beyond,
            "kinds": self.kinds,
            "unverified": self.unverified,
            "judge": self.judge,
            "run_id": str(self.run_id),
        }


class Judges:
    """The judge for the places a statement is written down, over the settings' LiteLLM."""

    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings

    @property
    def mode(self) -> Literal["sessions", "always", "off"]:
        return self._settings.fact_statement_judge

    def judges_fact(self, session_id: uuid.UUID | None) -> bool:
        """Whether a Fact recorded in `session_id` (or none) is judged."""
        return self.mode == "always" or (self.mode == "sessions" and session_id is not None)

    def judges_session(self) -> bool:
        """Whether a session's thesis and Beliefs are judged."""
        return self.mode != "off"

    def judges_belief(self, session_id: uuid.UUID | None) -> bool:
        return self.judges_fact(session_id)

    def _caller_and_run(self, kind: str) -> tuple[RoleCaller, uuid.UUID]:
        caller = RoleCaller.from_settings(self._settings, self._engine)
        if caller is None:
            raise JudgeUnavailable(
                "litellm_not_configured: judging needs ATLAS_LITELLM_URL and ATLAS_LITELLM_API_KEY"
            )
        recorder = RunRecorder.from_settings(self._settings, self._engine)
        if recorder is None:
            caller.close()
            raise JudgeUnavailable(
                "run_not_recordable: a judge's run needs Hindsight and LiteLLM configured"
            )
        try:
            return caller, recorder.start(kind).id
        except (RunNotStartable, HindsightError, LiteLLMError, httpx2.HTTPError) as error:
            caller.close()
            raise JudgeUnavailable(f"run_not_recordable: {error}") from error
        finally:
            recorder.close()

    def judge(
        self, kind: str, *, question: str, statement: str, rows: Sequence[Mapping[Any, Any]]
    ) -> Verdict:
        """`statement` judged against the Facts `rows` (the shape of
        `atlas.investigations.argument.fact_rows`), in a run of the given `kind`. Raises
        `JudgeUnavailable` when no verdict could be given."""
        caller, run_id = self._caller_and_run(kind)
        with caller:
            return judged_in_run(
                caller, run_id, self._settings, question=question, statement=statement, rows=rows
            )

    def fact_judge(self, question: str) -> "FactJudge":
        """The judge of a Fact's statement (`judge_fact`), each judgement in a run of its own."""
        return lambda statement, rows: self.judge(
            "fact_judge", question=question, statement=statement, rows=rows
        )


def judged_in_run(
    caller: RoleCaller,
    run_id: uuid.UUID,
    settings: Settings,
    *,
    question: str,
    statement: str,
    rows: Sequence[Mapping[Any, Any]],
) -> Verdict:
    """`judge_statement` with the settings' votes and rule, a failure of the judge as
    `JudgeUnavailable`: for a caller that holds a caller and a run already (a Reader)."""
    try:
        return judge_statement(
            caller,
            run_id,
            question=question,
            statement=statement,
            rows=rows,
            votes=settings.fact_statement_judge_votes,
            rule=settings.finding_judge_vote_rule,
        )
    except TransientFailure as error:
        raise JudgeUnavailable(
            f"role_unavailable: {error.failure_class}: {error}; call again later"
        ) from error
    except TokenBudgetExhausted as error:
        raise JudgeUnavailable(f"token_budget_exhausted: {error}") from error
    except RoleCallFailed as error:
        raise JudgeUnavailable(f"judge_failed: {error}") from error


type FactJudge = Callable[[str, Sequence[Mapping[Any, Any]]], Verdict]
"""(statement, the Fact's row) -> the verdict, or `JudgeUnavailable`."""


def judge_fact(
    connection: Connection, request: FactCreate, value: FactValue, judge: FactJudge
) -> tuple[FactJudgement, Verdict | None]:
    """The judge's word on a Fact that passed every other check (`Facts.check`): the
    `FactJudgement` to record it with and, when the statement says more than the quote, the
    misstated verdict that refuses it. A judge that cannot be reached gives an `unjudged`
    judgement (never a refusal)."""
    row = unrecorded_fact_row(
        connection,
        company_id=request.subject_company_id,
        source_version_id=request.source_version_id,
        quote=request.quote,
        span_start=request.span_start,
        span_end=request.span_end,
        epistemic_type=request.epistemic_type,
        value=value.model_dump(mode="json", exclude_none=True),
    )
    if row is None:  # the Fact's own checks refuse an unknown company or version
        return FactJudgement(verdict="unjudged", reason="the Fact's document is unknown"), None
    try:
        verdict = judge(request.statement, [row])
    except JudgeUnavailable as unavailable:
        return FactJudgement(verdict="unjudged", reason=unavailable.reason), None
    judgement = FactJudgement(
        verdict="supported",
        judge=verdict.judge,
        reason=verdict.reason,
        run_id=verdict.run_id,
        role_call_id=verdict.role_call_id,
    )
    return judgement, None if verdict.supported else verdict


def run_fact_judge(
    caller: RoleCaller, run_id: uuid.UUID, settings: Settings, question: str
) -> FactJudge | None:
    """The judge of a Fact's statement for a caller that holds a caller and a run (a Reader),
    in that run; None unless `ATLAS_FACT_STATEMENT_JUDGE` is `always`: the pipeline's Readers
    are not judged by default."""
    if settings.fact_statement_judge != "always":
        return None
    return lambda statement, rows: judged_in_run(
        caller, run_id, settings, question=question, statement=statement, rows=rows
    )


def fact_question(connection: Connection, request: FactCreate) -> str:
    """The question a Fact is recorded for: its session's, else its investigation's."""
    for table, key in (
        ("research_session", request.session_id),
        ("investigation", request.investigation_id),
    ):
        if key is None:
            continue
        found = connection.execute(
            text(f"SELECT question FROM {table} WHERE id = :id"),  # noqa: S608 (constants)
            {"id": key},
        ).scalar()
        if found:
            return str(found)
    return ""


def fact_refusal(verdict: Verdict) -> tuple[str, str]:
    """The code and message of the refusal of a Fact whose statement the judge found misstated."""
    beyond = "; ".join(f'"{each}"' for each in verdict.beyond) or verdict.reason
    return (
        "statement_beyond_quote",
        f"the statement says more than its quote: {beyond} ({verdict.reason}). Rewrite it to"
        " what the quote says, or take a longer quote that carries it.",
    )


def judge_statement(
    caller: RoleCaller,
    run_id: uuid.UUID,
    *,
    question: str,
    statement: str,
    rows: Sequence[Mapping[Any, Any]],
    votes: int,
    rule: Literal["any", "all"],
) -> Verdict:
    """The finding judge's verdict on `statement` over the Facts `rows`, as
    `POST /statements/judge` asks it (same request, same bases check, same vote rule). The
    caller's failures (`TransientFailure`, `RoleCallFailed`, `TokenBudgetExhausted`) propagate."""
    # Imported here: the tasks module imports the Reader, which may call this module.
    from atlas.investigations.tasks import _judged_fact  # pyright: ignore[reportPrivateUsage]

    claims = {f"c{index}": row for index, row in enumerate(rows, start=1)}
    cited = list(claims)
    metadata = finding_metadata(cited, claims)
    request = FindingJudgeRequest(
        research_question=question,
        finding=JudgedFinding(statement=statement, limitations=[], claim_refs=cited),
        claims=[_judged_fact(ref, row) for ref, row in claims.items()],
    )
    quotes = [
        QuotedText(
            id=ref,
            source=f"{row['source_version_id']}#{row['span_start']}-{row['span_end']}",
            text=row["quote"],
        )
        for ref, row in claims.items()
    ]
    ballot = voting(
        lambda asked, sent: caller.call_recorded(
            FINDING_JUDGE, asked, run_id=run_id, retrieved=sent
        ),
        votes,
        rule,
    ).ballot(request, quotes, metadata)
    decided, role_call_id = ballot.votes[ballot.decided]
    return Verdict(
        verdict=decided.verdict,
        reason=decided.reason,
        beyond=list(decided.beyond),
        kinds=list(decided.kinds),
        unverified=verify_bases(decided, quotes, metadata=metadata),
        judge=FINDING_JUDGE_VERSION,
        run_id=run_id,
        role_call_id=role_call_id,
    )


_FACT_CONTEXT = (
    "SELECT c.display_name AS subject_name, coalesce(d.title, d.canonical_url) AS source_title,"
    " a.available_at FROM company c, source_version v"
    " JOIN source_document d ON d.id = v.source_document_id"
    " JOIN source_version_availability a ON a.source_version_id = v.id"
    " WHERE c.id = :company AND v.id = :version"
)


def unrecorded_fact_row(
    connection: Connection,
    *,
    company_id: uuid.UUID,
    source_version_id: uuid.UUID,
    quote: str,
    span_start: int,
    span_end: int,
    epistemic_type: str,
    value: Mapping[str, Any],
) -> dict[str, Any] | None:
    """A Fact not yet recorded, shaped like `fact_rows`' rows for the judge: its subject's name,
    its document's title and date, its quote and span and the value (statement, status, period,
    quantity, resolved period) it would record. None for an unknown company or version (the
    Fact's own checks refuse those)."""
    context = (
        connection.execute(
            text(_FACT_CONTEXT), {"company": company_id, "version": source_version_id}
        )
        .mappings()
        .one_or_none()
    )
    if context is None:
        return None
    return {
        "id": None,
        "subject_name": context["subject_name"],
        "source_title": context["source_title"],
        "available_at": context["available_at"],
        "object_name": None,
        "object_text": None,
        "predicate": "fact",
        "epistemic_type": epistemic_type,
        "value_json": {**value, "statement": None},  # the reading is the statement judged
        "quote": quote,
        "source_version_id": source_version_id,
        "span_start": span_start,
        "span_end": span_end,
    }
