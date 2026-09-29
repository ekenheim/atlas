"""The Investigator role: propose span-backed Claims from quoted passages (spec "Relationships").

The request names the known companies (by ID and the names texts use for them), the predicate
whitelist with each predicate's direction, the layer taxonomy and the passages. The passages'
text is sent as quoted, low-trust `retrieved_data` (one item per passage, `id` = passage ID).
Each Claim names its passage and the exact quote as character offsets into that passage's
text; Atlas turns those into offsets of the Source Version's parsed text and checks the span
(`atlas.claims`). The response schema leaves `predicate` and `layer` as strings, so an
off-whitelist proposal is recorded as a rejected Claim with its reason instead of failing
the whole call.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

INVESTIGATOR_PROMPT_VERSION = 1

# An Investigator Claim quotes a source; an agent's own inference is never a Claim.
ClaimEpistemicType = Literal["direct_source_statement", "company_claim", "third_party_report"]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class KnownCompany(_Request):
    company_id: str
    names: list[str]


class PredicateDefinition(_Request):
    name: str
    object: Literal["company", "product"]
    reads: str


class LayerOption(_Request):
    name: str
    covers: str


class PassageInfo(_Request):
    passage_id: str
    source_version_id: str
    filer_company_id: str | None  # whose document it is: "we"/"our" in it means this company
    title: str
    section: str


class InvestigatorRequest(_Request):
    question: str | None
    companies: list[KnownCompany]
    predicates: list[PredicateDefinition]
    layers: list[LayerOption]
    passages: list[PassageInfo]


class ProposedClaim(RoleOutput):
    passage_id: str
    subject_company_id: str
    predicate: str
    object_company_id: str | None
    object_text: str | None
    product: str | None
    layer: str
    quote: str
    quote_start: int
    quote_end: int
    epistemic_type: ClaimEpistemicType


class InvestigatorClaims(RoleOutput):
    claims: list[ProposedClaim]


INVESTIGATOR = Role(
    name="investigator",
    prompt=Prompt.load(PROMPTS_DIR, "investigator", INVESTIGATOR_PROMPT_VERSION),
    request=InvestigatorRequest,
    response=InvestigatorClaims,
    max_output_tokens=4096,
)
