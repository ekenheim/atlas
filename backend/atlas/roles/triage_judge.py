"""The triage judge (ticket 33): the full-section reading that audits what triage skipped.

Retention triage reads a section in windows, at most a few of them (`atlas.retention.triage`),
so a long section is only sampled. The judge reads a skipped section **whole**: the same
rubric's criteria (triage rubric v2), but with the section's entire text as quoted, low-trust
`retrieved_data`, one section per call. A section longer than `triage_judge_max_chars` is
read in overlapping chunks, one call each (`chunk` of `chunks`), and the section is `retain`
when any chunk is (`atlas.retention.audit`). Its prompt is versioned like every role's
(`TRIAGE_JUDGE_RUBRIC_VERSION`, recorded with every audit).
"""

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput
from atlas.roles.triage import TriageCategory, TriageDocument, TriageTheme, TriageVerdict

TRIAGE_JUDGE_PROMPT_VERSION = 1


class TriageJudgeSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    anchor: str
    heading: str | None
    length: int  # the whole section's length in characters
    chunk: int  # which chunk of the section the retrieved text is, 1-based
    chunks: int  # how many chunks the section was split into (1: the whole section)


class TriageJudgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document: TriageDocument
    themes: list[TriageTheme]
    section: TriageJudgeSection


class TriageJudgement(RoleOutput):
    decision: TriageVerdict
    category: TriageCategory
    reason: str


TRIAGE_JUDGE = Role(
    name="triage_judge",
    prompt=Prompt.load(PROMPTS_DIR, "triage_judge", TRIAGE_JUDGE_PROMPT_VERSION),
    request=TriageJudgeRequest,
    response=TriageJudgement,
    max_output_tokens=512,
)
TRIAGE_JUDGE_RUBRIC_VERSION = f"{TRIAGE_JUDGE.prompt.name}.v{TRIAGE_JUDGE.prompt.version}"
