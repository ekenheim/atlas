"""The Financial Analyst role (spec Phase 4 "Roles", Phase 5 "Scenario"; §8.2): proposes the
inputs of a scenario's assumption table. It never computes a scenario: the scenario math is a
pure function in code (atlas.scenarios).

The request names each company to quantify with its as-of XBRL figures (each an
observation ID with its concept, period, unit and value), the investigation's accepted
Claims (each with its Assertion ID) and the inputs the model takes; each Claim's quote goes
as quoted, low-trust `retrieved_data` (`id` = the Assertion ID). The Analyst answers with
one proposed assumption table per company it can quantify; every input is `sourced` (an
observation ID or an Assertion ID from the request), `estimated` (with a written basis) or
`missing`. Code, not the model, decides what stands: an input citing what it wasn't sent,
whose values don't match the observation, or that has a value but neither a source nor a
basis is rejected and becomes missing (atlas.scenarios.analyst).

An input is read in the forms MiniMax writes it (`ProposedInput._as_the_model_writes_it`): its
optional fields left out, or its `kind` naming what sources it (`"assertion"`,
`"assertion_id"`) instead of `sourced`. On pilot question 2 (0.5.3, 2026-10-07) one such
input quarantined the whole answer twice, and the investigation lost its card
(bottleneck-argument ticket 07).
"""

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, model_validator

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput
from atlas.scenarios.model import InputName, Measure

FINANCIAL_ANALYST_PROMPT_VERSION = 1


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalystInput(_Request):
    name: InputName
    measure: Measure
    meaning: str
    xbrl_allowed: bool  # whether an XBRL observation may source it


class AnalystFigure(_Request):
    observation_id: str
    metric: str
    label: str
    concept: str | None
    period_start: str | None
    period_end: str
    unit: str
    value: str  # a plain decimal string, as filed


class AnalystCompany(_Request):
    company_id: str
    name: str
    figures: list[AnalystFigure]


class AnalystClaim(_Request):
    assertion_id: str
    subject: str
    predicate: str
    object: str
    product: str | None
    layer: str | None  # null: the Claim's quote names no layer


class FinancialAnalystRequest(_Request):
    theme_id: str
    research_question: str
    as_of: str
    inputs: list[AnalystInput]
    companies: list[AnalystCompany]
    claims: list[AnalystClaim]


_OPTIONAL = ("observation_id", "assertion_id", "basis", "low", "base", "high")
# A `kind` naming the source's type instead of saying the input is sourced, by the field that
# then holds its ID.
_SOURCE_KINDS = {
    "assertion": "assertion_id",
    "assertion_id": "assertion_id",
    "claim": "assertion_id",
    "fact": "assertion_id",
    "observation": "observation_id",
    "observation_id": "observation_id",
    "xbrl": "observation_id",
}


class ProposedInput(RoleOutput):
    name: InputName
    kind: Literal["sourced", "estimated", "missing"]
    observation_id: str | None
    assertion_id: str | None
    basis: str | None
    low: str | None
    base: str | None
    high: str | None

    @model_validator(mode="before")
    @classmethod
    def _as_the_model_writes_it(cls, data: Any) -> Any:
        """An optional field left out is null; a `kind` naming the source's type is `sourced`
        when the input gives that ID, else `missing` (code then decides what stands, as for
        any sourced input). The strict schema sent to the model is unchanged."""
        if not isinstance(data, dict):
            return data
        answer = dict(cast(dict[str, Any], data))
        for key in _OPTIONAL:
            answer.setdefault(key, None)
        kind = answer.get("kind")
        if isinstance(kind, str) and kind.strip().lower() in _SOURCE_KINDS:
            field = _SOURCE_KINDS[kind.strip().lower()]
            answer["kind"] = "sourced" if answer.get(field) else "missing"
        return answer


class ProposedScenario(RoleOutput):
    company_id: str
    product: str
    currency: str
    inputs: list[ProposedInput]


class ScenarioProposal(RoleOutput):
    scenarios: list[ProposedScenario]


FINANCIAL_ANALYST = Role(
    name="financial_analyst",
    prompt=Prompt.load(PROMPTS_DIR, "financial-analyst", FINANCIAL_ANALYST_PROMPT_VERSION),
    request=FinancialAnalystRequest,
    response=ScenarioProposal,
    max_output_tokens=6144,
)
