"""The Research Editor role (spec §7.1): an investigation's accepted Claims in, a draft
research card out.

The request lists the accepted Claims (their resolved subject, predicate and object, and the
Source Version each quotes) and the investigation's Tier C leads; each Claim's quote and each
lead's snippet go as quoted, low-trust `retrieved_data` (`id` = the claim or lead ID). The
Editor answers with findings, each citing the Claims it rests on, open questions, and whether
the Claims answer the question. Code, not the model, decides what a finding may cite: a
finding citing no accepted Claim of the investigation is dropped as unsupported, and every
cited Claim's quote, span and Source Version are filled in by code (atlas.investigations).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

EDITOR_PROMPT_VERSION = 1


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


class EditorRequest(_Request):
    theme_id: str
    theme_title: str
    research_question: str
    claims: list[EditorClaim]
    leads: list[EditorLead]
    disproven_premises: list[str]  # what the researcher has ruled out; don't rely on it


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
