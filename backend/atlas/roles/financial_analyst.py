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
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

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
    layer: str


class FinancialAnalystRequest(_Request):
    theme_id: str
    research_question: str
    as_of: str
    inputs: list[AnalystInput]
    companies: list[AnalystCompany]
    claims: list[AnalystClaim]


class ProposedInput(RoleOutput):
    name: InputName
    kind: Literal["sourced", "estimated", "missing"]
    observation_id: str | None
    assertion_id: str | None
    basis: str | None
    low: str | None
    base: str | None
    high: str | None


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
    max_output_tokens=4096,
)
