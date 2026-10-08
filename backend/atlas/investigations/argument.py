"""The argument plan (bottleneck-argument ticket 05; docs/decisions.md, "The argument plan"):
what its Readers and its Skeptic recorded, and the argument card built from it.

The plan (atlas.investigations.service.argument_plan): the Scout, then one Reader per
argument step in parallel (`reader:<step>`, atlas.investigations.reader), then the Skeptic (the
same loop, `ARGUMENT_SKEPTIC`, sent the Readers' Facts to challenge) beside the Financial
Analyst (sent the Readers' Facts in place of Claims), then the Editor (`EDITOR_ARGUMENT`), who
writes each step's statements (`editor-argument.v2`: one per point, each citing the few Facts it
uses). Code holds every statement to the quotes it cites, each on its own (the grounding
check, then the finding judge; atlas.investigations.grounding, .meaning): a dropped one leaves
the others standing. It decides each step's status:

- `unknown`: no statement passed, or no Fact stands behind the step;
- `disputed`: a Skeptic Fact contradicts, limits or dates one of the step's Facts (or of the
  Facts its kept statements cite), or could not be judged against it;
- `supported`: otherwise.

What a Skeptic Fact does to each Fact it challenges is the counter-judge's label
(`atlas.roles.counter_judge`, pilot-review T3), recorded in the Skeptic task's artifacts
(`counter_relations`; `counter_relations_unjudged` for the Skeptic Facts whose call failed): a
Skeptic Fact filed under a step, or naming one of its Facts, that only qualifies, supports or
is unrelated to them is shown with the step's counterevidence but never disputes it. A pair
with no label (its call failed, or nothing judged it) counts as contradicting: unjudged, the
step stays disputed and says so in `unchecked`.

The Editor's own status is kept beside it (`editor_status`). The card keeps the research
card's fields (no `findings`: each step's statements are its findings) with `plan` `argument`
and its `steps`.

What each Reader and the Skeptic recorded is read from their sessions (`reader_session`): the
Facts (by ID, with the Facts a Skeptic's speaks against), the queries, the windows read, the
refusals and why each stopped.

A statement never shows the short reference the Editor cites a Fact by (`c1`, `c2`, ...;
ticket 08): one naming a Fact it cites, every one of whose cited Facts with that reference is
one company's, says that company's name instead; one naming a reference it doesn't cite is
dropped as `internal_reference` (`without_references`).
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import JsonValue
from sqlalchemy import Connection, RowMapping, text

from atlas.investigations.model import (
    CardArgumentStep,
    CardFact,
    CardFactQuantity,
    CardFactRelation,
    CardStepStatement,
    CardStepStatus,
    SourceSpan,
)
from atlas.investigations.reader import ReaderState
from atlas.roles.contract import QuotedText
from atlas.roles.counter_judge import CONTRADICTING, UNJUDGED, JudgedFactItem
from atlas.roles.reader import ARGUMENT_STEPS, ChallengedFact

# At most this many of the Readers' Facts are sent to the Skeptic to challenge (oldest first).
MAX_CHALLENGED = 60
SKEPTIC_CHALLENGED = "challenged_fact_ids"  # the Skeptic task's artifact naming them
# The Skeptic task's artifacts holding the counter-judge's labels (pilot-review T3): a Skeptic
# Fact -> each Fact it challenges -> its relation (and the judge's reason); the Skeptic Facts
# whose call failed; how many calls were made.
COUNTER_RELATIONS = "counter_relations"
COUNTER_REASONS = "counter_relation_reasons"
COUNTER_UNJUDGED = "counter_relations_unjudged"
COUNTER_JUDGE_CALLS = "counter_judge_calls"


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
    # A Skeptic Fact -> a Fact it challenges -> the counter-judge's relation (and reason).
    relations: dict[uuid.UUID, dict[uuid.UUID, str]] = field(
        default_factory=dict[uuid.UUID, dict[uuid.UUID, str]]
    )
    reasons: dict[uuid.UUID, dict[uuid.UUID, str]] = field(
        default_factory=dict[uuid.UUID, dict[uuid.UUID, str]]
    )

    def relation(self, counter_id: uuid.UUID, fact_id: uuid.UUID) -> str:
        """What Skeptic Fact `counter_id` does to `fact_id`, one of the Facts it challenges:
        the counter-judge's label, or `unjudged` when there is none."""
        return self.relations.get(counter_id, {}).get(fact_id, UNJUDGED)

    def against_of(self, counter_id: uuid.UUID) -> list[uuid.UUID]:
        """The Facts Skeptic Fact `counter_id` speaks against: those it challenges whose
        relation contradicts, limits or dates them, or could not be judged."""
        return [
            each
            for each in self.against.get(counter_id, [])
            if self.relation(counter_id, each) in CONTRADICTING | {UNJUDGED}
        ]

    def contradicted_by(self, counter_id: uuid.UUID) -> list[uuid.UUID]:
        """The Facts the counter-judge found Skeptic Fact `counter_id` contradicts, limits or
        dates (judged: an unjudged pair is not among them)."""
        return [
            each
            for each in self.against.get(counter_id, [])
            if self.relation(counter_id, each) in CONTRADICTING
        ]

    def card_relations(self, counter_id: uuid.UUID) -> list[CardFactRelation]:
        """What Skeptic Fact `counter_id` does to each Fact it challenges, for the card."""
        return [
            CardFactRelation(
                fact_id=each,
                relation=self.relation(counter_id, each),
                reason=self.reasons.get(counter_id, {}).get(each),
            )
            for each in self.against.get(counter_id, [])
        ]


def skeptic_relations(
    connection: Connection, investigation_id: uuid.UUID, round_: int | None = None
) -> tuple[dict[uuid.UUID, dict[uuid.UUID, str]], dict[uuid.UUID, dict[uuid.UUID, str]]]:
    """The counter-judge's relations and reasons the investigation's Skeptic tasks recorded
    (every round's, or `round_`'s), by Skeptic Fact and challenged Fact."""
    relations: dict[uuid.UUID, dict[uuid.UUID, str]] = {}
    reasons: dict[uuid.UUID, dict[uuid.UUID, str]] = {}
    rows = connection.execute(
        text(
            "SELECT artifacts FROM investigation_task WHERE investigation_id = :id"
            " AND role = 'skeptic' AND (CAST(:round AS integer) IS NULL OR round = :round)"
            " ORDER BY round"
        ),
        {"id": investigation_id, "round": round_},
    ).all()
    for (artifacts,) in rows:
        recorded = cast(dict[str, Any], artifacts) if isinstance(artifacts, dict) else {}
        for target, source in ((relations, COUNTER_RELATIONS), (reasons, COUNTER_REASONS)):
            given: Any = recorded.get(source)
            if not isinstance(given, dict):
                continue
            for counter_id, labels in cast(dict[str, Any], given).items():
                if isinstance(labels, dict):
                    target[uuid.UUID(counter_id)] = {
                        uuid.UUID(fact_id): str(label)
                        for fact_id, label in cast(dict[str, Any], labels).items()
                    }
    return relations, reasons


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
    relations, reasons = skeptic_relations(connection, investigation_id)
    return ArgumentFacts(
        sessions=sessions,
        supporting=[row for row in rows if roles[row["id"]] == "reader"],
        counter=[row for row in rows if roles[row["id"]] == "skeptic"],
        against=against,
        rounds=rounds,
        relations=relations,
        reasons=reasons,
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


def judged_fact(ref: str, row: RowMapping) -> tuple[JudgedFactItem, QuotedText]:
    """A Fact as the counter-judge is sent it, by `ref`, with its quote as retrieved data."""
    value = _value(row)
    return (
        JudgedFactItem(
            ref=ref,
            company=row["subject_name"],
            step=row["step"],
            statement=str(value.get("statement", "")),
            status=str(value.get("status", "")),
            quantity=quantity_text(row),
            period=value.get("period"),
            source_title=row["source_title"],
        ),
        QuotedText(
            id=ref,
            source=f"{row['source_version_id']}#{row['span_start']}-{row['span_end']}",
            text=row["quote"],
        ),
    )


def card_fact(
    row: RowMapping,
    against: Sequence[uuid.UUID] = (),
    relations: Sequence[CardFactRelation] = (),
) -> CardFact:
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
        relations=list(relations),
    )


@dataclass(frozen=True)
class KeptStatement:
    """One of a step's statements that passed its checks."""

    statement: str
    cited: list[str]  # the references it cites (its Facts, then its counterevidence)
    judged: bool | None  # True: judged supported; None: kept unjudged


@dataclass(frozen=True)
class StepStatement:
    """What came of the Editor's statements for one step."""

    kept: list[KeptStatement]  # in the Editor's order; empty: none passed (or none was written)
    editor_status: CardStepStatus | None
    unchecked: list[str]


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
    counter_ids = {row["id"] for row in facts.counter}

    def counter_fact(row: RowMapping) -> CardFact:
        return card_fact(row, facts.against_of(row["id"]), facts.card_relations(row["id"]))

    for definition in ARGUMENT_STEPS:
        said = statements.get(definition.key)
        kept = said.kept if said else []
        cited_ids = {refs[ref]["id"] for each in kept for ref in each.cited if ref in refs}
        supporting = [
            row
            for row in facts.supporting
            if row["step"] == definition.key or row["id"] in cited_ids
        ]
        ids = {row["id"] for row in supporting}
        counter = [
            row
            for row in facts.counter
            if row["step"] == definition.key
            or set(facts.against.get(row["id"], [])) & ids
            or row["id"] in cited_ids
        ]
        shown = [
            CardStepStatement(
                statement=each.statement,
                facts=[
                    card_fact(refs[ref])
                    for ref in each.cited
                    if ref in refs and refs[ref]["id"] not in counter_ids
                ],
                counterevidence=[
                    counter_fact(refs[ref])
                    for ref in each.cited
                    if ref in refs and refs[ref]["id"] in counter_ids
                ],
                judged=each.judged,
            )
            for each in kept
        ]
        # Only a Skeptic Fact that contradicts, limits or dates one of the step's Facts (or
        # could not be judged against one) disputes it; one that qualifies, supports or is
        # unrelated to them is shown but disputes nothing.
        disputing = [row for row in facts.counter if set(facts.against_of(row["id"])) & ids]
        contested = any(set(facts.contradicted_by(row["id"])) & ids for row in facts.counter)
        unjudged = [
            row
            for row in facts.counter
            if any(
                facts.relation(row["id"], each) == UNJUDGED
                for each in facts.against.get(row["id"], [])
                if each in ids
            )
        ]
        first = kept[0] if kept else None
        statement = first.statement if first else None
        status: CardStepStatus
        if statement is None or not supporting:
            status = "unknown"
        elif disputing:
            status = "disputed"
        else:
            status = "supported"
        unchecked = list(said.unchecked) if said else []
        if not supporting:
            unchecked.append("no Fact was recorded for this step")
        if unjudged:
            unchecked.append(
                f"{len(unjudged)} counter-Fact{'s' if len(unjudged) != 1 else ''}"
                " could not be judged"
            )
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
                statements=shown,
                facts=[card_fact(row) for row in supporting],
                counterevidence=[counter_fact(row) for row in counter],
                unchecked=list(dict.fromkeys(unchecked)),
                grounded=True if first else None,
                judged=first.judged if first else None,
                searched=[str(each["query"]) for each in state.searches] if state else [],
                documents_read=(
                    list(dict.fromkeys(str(each["title"]) for each in state.reads)) if state else []
                ),
                facts_refused=len(state.refused) if state else 0,
                reader_summary=state.summary if state else None,
                reader_stop=state.stop_reason if state else None,
                skeptic_checked=checked,
                contested=contested,
            )
        )
    return steps


def step_counts(steps: Sequence[CardArgumentStep]) -> dict[str, JsonValue]:
    return {step.step: step.status for step in steps}


_REFERENCE = re.compile(r"\bc\d+\b")


def without_references(
    statement: str, cited: Sequence[str], refs: Mapping[str, Mapping[Any, Any]]
) -> str | None:
    """The statement with each Fact reference it names (`c1`, ...: a key of `refs`) replaced by
    the cited Fact's company name, or None when it names a reference it doesn't cite (or
    whose Fact has no company name). Words only shaped like one ("C3 band") are left: only
    the Editor's references, lower case as it was sent them, count."""
    named = [m for m in _REFERENCE.finditer(statement) if m.group(0) in refs]
    if not named:
        return statement
    names: dict[str, str] = {}
    for match in named:
        ref = match.group(0)
        name = refs[ref].get("subject_name")
        if ref not in cited or not name:
            return None
        names[ref] = str(name)
    return _REFERENCE.sub(lambda m: names.get(m.group(0), m.group(0)), statement)
