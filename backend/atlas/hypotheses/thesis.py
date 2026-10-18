"""A Belief-backed version's thesis judged on its own (atlas-beliefs ticket 30).

The Belief draft judges its thesis once, with the grounding check and one rewrite
(`atlas.hypotheses.belief_drafting`). A correction that changes the thesis, and a version whose
thesis no judge has seen, are judged here instead: the thesis is sent to the finding judge as a
thesis (`THESIS_JUDGE`, `finding_judge.v5`, `finding.thesis`) against the Facts the Beliefs it
cites rest on, the same Facts and the same cap the draft sends, with the draft's votes. There is
no rewrite: the researcher wrote this thesis, and the judge's word on it is its verdict.

`judge_thesis` raises `JudgeUnavailable` when the judge is off or cannot be reached; what the
caller does with that is its own (a correction stores no verdict, the judge-again route answers
503).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Connection, Engine, text

from atlas.beliefs.service import Belief, get_belief
from atlas.investigations.argument import fact_rows
from atlas.judging import Judges, JudgeUnavailable
from atlas.roles.finding_judge import THESIS_JUDGE, THESIS_JUDGE_PROMPT_VERSION

MAX_FACTS_PER_STATEMENT = 12  # the Facts a statement is judged against, as the draft sends them


def fact_citations(belief: Belief) -> list[uuid.UUID]:
    """The load-bearing Facts a Belief rests on (positive valence, kind `fact`)."""
    return [
        each.ref_id
        for each in belief.citations
        if each.kind == "fact" and each.weight == "load_bearing" and each.valence > 0
    ]


def facts_available_by(
    connection: Connection, fact_ids: Sequence[uuid.UUID], as_of: datetime | None
) -> set[uuid.UUID]:
    """The Facts among `fact_ids` that exist and whose Source Version was public by `as_of` (its
    effective `available_at`, a recorded correction's included; no bound: every Fact that
    exists). A Fact of a later document is no ground for a Hypothesis cut off before it."""
    if not fact_ids:
        return set()
    return set(
        connection.execute(
            text(
                "SELECT f.assertion_id FROM fact f JOIN assertion a ON a.id = f.assertion_id"
                " JOIN source_version_availability v ON v.source_version_id = a.source_version_id"
                " WHERE f.assertion_id = ANY(CAST(:ids AS uuid[]))"
                " AND (CAST(:as_of AS timestamptz) IS NULL OR v.available_at <= :as_of)"
            ),
            {"ids": list(fact_ids), "as_of": as_of},
        ).scalars()
    )


@dataclass(frozen=True)
class ThesisJudged:
    """What the judge said of a thesis: `supported` or `misstated` with its reason, or
    `unjudged` when the Beliefs cite no recorded Fact to judge it against (no call is made)."""

    verdict: Literal["supported", "misstated", "unjudged"]
    reason: str
    judge_role: str
    prompt_version: str
    role_call_id: uuid.UUID | None


def judge_thesis(
    engine: Engine,
    judges: Judges,
    *,
    question: str | None,
    statement: str,
    belief_ids: Sequence[uuid.UUID],
    as_of: datetime | None,
) -> ThesisJudged:
    """`statement` judged as a thesis against the Facts of the Beliefs `belief_ids` that were
    public by the Hypothesis's cutoff `as_of` (the cap of 12 comes after the ones that are
    unknown or later are dropped, as in the draft). Raises `JudgeUnavailable` when the judge is
    off or gives no verdict."""
    if not judges.judges_thesis():
        raise JudgeUnavailable("judge_off: ATLAS_FINDING_JUDGE is false")
    with engine.connect() as connection:
        facts: list[uuid.UUID] = []
        for belief_id in belief_ids:
            belief = get_belief(connection, belief_id)
            if belief is not None:
                facts += fact_citations(belief)
        public = facts_available_by(connection, facts, as_of)
        wanted = [each for each in dict.fromkeys(facts) if each in public]
        rows = fact_rows(connection, wanted[:MAX_FACTS_PER_STATEMENT], statements=True)
    if not rows:
        return ThesisJudged(
            "unjudged",
            "the thesis's Beliefs cite no Fact public by the cutoff to judge it against",
            THESIS_JUDGE.name,
            str(THESIS_JUDGE_PROMPT_VERSION),
            None,
        )
    verdict = judges.judge(
        "thesis_judge",
        question=question or "",
        statement=statement,
        rows=rows,
        thesis=True,
        votes=judges.thesis_votes,
    )
    role, _, version = verdict.judge.rpartition(".v")
    return ThesisJudged(verdict.verdict, verdict.reason, role, version, verdict.role_call_id)
