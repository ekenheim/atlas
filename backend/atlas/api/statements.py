"""`/api/v1/statements`: a session's statements judged before they are written down (beliefs
ticket 07).

The proof sessions' one weak measure was the trust gate: 8% and 29% of their statements said
more than their cited quotes, because no judge was applied. These routes put the pipeline's
own judges in front of a session, over the existing role machinery (no new prompt):

- `POST /statements/judge` (`{question, statement, fact_ids, counter_fact_ids?, votes?,
  run_id?}`): the finding judge (`finding_judge.v4`, on the role's model from
  `ATLAS_LLM_ROLE_MODELS`) is asked about the statement with the cited Facts' quotes, dates,
  status and period, exactly as the argument Editor's task asks it; `votes` (default 1) are
  decided by `ATLAS_FINDING_JUDGE_VOTE_RULE`; every basis is checked by code, so a `supported`
  answer with a basis no quote holds is `misstated`. Each counterevidence Fact is also related
  to the cited Facts by the counter-judge. The calls are recorded under `run_id`, else under a
  run of their own.
- `POST /statements/relate` (`{question, fact_id, counter_fact_id, run_id?}`): the counter-judge
  on a counterevidence Fact and a Fact: `contradicts`, `limits`, `dates`, `qualifies`,
  `supports` or `unrelated`. Only `contradicts` disputes a step.

422 for an unknown Fact, 404 for an unknown run, 503 when LiteLLM (or, for a run of their own,
Hindsight) isn't configured, and 503 `role_unavailable` for a quota or an outage (the bridge's
"Unknown items in responses API response" among them: transient, so call again).
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine, RowMapping, text

from atlas.api.common import INVALID, NOT_FOUND, error_response, error_responses, not_found
from atlas.beliefs.notices import confirm_by_relation
from atlas.investigations.argument import fact_rows, judged_fact
from atlas.investigations.meaning import finding_metadata, verify_bases, voting
from atlas.investigations.tasks import _judged_fact  # pyright: ignore[reportPrivateUsage]
from atlas.jobs.pacing import TransientFailure
from atlas.roles import QuotedText
from atlas.roles.caller import RoleCaller, RoleCallFailed, TokenBudgetExhausted
from atlas.roles.counter_judge import (
    COUNTER_JUDGE,
    COUNTER_JUDGE_VERSION,
    COUNTER_REF,
    RELATIONS,
    UNJUDGED,
    CounterJudgeRequest,
)
from atlas.roles.finding_judge import (
    FINDING_JUDGE,
    FINDING_JUDGE_VERSION,
    FindingJudgeRequest,
    JudgedFinding,
)
from atlas.runs import RunRecorder
from atlas.settings import Settings

Relation = Literal[
    "contradicts", "limits", "dates", "qualifies", "supports", "unrelated", "unjudged"
]
UNAVAILABLE = error_responses(503)
FAILURES = error_responses(409, 502)


class JudgeRequest(BaseModel):
    question: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    fact_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=12)]
    counter_fact_ids: Annotated[list[uuid.UUID], Field(max_length=8)] = []
    votes: Annotated[int, Field(ge=1, le=3)] = 1
    run_id: uuid.UUID | None = None


class JudgedClauseOut(BaseModel):
    text: str
    ref: str | None
    basis: str | None


class JudgeVote(BaseModel):
    verdict: Literal["supported", "misstated"]
    reason: str
    decided: bool
    role_call_id: uuid.UUID


class CounterRelationOut(BaseModel):
    counter_fact_id: uuid.UUID
    fact_id: uuid.UUID
    relation: Relation
    reason: str


class StatementJudgement(BaseModel):
    verdict: Literal["supported", "misstated"]
    clauses: list[JudgedClauseOut]  # the decided vote's, each with the quote words it rests on
    unverified: list[str]  # the clauses whose basis code could not find in the cited quote
    beyond: list[str]  # the statement's own words that go beyond the quotes
    kinds: list[str]
    reason: str
    refs: dict[str, uuid.UUID]  # `c1`, ... as the clauses name them -> the cited Fact
    votes: list[JudgeVote]
    counter_relations: list[CounterRelationOut]
    confirmed_beliefs: list[uuid.UUID] = Field(
        default_factory=list[uuid.UUID],
        description="the Beliefs noticed by a `supports` among the counter relations",
    )
    judge: str
    run_id: uuid.UUID


class RelateRequest(BaseModel):
    question: str = Field(min_length=1)
    fact_id: uuid.UUID  # the Fact challenged
    counter_fact_id: uuid.UUID  # the counterevidence Fact
    run_id: uuid.UUID | None = None


class FactRelation(BaseModel):
    relation: Relation
    reason: str
    judge: str
    run_id: uuid.UUID
    role_call_id: uuid.UUID | None
    confirmed_beliefs: list[uuid.UUID] = Field(
        default_factory=list[uuid.UUID],
        description="the proven Beliefs given a `belief_confirmed` notice: `supports` of a"
        " load-bearing Fact of theirs, by a session's Fact from a document newer than their"
        " as-of time (ticket 26). The judgement is not touched",
    )


class _Refused(Exception):
    def __init__(self, response: JSONResponse) -> None:
        super().__init__(response.status_code)
        self.response = response


def statements_router(engine: Engine, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/statements", tags=["statements"])

    def caller_and_run(run_id: uuid.UUID | None, kind: str) -> tuple[RoleCaller, uuid.UUID]:
        caller = RoleCaller.from_settings(settings, engine)
        if caller is None:
            raise _Refused(
                error_response(
                    503,
                    "litellm_not_configured",
                    "judging needs LiteLLM: set ATLAS_LITELLM_URL and ATLAS_LITELLM_API_KEY",
                )
            )
        if run_id is not None:
            with engine.connect() as connection:
                known = connection.execute(
                    text("SELECT 1 FROM run WHERE id = :id"), {"id": run_id}
                ).scalar()
            if known is None:
                caller.close()
                raise _Refused(not_found("run"))
            return caller, run_id
        recorder = RunRecorder.from_settings(settings, engine)
        if recorder is None:
            caller.close()
            raise _Refused(
                error_response(
                    503,
                    "run_not_recordable",
                    "a run of its own needs Hindsight and LiteLLM: pass a run_id or set both",
                )
            )
        try:
            return caller, recorder.start(kind).id
        except Exception:
            caller.close()
            raise
        finally:
            recorder.close()

    def rows_of(ids: list[uuid.UUID]) -> dict[uuid.UUID, RowMapping]:
        with engine.connect() as connection:
            found = fact_rows(connection, list(dict.fromkeys(ids)))
        by_id = {row["id"]: row for row in found}
        for each in ids:
            if each not in by_id:
                raise _Refused(error_response(422, "unknown_fact", f"no such Fact: {each}"))
        return by_id

    def relate_all(
        caller: RoleCaller,
        run_id: uuid.UUID,
        question: str,
        counter: RowMapping,
        challenged: list[RowMapping],
    ) -> list[tuple[uuid.UUID, Relation, str, uuid.UUID | None]]:
        """The counter-judge's relation of `counter` to each of `challenged` (one call)."""
        sent = {f"f{index}": row for index, row in enumerate(challenged, start=1)}
        counter_item, counter_quote = judged_fact(COUNTER_REF, counter)
        items = {ref: judged_fact(ref, row) for ref, row in sent.items()}
        request = CounterJudgeRequest(
            research_question=question,
            counter=counter_item,
            challenged=[item for item, _ in items.values()],
        )
        judgement, role_call_id = caller.call_recorded(
            COUNTER_JUDGE,
            request,
            run_id=run_id,
            retrieved=[counter_quote, *(quote for _, quote in items.values())],
        )
        answered = {each.ref: each for each in judgement.relations}
        out: list[tuple[uuid.UUID, Relation, str, uuid.UUID | None]] = []
        for ref, row in sent.items():
            each = answered.get(ref)
            if each is None or each.relation not in RELATIONS:
                out.append((row["id"], UNJUDGED, "the judge gave no relation for this Fact", None))
            else:
                out.append((row["id"], each.relation, each.reason, role_call_id))
        return out

    def confirmed(fact_id: uuid.UUID, counter_fact_id: uuid.UUID, relation: str) -> list[uuid.UUID]:
        """The Beliefs noticed because a session's Fact supports a Fact they rest on (ticket
        26; `atlas.beliefs.notices`): none unless the counter-judge said `supports`."""
        if relation != "supports":
            return []
        with engine.begin() as connection:
            return confirm_by_relation(connection, fact_id, counter_fact_id)

    def failed(error: Exception) -> JSONResponse:
        if isinstance(error, TransientFailure):
            return error_response(
                503, "role_unavailable", f"{error.failure_class}: {error}; call again later"
            )
        if isinstance(error, TokenBudgetExhausted):
            return error_response(409, "token_budget_exhausted", str(error))
        return error_response(502, "judge_failed", str(error))

    @router.post(
        "/judge",
        response_model=StatementJudgement,
        responses=INVALID | NOT_FOUND | UNAVAILABLE | FAILURES,
    )
    def judge(body: JudgeRequest) -> StatementJudgement | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            rows = rows_of([*body.fact_ids, *body.counter_fact_ids])
            caller, run_id = caller_and_run(body.run_id, "statement_judge")
        except _Refused as refused:
            return refused.response
        refs = {f"c{index}": fact_id for index, fact_id in enumerate(body.fact_ids, start=1)}
        claims = {ref: rows[fact_id] for ref, fact_id in refs.items()}
        cited = list(claims)
        metadata = finding_metadata(cited, claims)
        request = FindingJudgeRequest(
            research_question=body.question,
            finding=JudgedFinding(statement=body.statement, limitations=[], claim_refs=cited),
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
        relations: list[CounterRelationOut] = []
        try:
            with caller:
                ballot = voting(
                    lambda asked, sent: caller.call_recorded(
                        FINDING_JUDGE, asked, run_id=run_id, retrieved=sent
                    ),
                    body.votes,
                    settings.finding_judge_vote_rule,
                ).ballot(request, quotes, metadata)
                for counter_id in body.counter_fact_ids:
                    for fact_id, relation, reason, _ in relate_all(
                        caller, run_id, body.question, rows[counter_id], list(claims.values())
                    ):
                        relations.append(
                            CounterRelationOut(
                                counter_fact_id=counter_id,
                                fact_id=fact_id,
                                relation=relation,
                                reason=reason,
                            )
                        )
        except (TransientFailure, TokenBudgetExhausted, RoleCallFailed) as error:
            return failed(error)
        decided, _ = ballot.votes[ballot.decided]
        return StatementJudgement(
            verdict=decided.verdict,
            clauses=[
                JudgedClauseOut(text=each.text, ref=each.ref, basis=each.basis)
                for each in decided.clauses
            ],
            unverified=verify_bases(decided, quotes, metadata=metadata),
            beyond=decided.beyond,
            kinds=list(decided.kinds),
            reason=decided.reason,
            refs=refs,
            votes=[
                JudgeVote(
                    verdict=vote.verdict,
                    reason=vote.reason,
                    decided=index == ballot.decided,
                    role_call_id=call_id,
                )
                for index, (vote, call_id) in enumerate(ballot.votes)
            ],
            counter_relations=relations,
            confirmed_beliefs=list(
                dict.fromkeys(
                    belief
                    for each in relations
                    if each.relation == "supports"
                    for belief in confirmed(each.fact_id, each.counter_fact_id, each.relation)
                )
            ),
            judge=FINDING_JUDGE_VERSION,
            run_id=run_id,
        )

    @router.post(
        "/relate",
        response_model=FactRelation,
        responses=INVALID | NOT_FOUND | UNAVAILABLE | FAILURES,
    )
    def relate(body: RelateRequest) -> FactRelation | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            rows = rows_of([body.fact_id, body.counter_fact_id])
            caller, run_id = caller_and_run(body.run_id, "statement_relate")
        except _Refused as refused:
            return refused.response
        try:
            with caller:
                [(_, relation, reason, call_id)] = relate_all(
                    caller, run_id, body.question, rows[body.counter_fact_id], [rows[body.fact_id]]
                )
        except (TransientFailure, TokenBudgetExhausted, RoleCallFailed) as error:
            return failed(error)
        return FactRelation(
            relation=relation,
            reason=reason,
            judge=COUNTER_JUDGE_VERSION,
            run_id=run_id,
            role_call_id=call_id,
            confirmed_beliefs=confirmed(body.fact_id, body.counter_fact_id, relation),
        )

    return router
