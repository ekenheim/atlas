"""The argument plan (bottleneck-argument ticket 05; docs/decisions.md, "The argument plan"):
what its Readers and its Skeptic recorded, and the argument card built from it.

The plan (atlas.investigations.service.argument_plan): the Scout, then one Reader per
argument step in parallel (`reader:<step>`, atlas.investigations.reader), then the Skeptic (the
same loop, `ARGUMENT_SKEPTIC`, sent the Readers' Facts to challenge) beside the Financial
Analyst (sent the Readers' Facts in place of Claims), then the Editor (`EDITOR_ARGUMENT`), who
writes each step's statement. Code holds every statement to the quotes it cites (the grounding
check, then the finding judge; atlas.investigations.grounding, .meaning) and decides each
step's status:

- `unknown`: no statement passed, or no Fact stands behind the step;
- `disputed`: the Skeptic's counterevidence is on the step, or speaks against one of its Facts;
- `supported`: otherwise.

The Editor's own status is kept beside it (`editor_status`). The card keeps the research
card's fields (no `findings`: each step's statement is its finding) with `plan` `argument` and
its `steps`.

What each Reader and the Skeptic recorded is read from their sessions (`reader_session`): the
Facts (by ID, with the Facts a Skeptic's speaks against), the queries, the windows read, the
refusals and why each stopped.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import JsonValue
from sqlalchemy import Connection, RowMapping, text

from atlas.investigations.model import (
    CardArgumentStep,
    CardFact,
    CardFactQuantity,
    CardStepStatus,
    SourceSpan,
)
from atlas.investigations.reader import ReaderState
from atlas.roles.contract import QuotedText
from atlas.roles.reader import ARGUMENT_STEPS, ChallengedFact

# At most this many of the Readers' Facts are sent to the Skeptic to challenge (oldest first).
MAX_CHALLENGED = 60
SKEPTIC_CHALLENGED = "challenged_fact_ids"  # the Skeptic task's artifact naming them


@dataclass(frozen=True)
class ArgumentSession:
    """A Reader's or the Skeptic's session in the investigation."""

    task_key: str
    round: int
    role: str  # reader or skeptic
    step: str
    status: str
    state: ReaderState


@dataclass
class ArgumentFacts:
    sessions: list[ArgumentSession]
    supporting: list[RowMapping]  # the Readers' Facts, oldest first
    counter: list[RowMapping]  # the Skeptic's
    against: dict[uuid.UUID, list[uuid.UUID]] = field(
        default_factory=dict[uuid.UUID, list[uuid.UUID]]
    )  # a Skeptic Fact -> the Readers' Facts it speaks against
    rounds: dict[uuid.UUID, int] = field(default_factory=dict[uuid.UUID, int])


def argument_facts(
    connection: Connection, investigation_id: uuid.UUID, *, statements: bool = False
) -> ArgumentFacts:
    """The Facts the investigation's Readers and Skeptic recorded, every round, as rows shaped
    like the accepted Claims' (atlas.investigations.tasks.accepted_claims: `subject_name`,
    `predicate` `fact`, `quote`, the span, ...). `statements`: each row's `object_text` is the
    Fact's statement (for the Financial Analyst); else None (the grounding check's grounds are
    the quotes only)."""
    sessions = [
        ArgumentSession(
            task_key=row.key,
            round=row.round,
            role=row.role,
            step=row.step,
            status=row.status,
            state=ReaderState.model_validate(row.state),
        )
        for row in connection.execute(
            text(
                "SELECT t.key, t.round, s.role, s.step, s.status, s.state FROM reader_session s"
                " JOIN investigation_task t ON t.id = s.task_id"
                " WHERE s.investigation_id = :id ORDER BY t.round, t.position"
            ),
            {"id": investigation_id},
        )
    ]
    roles: dict[uuid.UUID, str] = {}
    rounds: dict[uuid.UUID, int] = {}
    against: dict[uuid.UUID, list[uuid.UUID]] = {}
    for session in sessions:
        for fact in session.state.facts:
            roles[fact.fact_id] = session.role
            rounds[fact.fact_id] = session.round
            if session.role == "skeptic":
                against[fact.fact_id] = list(fact.challenged_fact_ids)
    rows = fact_rows(connection, list(roles), statements=statements)
    return ArgumentFacts(
        sessions=sessions,
        supporting=[row for row in rows if roles[row["id"]] == "reader"],
        counter=[row for row in rows if roles[row["id"]] == "skeptic"],
        against=against,
        rounds=rounds,
    )


def fact_rows(
    connection: Connection, fact_ids: Sequence[uuid.UUID], *, statements: bool = False
) -> list[RowMapping]:
    """The Facts as rows shaped like accepted Claims (see `argument_facts`), oldest first."""
    if not fact_ids:
        return []
    return list(
        connection.execute(
            text(
                "SELECT a.id, a.id AS assertion_id, f.step, a.value_json, a.subject_company_id,"
                " CAST(NULL AS uuid) AS object_company_id, s.display_name AS subject_name,"
                " s.slug AS subject_slug, CAST(NULL AS text) AS object_name,"
                " CASE WHEN :statements THEN a.value_json ->> 'statement' END AS object_text,"
                " CAST(NULL AS text) AS product, CAST(NULL AS text) AS layer, a.predicate,"
                " a.epistemic_type, a.quote, a.source_version_id, a.span_start, a.span_end,"
                " a.verification_status, coalesce(d.title, d.canonical_url) AS source_title,"
                " v.available_at, m.evidence_family_id"
                " FROM fact f JOIN assertion a ON a.id = f.assertion_id"
                " JOIN company s ON s.id = a.subject_company_id"
                " JOIN source_version v ON v.id = a.source_version_id"
                " JOIN source_document d ON d.id = v.source_document_id"
                " LEFT JOIN evidence_family_member m ON m.source_version_id = a.source_version_id"
                " WHERE f.assertion_id = ANY(:ids) ORDER BY f.created_at, f.assertion_id"
            ),
            {"ids": list(fact_ids), "statements": statements},
        ).mappings()
    )


def _value(row: RowMapping) -> dict[str, Any]:
    value: Any = row["value_json"]
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def quantity_text(row: RowMapping) -> str | None:
    quantity: Any = _value(row).get("quantity")
    if not isinstance(quantity, dict):
        return None
    shown = cast(dict[str, Any], quantity)
    return f"{shown.get('value')} {shown.get('unit')} ({shown.get('metric')})"


def challenged(facts: Sequence[RowMapping]) -> tuple[list[ChallengedFact], list[QuotedText]]:
    """The Readers' Facts as the Skeptic is sent them (`f1`, ...), with their quotes."""
    chosen = list(facts)[:MAX_CHALLENGED]
    sent = [
        ChallengedFact(
            ref=f"f{index}",
            step=row["step"],
            company_slug=row["subject_slug"],
            statement=str(_value(row).get("statement", "")),
            status=str(_value(row).get("status", "")),
            quantity=quantity_text(row),
            period=_value(row).get("period"),
            source_title=row["source_title"],
        )
        for index, row in enumerate(chosen, start=1)
    ]
    quotes = [
        QuotedText(
            id=f"f{index}",
            source=f"{row['source_version_id']}#{row['span_start']}-{row['span_end']}",
            text=row["quote"],
        )
        for index, row in enumerate(chosen, start=1)
    ]
    return sent, quotes


def card_fact(row: RowMapping, against: Sequence[uuid.UUID] = ()) -> CardFact:
    value = _value(row)
    quantity: Any = value.get("quantity")
    return CardFact(
        fact_id=row["id"],
        company_id=row["subject_company_id"],
        company_name=row["subject_name"],
        step=row["step"],
        status=str(value.get("status", "")),
        statement=str(value.get("statement", "")),
        quantity=CardFactQuantity.model_validate(quantity) if isinstance(quantity, dict) else None,
        period=value.get("period"),
        source_title=row["source_title"],
        source_span=SourceSpan(
            claim_id=row["id"],
            assertion_id=row["id"],
            source_version_id=row["source_version_id"],
            span_start=row["span_start"],
            span_end=row["span_end"],
            quote=row["quote"],
            verification_status=row["verification_status"],
        ),
        evidence_available_at=row["available_at"],
        against=list(against),
    )


@dataclass(frozen=True)
class StepStatement:
    """What came of the Editor's statement for one step."""

    statement: str | None  # None: none passed (or none was written)
    cited: list[str]  # the references it cites
    editor_status: CardStepStatus | None
    unchecked: list[str]
    grounded: bool | None
    judged: bool | None


def build_steps(
    facts: ArgumentFacts,
    statements: dict[str, StepStatement],
    refs: dict[str, RowMapping],
    skeptic_checked: set[uuid.UUID],
    skeptic_ran: bool,
) -> list[CardArgumentStep]:
    """The argument's six steps, in order, each with its status (see the module)."""
    steps: list[CardArgumentStep] = []
    readers = {s.step: s for s in facts.sessions if s.role == "reader"}  # the latest round's
    for definition in ARGUMENT_STEPS:
        said = statements.get(definition.key)
        cited_ids = {refs[ref]["id"] for ref in (said.cited if said else []) if ref in refs}
        supporting = [
            row
            for row in facts.supporting
            if row["step"] == definition.key or (said and said.statement and row["id"] in cited_ids)
        ]
        ids = {row["id"] for row in supporting}
        counter = [
            row
            for row in facts.counter
            if row["step"] == definition.key
            or set(facts.against.get(row["id"], [])) & ids
            or (said and said.statement and row["id"] in cited_ids)
        ]
        statement = said.statement if said else None
        status: CardStepStatus
        if statement is None or not supporting:
            status = "unknown"
        elif counter:
            status = "disputed"
        else:
            status = "supported"
        unchecked = list(said.unchecked) if said else []
        if not supporting:
            unchecked.append("no Fact was recorded for this step")
        checked = bool(ids) and ids <= skeptic_checked
        if ids and not checked:
            unchecked.append(
                "the Skeptic was not sent every Fact of this step to challenge"
                if skeptic_ran
                else "the Skeptic did not run, so nothing here was challenged"
            )
        reader = readers.get(definition.key)
        state = reader.state if reader else None
        steps.append(
            CardArgumentStep(
                step=definition.key,
                title=definition.title,
                asks=definition.asks,
                status=status,
                editor_status=said.editor_status if said else None,
                statement=statement,
                facts=[card_fact(row) for row in supporting],
                counterevidence=[
                    card_fact(row, facts.against.get(row["id"], [])) for row in counter
                ],
                unchecked=list(dict.fromkeys(unchecked)),
                grounded=said.grounded if said and statement else None,
                judged=said.judged if said and statement else None,
                searched=[str(each["query"]) for each in state.searches] if state else [],
                documents_read=(
                    list(dict.fromkeys(str(each["title"]) for each in state.reads)) if state else []
                ),
                facts_refused=len(state.refused) if state else 0,
                reader_summary=state.summary if state else None,
                reader_stop=state.stop_reason if state else None,
                skeptic_checked=checked,
            )
        )
    return steps


def step_counts(steps: Sequence[CardArgumentStep]) -> dict[str, JsonValue]:
    return {step.step: step.status for step in steps}
