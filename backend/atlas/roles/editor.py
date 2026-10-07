"""The Research Editor role (spec §7.1): an investigation's accepted Claims in, a draft
research card out; and, when the researcher saves the investigation, a Hypothesis draft
(`HYPOTHESIS_EDITOR`, below).

The request lists the accepted Claims (their resolved subject, predicate and object, and the
Source Version each quotes), the investigation's Tier C leads, the Skeptic's accepted
counterevidence in its two kinds, separately (`contradictions` of named Claims, and
`bear_context` about a company, attached to no Claim), and what the investigation searched
and read (the Scout's queries; each Investigator's documents, sections and extraction
outcomes); each Claim's quote, each lead's snippet and each counterevidence quote go as
quoted, low-trust `retrieved_data` (`id` = the Claim's short reference, the lead or the
counterevidence ID). Each Claim goes by a short reference (`c1`, `c2`, ..., in the request's
order), not its 36-character ID (v6: the IDs were most of the answer a multi-hop
investigation's Editor was cut off in). The Editor answers with findings, each citing the
references of the Claims it rests on, open questions, and whether the Claims answer the
question. Code, not the model, decides what a finding may cite: it maps each reference back
to its Claim; a finding citing no accepted Claim of the investigation (or a reference it
wasn't sent) is dropped as unsupported, and every cited Claim's quote, span and Source
Version are filled in by code (atlas.investigations).
A finding's statement says only what its cited Claims say (v7; pilot-fixes ticket 21): code
checks its numbers, names and quoted phrases against them (atlas.investigations.grounding)
and asks the Editor once more for the ungrounded ones (`EDITOR_REGROUND`).
With no accepted Claim the Editor still writes the card: no finding, and open questions for
the next round drawn from what was searched and read (the card's `searched` and `read`
sections are code's, never the model's).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

# v2: counterevidence (ticket 15); v3: the bottleneck method; v4: what was searched and read,
# and a card with no accepted Claim (pilot fix 01); v5: contradictions and bear context,
# separately (memory-directed reading, ticket 03); v6: Claims by short reference (memory
# quality, ticket 16); v7: a finding's statement says only what its cited Claims' quotes say
# (pilot-fixes ticket 21)
EDITOR_PROMPT_VERSION = 7


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EditorClaim(_Request):
    """An accepted Claim as the Hypothesis Editor is sent it (by its ID)."""

    claim_id: str
    subject: str  # the subject company's name
    predicate: str
    object: str  # the object company's name, or the product/material/technology named
    product: str | None
    layer: str | None  # null: the Claim's quote names no layer
    epistemic_type: str
    source_title: str
    source_version_id: str


class EditorCardClaim(_Request):
    """An accepted Claim as the research card's Editor is sent it: by its short reference
    (`c1`, `c2`, ...), which code maps back to the Claim's ID."""

    ref: str
    subject: str  # the subject company's name
    predicate: str
    object: str  # the object company's name, or the product/material/technology named
    product: str | None
    layer: str | None  # null: the Claim's quote names no layer
    epistemic_type: str
    source_title: str
    source_version_id: str


class EditorLead(_Request):
    lead_id: str
    title: str
    url: str


class EditorCounterevidence(_Request):
    """A contradiction the Skeptic found, as the Editors are sent it (its quote goes as
    retrieved data). Never citable as a finding's claim."""

    counterevidence_id: str
    checklist_item: str
    subject: str
    statement: str
    contradicts_claim_ids: list[str]
    independent: bool  # its Evidence Family is none of the supporting Claims'
    source_title: str


class EditorContradiction(_Request):
    """A contradiction as the research card's Editor is sent it: the Claims it names by their
    short references, and how it contradicts them (its quote goes as retrieved data)."""

    counterevidence_id: str
    checklist_item: str
    subject: str
    statement: str
    contradicts_refs: list[str]  # the Claims it names that the Editor is sent
    independent: bool  # its Evidence Family is none of the supporting Claims'
    source_title: str
    how: str | None  # denies, limits or dates the Claims' statement


class EditorBearContext(_Request):
    """Bear context the Skeptic found: a bear-checklist item about a company, attached to no
    Claim (its quote goes as retrieved data). It contradicts no finding; never citable."""

    counterevidence_id: str
    checklist_item: str
    company: str
    statement: str
    # The figure a quoted table row states, and its period (None for any other quote).
    figure_name: str | None
    figure_period: str | None
    source_title: str


class EditorQuery(_Request):
    """A query the Scout searched."""

    query: str
    purpose: str | None


class EditorDocumentRead(_Request):
    """A document an Investigator read, and the sections of the passages it was sent."""

    title: str
    sections: list[str]


class EditorReading(_Request):
    """What one Investigator task read and what came of it (atlas.investigations.coverage)."""

    company: str
    documents: list[EditorDocumentRead]
    documents_dropped: int  # left out by the document budget
    passages: int
    claims_proposed: int
    claims_accepted: int
    rejected: dict[str, int]  # reason code -> count
    detail: str | None  # why it read nothing, if so


class EditorRequest(_Request):
    theme_id: str
    theme_title: str
    research_question: str
    claims: list[EditorCardClaim]
    leads: list[EditorLead]
    contradictions: list[EditorContradiction]  # of the Claims each names
    bear_context: list[EditorBearContext]  # about a company; contradicts no Claim
    disproven_premises: list[str]  # what the researcher or the Skeptic ruled out
    queries: list[EditorQuery]  # what the Scout searched, every round
    read: list[EditorReading]  # what each Investigator read, every round


class EditorFinding(RoleOutput):
    """A finding of the Hypothesis draft (its Claims by ID)."""

    statement: str
    claim_ids: list[str]
    limitations: list[str]
    open_questions: list[str]


class CardFindingDraft(RoleOutput):
    """A finding of the research card's draft: its Claims by short reference."""

    statement: str
    claim_refs: list[str]
    limitations: list[str]
    open_questions: list[str]


class ResearchCardDraft(RoleOutput):
    findings: list[CardFindingDraft]
    open_questions: list[str]
    verdict: Literal["answered", "needs_review"]


# The first call's output cap; an answer cut off at it is asked again with the cap doubled, up
# to `editor_max_output_tokens` (atlas.investigations.tasks).
EDITOR = Role(
    name="editor",
    prompt=Prompt.load(PROMPTS_DIR, "editor", EDITOR_PROMPT_VERSION),
    request=EditorRequest,
    response=ResearchCardDraft,
    max_output_tokens=8192,
)


# --- a finding asked again (pilot-fixes ticket 21) ---------------------------------------------

# A finding whose statement names a number, a name or a quoted phrase none of its cited Claims
# holds (atlas.investigations.grounding) is sent back once, with what wasn't found; the
# answer's statements are checked again.
EDITOR_REGROUND_PROMPT_VERSION = 1


class EditorUngroundedFinding(_Request):
    finding: str  # `f1`, `f2`, ...: how the answer names it
    statement: str
    claim_refs: list[str]
    ungrounded: list[str]  # what none of its cited Claims holds, as the statement writes it


class EditorRegroundRequest(_Request):
    research_question: str
    findings: list[EditorUngroundedFinding]
    claims: list[EditorCardClaim]  # the Claims those findings cite


class RegroundedFinding(RoleOutput):
    finding: str
    statement: str


class RegroundedFindings(RoleOutput):
    findings: list[RegroundedFinding]


# The same Editor role (its calls are recorded as `editor`), with its own versioned prompt.
EDITOR_REGROUND = Role(
    name="editor",
    prompt=Prompt.load(PROMPTS_DIR, "editor-reground", EDITOR_REGROUND_PROMPT_VERSION),
    request=EditorRegroundRequest,
    response=RegroundedFindings,
    max_output_tokens=4096,
)


# --- a finding rewritten after the judge (bottleneck-argument ticket 04) -------------------------

# A finding the finding judge (atlas.roles.finding_judge) found misstated is sent back once,
# with the judge's reason and the words that went beyond its quotes; the rewritten finding is
# checked for grounding and judged again (atlas.investigations.meaning).
EDITOR_REVISE_PROMPT_VERSION = 1


class EditorMisstatedFinding(_Request):
    finding: str  # `f1`, `f2`, ...: how the answer names it
    statement: str
    limitations: list[str]
    claim_refs: list[str]
    beyond: list[str]  # the judge's words that go beyond the quotes, as the finding writes them
    kinds: list[str]
    reason: str  # the judge's reason


class EditorReviseRequest(_Request):
    research_question: str
    findings: list[EditorMisstatedFinding]
    claims: list[EditorCardClaim]  # the Claims those findings cite


class RevisedFinding(RoleOutput):
    finding: str
    statement: str
    limitations: list[str]


class RevisedFindings(RoleOutput):
    findings: list[RevisedFinding]


# The same Editor role (its calls are recorded as `editor`), with its own versioned prompt.
EDITOR_REVISE = Role(
    name="editor",
    prompt=Prompt.load(PROMPTS_DIR, "editor-revise", EDITOR_REVISE_PROMPT_VERSION),
    request=EditorReviseRequest,
    response=RevisedFindings,
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
