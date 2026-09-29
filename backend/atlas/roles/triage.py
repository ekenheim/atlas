"""The Triage role (ticket 30): which sections of a new Source Version are worth retaining.

The request carries the document's metadata, its company's themes (the bottleneck questions)
and the sections to decide by anchor and heading; each section's opening (its first
`triage_excerpt_chars` characters) is sent as quoted, low-trust `retrieved_data` whose `id`
is the anchor. The prompt file is the rubric: its version is the rubric version recorded
with every decision (`TRIAGE_RUBRIC_VERSION`).
"""

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

TRIAGE_PROMPT_VERSION = 1

TriageCategory = Literal[
    "supplier_customer",
    "capacity",
    "qualification_design_win",
    "supply_pricing",
    "substitutes_second_source",
    "dilution_financing",
    "segment_guidance",
    "material_risk_change",
    "boilerplate",
    "other",
]
TRIAGE_CATEGORIES: tuple[str, ...] = get_args(TriageCategory)
TriageVerdict = Literal["retain", "skip"]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TriageTheme(_Request):
    theme_id: str
    title: str
    description: str


class TriageDocument(_Request):
    source_version_id: str
    company: str | None
    title: str
    form_type: str | None
    document_type: str | None
    provider: str
    source_type: str
    available_at: str


class TriageSection(_Request):
    anchor: str
    heading: str | None
    length: int  # the whole section's length in characters; the role sees its opening only


class TriageRequest(_Request):
    document: TriageDocument
    themes: list[TriageTheme]
    sections: list[TriageSection]


class TriageSectionDecision(RoleOutput):
    anchor: str
    decision: TriageVerdict
    category: TriageCategory
    reason: str


class TriageDecisions(RoleOutput):
    decisions: list[TriageSectionDecision]


TRIAGE = Role(
    name="triage",
    prompt=Prompt.load(PROMPTS_DIR, "triage", TRIAGE_PROMPT_VERSION),
    request=TriageRequest,
    response=TriageDecisions,
    max_output_tokens=2048,
)
TRIAGE_RUBRIC_VERSION = f"{TRIAGE.prompt.name}.v{TRIAGE.prompt.version}"
