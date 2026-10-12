"""The argument plan's Editor proposes Beliefs (beliefs ticket 03).

One `unproven` Belief per kept step statement, in the transaction that stores the card, citing
the statement's Facts (valence +0.5, load-bearing) and the Skeptic Facts the counter-judge
related to them (its relation's default valence, as context). A Belief with the same statement
in the same theme and step is cited again, never duplicated. The pipeline never judges: the
Belief stays `unproven` until an author does.
"""

import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import Connection, text

from atlas.beliefs.service import RELATION_VALENCE, BeliefPropose, Beliefs, CitationIn, Step
from atlas.investigations.model import CardArgumentStep, CardFact, CardStepStatement

STATEMENT_VALENCE = 0.5


def _citations(statement: CardStepStatement, actor: str) -> list[CitationIn]:
    cited: dict[uuid.UUID, CitationIn] = {}
    for fact in statement.facts:
        cited.setdefault(
            fact.fact_id,
            CitationIn(
                ref_id=fact.fact_id,
                valence=STATEMENT_VALENCE,
                weight="load_bearing",
                actor=actor,
            ),
        )
    ours = set(cited)
    # The Skeptic Facts the counter-judge related to the statement's Facts: the strongest
    # relation it found (the most negative valence) is the citation's.
    counter: dict[uuid.UUID, tuple[float, str]] = {}
    for fact in statement.counterevidence:
        for relation in fact.relations:
            valence = RELATION_VALENCE.get(relation.relation)
            if relation.fact_id not in ours or valence is None:
                continue
            if fact.fact_id not in counter or valence < counter[fact.fact_id][0]:
                counter[fact.fact_id] = (valence, relation.relation)
    for fact_id, (valence, relation) in counter.items():
        cited.setdefault(
            fact_id,
            CitationIn(
                ref_id=fact_id,
                valence=valence,
                weight="context",
                note=f"the counter-judge: {relation}",
                actor=actor,
            ),
        )
    return list(cited.values())


def _companies(facts: list[CardFact]) -> list[uuid.UUID]:
    return list(dict.fromkeys(fact.company_id for fact in facts))


def propose_from_card(
    connection: Connection,
    beliefs: Beliefs,
    *,
    steps: list[CardArgumentStep],
    theme: str,
    as_of: datetime,
    session_id: uuid.UUID,
    actor: str,
) -> dict[str, list[uuid.UUID]]:
    """Propose (or cite again) a Belief for each kept statement; the Belief IDs by step."""
    made: dict[str, list[uuid.UUID]] = {}
    for step in steps:
        for statement in step.statements:
            citations = _citations(statement, actor)
            if not any(each.weight == "load_bearing" for each in citations):
                continue
            existing = connection.execute(
                text(
                    "SELECT id FROM belief WHERE theme = :theme AND step = :step"
                    " AND statement = :statement AND status = 'active'"
                    " ORDER BY created_at LIMIT 1"
                ),
                {"theme": theme, "step": step.step, "statement": statement.statement},
            ).scalar_one_or_none()
            if existing is None:
                belief_id = beliefs.propose_within(
                    connection,
                    BeliefPropose(
                        statement=statement.statement,
                        theme=theme,
                        step=cast(Step, step.step),
                        company_ids=_companies(statement.facts),
                        as_of=as_of,
                        session_id=session_id,
                        actor=actor,
                        citations=citations,
                    ),
                ).id
            else:
                belief_id = existing
                already = set(
                    connection.execute(
                        text("SELECT ref_id FROM belief_citation WHERE belief_id = :id"),
                        {"id": belief_id},
                    ).scalars()
                )
                for citation in citations:
                    if citation.ref_id not in already:
                        beliefs.cite_within(connection, belief_id, citation)
            if belief_id not in made.setdefault(step.step, []):
                made[step.step].append(belief_id)
    return made
