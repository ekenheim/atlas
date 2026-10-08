"""The question planner (pilot-review R2-01; docs/decisions.md, "Reading that follows the
question: parts, terms and the card's account"): the research question split into the parts it
asks, each with the words a filing or a call would write for it, and what each argument step
must establish for this question.

On pilot question 5 ("How does coherent-optics and systems demand (DCI, 800ZR) pull on
component supply, and where does it bind?") the Readers were sent the whole question and a
`looks_for` that is the same for every question; 18 of 24 of their term searches named none of
the question's own terms and returned the theme's datacom story (27% of 0.5.4's Facts were off
the question). The plan gives each Reader the question's parts and their terms; code refuses a
search that names none of them (atlas.investigations.reader) and the card says which parts its
statements answered (atlas.investigations.argument.parts_answered).

One call per round, in the Scout task, after the discovery. The request carries the question,
the theme and the argument's steps (key, title, what each asks); no retrieved data. The answer
(`QuestionPlanDraft`): 2 to 6 `parts`, each a snake_case `key`, the question's own words for it
(`text`), up to 12 search `terms` and an optional supply-chain `layer`; and `step_focus`, one
sentence per argument step. `step_focus` is a list of `{step, focus}` in the schema (a strict
JSON schema has no open-keyed object) and is also read when the model writes it as an object
keyed by step; code stores it keyed by step (atlas.investigations.question).
"""

import re
from typing import Any, Self, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

QUESTION_PLANNER_PROMPT_VERSION = 1

MIN_PARTS = 2
MAX_PARTS = 6
MAX_TERMS = 12


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlannerStep(_Request):
    key: str
    title: str
    asks: str


class QuestionPlannerRequest(_Request):
    research_question: str
    theme_title: str
    theme_description: str
    steps: list[PlannerStep]


def snake_case(value: str) -> str:
    """`value` as a snake_case key: lower case, every run of other characters one `_`."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


class QuestionPartDraft(RoleOutput):
    key: str  # snake_case, unique in the plan
    text: str  # the question's own words for the part
    terms: list[str]  # search terms as filings and calls write them (1 to 12; 3 to 12 asked)
    layer: str | None  # its supply-chain layer, when the part names one

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        key = snake_case(value)
        if not key:
            raise ValueError("a part's key must hold a letter or a digit")
        return key

    @field_validator("terms")
    @classmethod
    def _terms(cls, value: list[str]) -> list[str]:
        terms = list(dict.fromkeys(term.strip() for term in value if term.strip()))
        if not 1 <= len(terms) <= MAX_TERMS:
            raise ValueError(f"a part has 1 to {MAX_TERMS} terms (given: {len(terms)})")
        return terms


class StepFocus(RoleOutput):
    step: str  # an argument step's key
    focus: str  # what the step must establish for this question, in its terms


class QuestionPlanDraft(RoleOutput):
    parts: list[QuestionPartDraft]
    step_focus: list[StepFocus]

    @model_validator(mode="before")
    @classmethod
    def _focus_as_written(cls, data: Any) -> Any:
        """`step_focus` written as an object keyed by step, as the request's wording invites,
        read as the schema's list; null as empty."""
        if not isinstance(data, dict):
            return data
        answer = dict(cast(dict[str, Any], data))
        focus = answer.get("step_focus")
        if focus is None and "step_focus" in answer:
            answer["step_focus"] = []
        elif isinstance(focus, dict):
            answer["step_focus"] = [
                {"step": step, "focus": text}
                for step, text in cast(dict[str, Any], focus).items()
                if isinstance(text, str)
            ]
        return answer

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if not MIN_PARTS <= len(self.parts) <= MAX_PARTS:
            raise ValueError(
                f"the plan has {MIN_PARTS} to {MAX_PARTS} parts (given: {len(self.parts)})"
            )
        keys = [part.key for part in self.parts]
        if len(set(keys)) != len(keys):
            raise ValueError(f"each part's key is unique (given: {', '.join(keys)})")
        return self


QUESTION_PLANNER = Role(
    name="question_planner",
    prompt=Prompt.load(PROMPTS_DIR, "question_plan", QUESTION_PLANNER_PROMPT_VERSION),
    request=QuestionPlannerRequest,
    response=QuestionPlanDraft,
    max_output_tokens=2048,
)
QUESTION_PLANNER_VERSION = f"{QUESTION_PLANNER.prompt.name}.v{QUESTION_PLANNER.prompt.version}"
