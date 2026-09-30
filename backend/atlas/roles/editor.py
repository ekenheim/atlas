"""The Research Editor role (spec §7.1): an investigation's accepted Claims in, a draft
research card out; and, when the researcher saves the investigation, a Hypothesis draft
(`HYPOTHESIS_EDITOR`, below).

The request lists the accepted Claims (their resolved subject, predicate and object, and the
Source Version each quotes), the investigation's Tier C leads and the Skeptic's accepted
counterevidence; each Claim's quote, each lead's snippet and each counterevidence quote go as
quoted, low-trust `retrieved_data` (`id` = the claim, lead or counterevidence ID). The
Editor answers with findings, each citing the Claims it rests on, open questions, and whether
the Claims answer the question. Code, not the model, decides what a finding may cite: a
finding citing no accepted Claim of the investigation is dropped as unsupported, and every
cited Claim's quote, span and Source Version are filled in by code (atlas.investigations).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

EDITOR_PROMPT_VERSION = 3  # v2: counterevidence (ticket 15); v3: the bottleneck method


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EditorClaim(_Request):
    claim_id: str
    subject: str  # the subject company's name
    predicate: str
    object: str  # the object company's name, or the product/material/technology named
    product: str | None
    layer: str
    epistemic_type: str
    source_title: str
    source_version_id: str


class EditorLead(_Request):
    lead_id: str
    title: str
    url: str


class EditorCounterevidence(_Request):
    """The Skeptic's accepted counterevidence, as the Editors are sent it (its quote goes as
    retrieved data). Never citable as a finding's claim."""

    counterevidence_id: str
    checklist_item: str
    subject: str
    statement: str
    contradicts_claim_ids: list[str]
    independent: bool  # its Evidence Family is none of the supporting Claims'
    source_title: str


class EditorRequest(_Request):
    theme_id: str
    theme_title: str
    research_question: str
    claims: list[EditorClaim]
    leads: list[EditorLead]
    counterevidence: list[EditorCounterevidence]
    disproven_premises: list[str]  # what the researcher or the Skeptic ruled out


class EditorFinding(RoleOutput):
    statement: str
    claim_ids: list[str]
    limitations: list[str]
    open_questions: list[str]


class ResearchCardDraft(RoleOutput):
    findings: list[EditorFinding]
    open_questions: list[str]
    verdict: Literal["answered", "needs_review"]


EDITOR = Role(
    name="editor",
    prompt=Prompt.load(PROMPTS_DIR, "editor", EDITOR_PROMPT_VERSION),
    request=EditorRequest,
    response=ResearchCardDraft,
    max_output_tokens=4096,
)


# --- the Hypothesis draft (spec §5.6, §8.1) ------------------------------------------------------

HYPOTHESIS_EDITOR_PROMPT_VERSION = 3  # v2: contradictions (ticket 15); v3: the bottleneck method


class CardFindingSummary(_Request):
    """A research card finding as the Hypothesis Editor is sent it."""

    statement: str
    claim_ids: list[str]
    limitations: list[str]
    open_questions: list[str]


class HypothesisEditorRequest(_Request):
    theme_id: str
    theme_title: str
    research_question: str
    card_findings: list[CardFindingSummary]
    card_open_questions: list[str]
    claims: list[EditorClaim]
    contradictions: list[EditorCounterevidence]
    disproven_premises: list[str]


class Mechanism(RoleOutput):
    demand_driver: str | None
    possible_constraint: str | None
    economic_capture_question: str | None


class HypothesisDraft(RoleOutput):
    thesis_statement: str
    mechanism: Mechanism
    measurable_predictions: list[str]
    catalysts: list[str]
    falsifiers: list[str]
    required_evidence: list[str]
    alternative_explanations: list[str]
    unresolved_questions: list[str]
    findings: list[EditorFinding]


# The same Editor role (its calls are recorded as `editor`), with its own versioned prompt.
HYPOTHESIS_EDITOR = Role(
    name="editor",
    prompt=Prompt.load(PROMPTS_DIR, "editor-hypothesis", HYPOTHESIS_EDITOR_PROMPT_VERSION),
    request=HypothesisEditorRequest,
    response=HypothesisDraft,
    max_output_tokens=4096,
)
