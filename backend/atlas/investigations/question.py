"""The question's parts (pilot-review R2-01; docs/decisions.md, "Reading that follows the
question: parts, terms and the card's account").

An argument investigation's Scout task plans each round's question once
(`atlas.roles.question_planner`) and stores the plan in its artifacts (`question_plan`:
`{source, parts, step_focus}`); when the planner's answer is quarantined, or the run's token
budget is spent, the plan is code's (`fallback_plan`, `source` `fallback`). The round's Readers
read it (`load_plan`): each is sent the parts and its step's focus, a search naming no term of
any part is refused (`names_a_part`), and each Fact names the part it answers. The Editor's card
says which parts its statements answered (atlas.investigations.argument.parts_answered).
"""

import re
import uuid
from collections.abc import Mapping
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Connection, text

from atlas.research.search import _STOPWORDS  # pyright: ignore[reportPrivateUsage]
from atlas.roles.question_planner import QuestionPlanDraft

QUESTION_PLAN = "question_plan"  # the Scout task's artifact holding the round's plan
PlanSource = Literal["planner", "fallback"]
# A clause of fewer words joins the clause before it (`fallback_plan`).
MIN_CLAUSE_WORDS = 3
# At most this many terms are named in a refused search's message.
TERMS_SHOWN = 12


class QuestionPart(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    key: str
    text: str
    terms: list[str]
    layer: str | None = None


class QuestionPlan(BaseModel):
    """A round's plan of its question: the parts, and what each argument step must establish
    for it (`step_focus`, by step key; empty for the fallback)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    source: PlanSource
    parts: list[QuestionPart]
    step_focus: dict[str, str] = Field(default_factory=dict[str, str])

    def keys(self) -> list[str]:
        return [part.key for part in self.parts]

    def artifact(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], self.model_dump(mode="json"))


def planned(draft: QuestionPlanDraft, steps: set[str]) -> QuestionPlan:
    """The planner's answer as the stored plan: its focus keyed by step, a step that isn't
    one of `steps` (or a blank focus) left out, the first entry for a step kept."""
    focus: dict[str, str] = {}
    for each in draft.step_focus:
        if each.step in steps and each.focus.strip() and each.step not in focus:
            focus[each.step] = each.focus.strip()
    return QuestionPlan(
        source="planner",
        parts=[
            QuestionPart(key=p.key, text=p.text.strip(), terms=p.terms, layer=p.layer)
            for p in draft.parts
        ],
        step_focus=focus,
    )


# --- the fallback -------------------------------------------------------------------------------

_PARENTHESISED = re.compile(r"\(([^()]*)\)")
_EDGE = "\"'`.,;:!?()[]{}"


def _clauses(question: str) -> list[str]:
    """The question split at ';', ':' and ', ' outside parentheses."""
    clauses: list[str] = []
    depth = 0
    current: list[str] = []
    index = 0
    while index < len(question):
        char = question[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        split = depth == 0 and (
            char in ";:" or (char == "," and question[index + 1 : index + 2] == " ")
        )
        if split:
            clauses.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    clauses.append("".join(current))
    return [" ".join(each.split()) for each in clauses if each.strip()]


def _clause_terms(clause: str) -> list[str]:
    """A clause's words of 3 or more letters that are not stopwords, as written (outside its
    parentheses), then each parenthesised item split on ','."""
    outside = _PARENTHESISED.sub(" ", clause)
    terms: list[str] = []
    for word in outside.split():
        word = word.strip(_EDGE)
        if sum(char.isalpha() for char in word) >= 3 and word.lower() not in _STOPWORDS:
            terms.append(word)
    for inside in _PARENTHESISED.findall(clause):
        terms += [item.strip(_EDGE + " ") for item in inside.split(",") if item.strip(_EDGE + " ")]
    return list(dict.fromkeys(terms))


def fallback_plan(question: str) -> QuestionPlan:
    """Code's plan of the question when the planner's answer can't be had: one part per
    clause (split at ';', ':' and ', ' outside parentheses; a clause of fewer than
    `MIN_CLAUSE_WORDS` words joins the one before it, or the next when it is the first), key
    `part_<n>`, its terms the clause's words of 3+ letters that are not stopwords and each
    parenthesised item; no step focus."""
    merged: list[str] = []
    pending = ""
    for clause in _clauses(question):
        if len(clause.split()) < MIN_CLAUSE_WORDS:
            if merged:
                merged[-1] = f"{merged[-1]}, {clause}"
            else:
                pending = f"{pending}, {clause}" if pending else clause
            continue
        merged.append(f"{pending}, {clause}" if pending else clause)
        pending = ""
    if pending:
        merged.append(pending)
    parts = [
        QuestionPart(key=f"part_{index}", text=clause, terms=_clause_terms(clause))
        for index, clause in enumerate(merged, start=1)
    ]
    return QuestionPlan(source="fallback", parts=[p for p in parts if p.terms] or parts)


# --- reading it -----------------------------------------------------------------------------------


def load_plan(
    connection: Connection, investigation_id: uuid.UUID, round_: int
) -> QuestionPlan | None:
    """The round's plan, from its Scout task's artifacts; None before the Scout stored one (a
    round run before R2-01, or the default plan)."""
    artifacts: Any = connection.execute(
        text(
            "SELECT artifacts FROM investigation_task WHERE investigation_id = :id"
            " AND round = :round AND key = 'scout'"
        ),
        {"id": investigation_id, "round": round_},
    ).scalar_one_or_none()
    stored: Any = (
        cast(Mapping[str, Any], artifacts).get(QUESTION_PLAN)
        if isinstance(artifacts, Mapping)
        else None
    )
    if not isinstance(stored, Mapping):
        return None
    return QuestionPlan.model_validate(stored)


def _term_pattern(term: str) -> re.Pattern[str] | None:
    """The term as a whole word (a plural 's' or 'es' allowed), case-insensitively; a hyphen or
    a space in it matches either."""
    words = [w for w in re.split(r"[\s\-]+", term.strip()) if w]
    if not words:
        return None
    body = r"[\s\-]+".join(re.escape(word) for word in words)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?:e?s)?(?![A-Za-z0-9])", re.IGNORECASE)


def names_a_part(query: str, plan: QuestionPlan) -> str | None:
    """The key of the first part (in the plan's order) one of whose terms the query names, or
    None when it names none."""
    for part in plan.parts:
        for term in part.terms:
            pattern = _term_pattern(term)
            if pattern is not None and pattern.search(query):
                return part.key
    return None


def terms_to_name(plan: QuestionPlan, limit: int = TERMS_SHOWN) -> list[str]:
    """Up to `limit` of the plan's terms, taken from each part in turn."""
    shown: list[str] = []
    depth = 0
    while len(shown) < limit and any(depth < len(part.terms) for part in plan.parts):
        for part in plan.parts:
            if depth < len(part.terms) and part.terms[depth] not in shown:
                shown.append(part.terms[depth])
                if len(shown) == limit:
                    break
        depth += 1
    return shown
