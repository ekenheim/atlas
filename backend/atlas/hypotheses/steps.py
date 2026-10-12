"""The steps of a Hypothesis over Beliefs (atlas-beliefs ticket 14).

A version's `steps` are the argument's steps (constraint, demand against supply, relief,
control, capture, invalidation), each with the Beliefs it rests on as they stood when the
version was drafted: the Belief's statement, its judgement and confidence, its as-of time and
its load-bearing citations (the Facts' exact quotes at their spans). A step may have a
`statement`, the Editor's one sentence on the step citing some of those Beliefs
(`statement_belief_ids`), grounded in their Facts' quotes and judged like a card statement.

The content is frozen with the version. What the Beliefs are judged *now* is read again by the
publish gate and by the Research Snapshot (atlas.snapshots), inside the publishing transaction.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection

from atlas.beliefs.service import Belief, get_belief

# The order the argument is told in.
STEP_ORDER: tuple[str, ...] = (
    "constraint",
    "demand_vs_supply",
    "relief",
    "control",
    "capture",
    "invalidation",
)


class StepCitation(BaseModel):
    """A load-bearing citation of a Belief: a Fact (or Assertion) and the words at its span."""

    model_config = ConfigDict(frozen=True)

    ref_id: uuid.UUID  # the Fact's ID, which is its Assertion's
    kind: str
    valence: float
    statement: str | None
    quote: str
    span_start: int
    span_end: int
    source_version_id: uuid.UUID
    source_title: str | None
    company_name: str
    available_at: datetime


class StepBelief(BaseModel):
    model_config = ConfigDict(frozen=True)

    belief_id: uuid.UUID
    statement: str
    judgement: str
    confidence: float
    as_of: datetime
    judged_by: str
    companies: list[str]
    citations: list[StepCitation]


class HypothesisStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    step: str
    statement: str | None = None
    statement_belief_ids: list[uuid.UUID] = []
    # True: the finding judge found the statement supported; None: not judged (the judge is
    # off, or its call failed).
    judged: bool | None = None
    beliefs: list[StepBelief]


def step_belief(belief: Belief) -> StepBelief:
    return StepBelief(
        belief_id=belief.id,
        statement=belief.statement,
        judgement=belief.judgement.judgement,
        confidence=belief.judgement.confidence,
        as_of=belief.as_of,
        judged_by=belief.judgement.actor,
        companies=[each.display_name for each in belief.companies],
        citations=[
            StepCitation(
                ref_id=each.ref_id,
                kind=each.kind,
                valence=each.valence,
                statement=each.statement,
                quote=each.quote,
                span_start=each.span_start,
                span_end=each.span_end,
                source_version_id=each.source_version_id,
                source_title=each.source_title,
                company_name=each.company_name,
                available_at=each.available_at,
            )
            for each in belief.citations
            if each.weight == "load_bearing" and each.valence > 0
        ],
    )


def read_beliefs(connection: Connection, belief_ids: Sequence[uuid.UUID]) -> list[Belief]:
    found = (get_belief(connection, each) for each in dict.fromkeys(belief_ids))
    return [each for each in found if each is not None]


def step_belief_ids(steps: Sequence[HypothesisStep]) -> list[uuid.UUID]:
    """Every Belief the steps rest on, once, in step order."""
    return list(dict.fromkeys(each.belief_id for step in steps for each in step.beliefs))
