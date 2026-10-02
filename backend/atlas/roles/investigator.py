"""The Investigator role: propose span-backed Claims from quoted passages (spec "Relationships").

The request names the known companies (by ID and the names texts use for them), the predicate
whitelist with each predicate's direction, the layer taxonomy and the passages. The passages'
text is sent as quoted, low-trust `retrieved_data` (one item per passage, `id` = passage ID).
Each Claim names its passage and the exact quote as character offsets into that passage's
text; Atlas turns those into offsets of the Source Version's parsed text and checks the span
(`atlas.claims`). A company object is one of the known companies (`object_company_id`) or a
company the quote names that isn't among them (`object_name`, the name as quoted), which
Atlas resolves to a counterparty company or rejects (`atlas.counterparties`). The response
schema leaves `predicate` and `layer` as strings, so an
off-whitelist proposal is recorded as a rejected Claim with its reason instead of failing
the whole call. `layer` may be null: a Claim names a layer only when its quote does, and Atlas
drops a proposed layer the quote and the object don't name (`atlas.claims.layer_term`).
`object_text` may be null for one product predicate: a `capacity_constrained` Claim about the
filer's own supply, whose quote names no product (`atlas.claims.company_level`).
"""

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, model_validator

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

# v2: the bottleneck method; v3: company-level bottleneck facts; v4: a company object outside
# the known companies, by name (counterparty companies); v5: the layer from the quote's named
# object, no generic materials/components Claims, one clause (pilot-fixes ticket 09); v6: the
# filer's impersonal sentences and slide bullets, language of constraint, `owns` from the holder
# to the issuer (memory-directed reading ticket 02); v7: the layer may be left out, and is kept
# only when the quote or the object names it (memory-directed reading ticket 08); v8: a
# constraint on the company's own supply is proposed with no object and no layer
# (memory-directed reading ticket 09); v9: the answer's twelve fields listed, and no
# `subject_name` or `claim_id` (the fifth pilot run's extra fields), an analyst's question in a
# transcript is context, not the company's statement (pilot-fixes tickets 26 and 22)
INVESTIGATOR_PROMPT_VERSION = 9

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
    # The words Atlas takes as naming the layer: a Claim keeps a layer only when one of them
    # is in its quote or object text (`atlas.claims.LAYER_TERMS`).
    terms: list[str]


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
    object_name: str | None  # a company object outside `request.companies`, as the quote names it
    # A product object, as the quote names it; null for a company object, and for a
    # company-level `capacity_constrained` Claim (the quote names no product)
    object_text: str | None
    product: str | None
    layer: str | None  # null: the quote names nothing of a particular layer
    quote: str
    quote_start: int
    quote_end: int
    epistemic_type: ClaimEpistemicType

    @model_validator(mode="before")
    @classmethod
    def _object_fields_it_needs_no_value_for(cls, data: Any) -> Any:
        """A Claim gives its object one way: a known company, a quoted name or product text.
        The strict schema still asks for all three, but one left out where the Claim gives
        its object another way, or where it is a `capacity_constrained` Claim (which may have
        no object: `atlas.claims.company_level`), is null, as the Claim checks read it, not a
        validation error (pilot-fixes ticket 26). With none of the three given, a Claim of
        any other predicate still fails validation and is repaired."""
        if not isinstance(data, dict):
            return data
        claim = cast(dict[str, Any], data)
        absent = [name for name in _OBJECT_FIELDS if name not in claim]
        given = any(claim.get(name) is not None for name in _OBJECT_FIELDS)
        if absent and (given or claim.get("predicate") == "capacity_constrained"):
            return claim | dict.fromkeys(absent)
        return claim


_OBJECT_FIELDS = ("object_company_id", "object_name", "object_text")


class InvestigatorClaims(RoleOutput):
    claims: list[ProposedClaim]


INVESTIGATOR = Role(
    name="investigator",
    prompt=Prompt.load(PROMPTS_DIR, "investigator", INVESTIGATOR_PROMPT_VERSION),
    request=InvestigatorRequest,
    response=InvestigatorClaims,
    max_output_tokens=4096,
)
