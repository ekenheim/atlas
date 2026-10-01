"""The Skeptic role (spec "Research workflow"; build plan §7.1 Skeptical Reviewer): an
independent search for counterevidence, driven by the bear checklist.

The Skeptic makes two kinds of call, both recorded as `skeptic`:

- **The plan** (`SKEPTIC_PLAN`): the research question, the checklist, the Claims the
  investigation accepted (what to challenge, as request fields, never as quoted data) and the
  seed companies in, its own web search queries (each with an optional `filing_phrase` for
  EDGAR full-text search, v3; a specific one, v4) out. It chooses no document (v5,
  memory-directed reading ticket 07): what the Skeptic reads is where Memory points for each
  checklist item (atlas.investigations.skeptic), so an empty plan leaves it reading.
- **The reading** (`SKEPTIC`): passages of the Source Versions code chose in (each passage's
  text as quoted, low-trust `retrieved_data`), counterevidence out: each item names its
  passage, the checklist item, the company it is about, the exact quote as offsets into the
  passage and its **kind** (v3): a `contradiction` names the supporting Claims it contradicts
  and `how` (it denies, limits or dates their statement) and may name a company premise it
  disproves; `bear_context` is a checklist item about a company, attached to no Claim. A
  quoted table row also states its figure's name and period. Code checks every item
  (atlas.investigations.skeptic).

**The bear checklist** (spec user story 31; research note M10 and V10): substitutes, second
sources, capacity additions, the inventory cycle, dilution and financing (S-3 shelf
registrations, 424B prospectus supplements, at-the-market programs, convertibles), and
customer concentration. Each item has the words Memory is asked about it for a company
(`recall`; `bear_query` phrases the query) and a small pattern list (`cues`) that tells the
Skeptic which items a passage's text touches on: a hint, never a judgement.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput
from atlas.roles.scout import filing_phrase_required

# v2: the bottleneck method; v3: each item is a contradiction of a named Claim or bear
# context, never both (memory-directed reading, ticket 03)
SKEPTIC_PROMPT_VERSION = 3
# v3: it must choose archived documents from the catalog, and why (pilot fix 06); a filing
# phrase per query for EDGAR full-text search (pilot fix 12)
# v4: the filing phrase is specific (memory-directed reading, ticket 04)
# v5: queries only; the plan chooses no document (memory-directed reading, ticket 07)
SKEPTIC_PLAN_PROMPT_VERSION = 5
# A bear-checklist query names at most this many of the Claims' objects.
BEAR_QUERY_OBJECTS = 4


@dataclass(frozen=True)
class ChecklistItem:
    name: str
    covers: str
    recall: str  # the words Memory is asked about the item for a company (`bear_query`)
    cues: tuple[re.Pattern[str], ...]


def _cues(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


BEAR_CHECKLIST: tuple[ChecklistItem, ...] = (
    ChecklistItem(
        "substitutes",
        "a substitute product, material or technology that could replace what the thesis"
        " depends on, or a customer able to make it themselves",
        "substitute products or technologies, customers making it in-house",
        _cues(
            r"\bsubstitut\w*",
            r"\balternative (?:technolog|product|material)\w*",
            r"\bdisplac\w*",
            r"\bother technologies\b",
            r"\bbackward[- ]integrat\w*",
            r"\binsourc\w*",
        ),
    ),
    ChecklistItem(
        "second_sources",
        "another qualified supplier exists or is being qualified: the input is not sole-sourced",
        "second source, alternative or additional qualified suppliers, sole or single source"
        " supply",
        _cues(
            r"\bsecond[- ]sources?\b",
            r"\bmultiple sources\b",
            r"\balternat\w* (?:suppliers?|sources?|vendors?)\b",
            r"\bdual[- ]sourc\w*",
            r"\b(?:sole|single)[- ]sources?\b",
            r"\bqualif\w* (?:an? )?(?:second|additional|new|alternative) (?:suppliers?|sources?)",
        ),
    ),
    ChecklistItem(
        "capacity_additions",
        "capacity being added (by the company, its competitors or its suppliers) that could"
        " relieve the constraint",
        "capacity additions, new fabs and facilities, manufacturing expansion, ramp-up",
        _cues(
            r"\bcapacity\b",
            r"\bnew (?:fabs?|facilit(?:y|ies)|plants?|lines?)\b",
            r"\bexpan(?:d|ds|ded|ding|sion)\b[^.\n]{0,60}\b(?:manufactur|production|facilit|fab)",
            r"\bramp(?:s|ed|ing)?[- ]up\b",
        ),
    ),
    ChecklistItem(
        "inventory_cycle",
        "inventory build-up, excess or obsolete inventory, or double ordering that could mimic"
        " demand",
        "inventory build-up, excess and obsolete inventory, double ordering, destocking",
        _cues(
            r"\binventor(?:y|ies)\b",
            r"\bexcess (?:and|or) obsolete\b",
            r"\bdouble[- ]order\w*",
            r"\bdestock\w*",
            r"\bchannel stuff\w*",
        ),
    ),
    ChecklistItem(
        "dilution_financing",
        "share issuance, convertible notes, shelf registrations (Form S-3), prospectus"
        " supplements (424B), at-the-market programs or other financing that dilutes holders",
        "share issuance, convertible notes, shelf registration, at-the-market offering, dilution",
        _cues(
            r"\bdilut\w*",
            r"\bconvertible\b",
            r"\bat[- ]the[- ]market\b",
            r"\bATM (?:program|offering|facility|agreement)s?\b",
            r"\bshelf registration\b",
            r"\bForm S-3\b",
            r"\b424\(?B\)?\(?\d?\)?",
            r"\b(?:equity|stock|share) offerings?\b",
            r"\bissued - [\d,]+ shares\b",
            r"\bequitiz\w*",
        ),
    ),
    ChecklistItem(
        "customer_concentration",
        "revenue depends on a few customers, whose loss, insourcing or pricing power would hurt",
        "customer concentration, largest customers, share of revenue from a few customers",
        _cues(
            r"\bcustomer concentration\b",
            r"\b(?:largest|significant|major|key|large) customers?\b",
            r"\bsmall number of customers\b",
            r"\b10% of (?:our )?(?:total )?(?:net )?revenues?\b",
            r"\bconcentrat\w* of (?:our )?(?:customers|revenues?)\b",
        ),
    ),
)
CHECKLIST_NAMES: tuple[str, ...] = tuple(item.name for item in BEAR_CHECKLIST)


def checklist_matches(text: str) -> list[str]:
    """The checklist items whose cues `text` matches, in checklist order."""
    return [item.name for item in BEAR_CHECKLIST if any(c.search(text) for c in item.cues)]


def bear_query(item: ChecklistItem, company: str, objects: Sequence[str] = ()) -> str:
    """What Memory is asked about a checklist item for a company: the company's name, the
    item's words and the objects of the accepted Claims that name the company (the other
    party, the object text, the product: at most `BEAR_QUERY_OBJECTS`, each once, in the
    Claims' order). Deterministic text, no model: "Coherent: customer concentration, largest
    customers, share of revenue from a few customers; NVIDIA; advanced lasers"."""
    named: list[str] = []
    for each in objects:
        name = " ".join(each.split())
        if name and name.casefold() not in {seen.casefold() for seen in named}:
            named.append(name)
    return "; ".join([f"{company}: {item.recall}", *named[:BEAR_QUERY_OBJECTS]])


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChecklistOption(_Request):
    name: str
    covers: str


class SupportingClaim(_Request):
    """A Claim the investigation accepted: what the Skeptic challenges, never a witness."""

    claim_id: str
    subject: str
    predicate: str
    object: str
    source_version_id: str
    source_title: str


class SeedCompany(_Request):
    company_id: str
    names: list[str]


class SkepticPlanRequest(_Request):
    research_question: str
    theme_id: str
    theme_title: str
    checklist: list[ChecklistOption]
    supporting_claims: list[SupportingClaim]
    companies: list[SeedCompany]
    max_queries: int


class PlannedQuery(RoleOutput):
    model_config = ConfigDict(json_schema_extra=filing_phrase_required)

    query: str
    checklist_item: str
    # The exact phrase to search in SEC filings (EDGAR full-text search), or None.
    filing_phrase: str | None = None


class SkepticPlan(RoleOutput):
    queries: list[PlannedQuery]


class KnownCompany(_Request):
    company_id: str
    names: list[str]


class PremiseOption(_Request):
    key: str
    statement: str


class PassageInfo(_Request):
    passage_id: str
    source_version_id: str
    filer_company_id: str | None  # whose document it is: "we"/"our" in it means this company
    title: str
    section: str
    checklist_items: list[str]  # the checklist items whose cues the passage matches (or none)


class SkepticRequest(_Request):
    research_question: str
    checklist: list[ChecklistOption]
    companies: list[KnownCompany]
    supporting_claims: list[SupportingClaim]
    premises: list[PremiseOption]  # the company premises counterevidence may disprove
    passages: list[PassageInfo]


CounterevidenceEpistemicType = Literal[
    "direct_source_statement", "company_claim", "third_party_report"
]


# A contradiction speaks against a named supporting Claim's statement; bear context is a
# checklist item about a company, attached to no Claim.
CounterevidenceKind = Literal["contradiction", "bear_context"]
# How a contradiction contradicts: the statement is not so, holds only in part, or held at
# another time.
ContradictionHow = Literal["denies", "limits", "dates"]


class ProposedCounterevidence(RoleOutput):
    passage_id: str
    kind: CounterevidenceKind
    checklist_item: str
    subject_company_id: str
    statement: str
    quote: str
    quote_start: int
    quote_end: int
    epistemic_type: CounterevidenceEpistemicType
    contradicts_claim_ids: list[str]  # a contradiction's Claims; empty for bear context
    how: ContradictionHow | None  # a contradiction's; None for bear context
    # The figure a quoted table row states and its period; None for any other quote.
    figure_name: str | None
    figure_period: str | None
    disproves_premise: str | None


class SkepticFindings(RoleOutput):
    counterevidence: list[ProposedCounterevidence]


SKEPTIC_PLAN = Role(
    name="skeptic",
    prompt=Prompt.load(PROMPTS_DIR, "skeptic-plan", SKEPTIC_PLAN_PROMPT_VERSION),
    request=SkepticPlanRequest,
    response=SkepticPlan,
    max_output_tokens=2048,
)

SKEPTIC = Role(
    name="skeptic",
    prompt=Prompt.load(PROMPTS_DIR, "skeptic", SKEPTIC_PROMPT_VERSION),
    request=SkepticRequest,
    response=SkepticFindings,
    max_output_tokens=4096,
)
