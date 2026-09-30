"""The Reviewer role: judge proposed Relationships from their quotes (spec "Relationships",
"Review").

A separate LLM call from the Investigator's, with its own prompt and schema. Each item is one
Assertion as a proposed edge: subject, predicate (with the direction it reads in), object,
product and layer, plus the source it quotes. The quote and a window of text around it are
sent as quoted, low-trust `retrieved_data` (`<item_id>:quote` and `<item_id>:context`), never
in the request. For each item the Reviewer answers whether the quote establishes the edge
(`verdict`), whether it states the direction proposed (`direction`) and whether the layer is
right (`layer`, with the layer it should be when not). Atlas combines the answer with its
deterministic checks (`atlas.relationships`); only a confirmation in every part can make a
Relationship machine-reviewed.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput
from atlas.roles.investigator import LayerOption

REVIEWER_PROMPT_VERSION = 2  # v2: product objects and the company-level bottleneck predicates

Verdict = Literal["confirmed", "rejected", "uncertain"]
Direction = Literal["as_proposed", "reversed", "undirected", "not_stated"]
LayerVerdict = Literal["correct", "wrong", "unclear"]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EdgeParty(_Request):
    company_id: str
    names: list[str]


class EdgeSource(_Request):
    source_version_id: str
    title: str
    publisher: str
    form_type: str | None
    source_tier: str
    filer_company_id: str | None  # whose document it is: "we"/"our" in it means this company


class EdgeToReview(_Request):
    item_id: str
    subject: EdgeParty
    predicate: str
    reads: str  # what "<subject> <predicate> <object>" means, direction included
    object_company: EdgeParty | None
    object_text: str | None
    product: str | None
    layer: str
    source: EdgeSource


class ReviewerRequest(_Request):
    layers: list[LayerOption]
    items: list[EdgeToReview]


class EdgeReview(RoleOutput):
    item_id: str
    verdict: Verdict
    direction: Direction
    layer: LayerVerdict
    suggested_layer: str | None
    reasoning: str


class ReviewerVerdicts(RoleOutput):
    reviews: list[EdgeReview]


REVIEWER = Role(
    name="reviewer",
    prompt=Prompt.load(PROMPTS_DIR, "reviewer", REVIEWER_PROMPT_VERSION),
    request=ReviewerRequest,
    response=ReviewerVerdicts,
    max_output_tokens=4096,
)
