"""The finding judge (bottleneck-argument ticket 04): the trust gate's second half.

The grounding check (`atlas.investigations.grounding`) holds a finding's names, figures and
quoted phrases to the Claims it cites; it can't read what a sentence does with them. The judge
does: it compares one finding (its statement and limitations) with the exact quotes it cites
and answers `supported` or `misstated`, with the words that go beyond the quotes (`beyond`),
what kind of misstatement each is (`kinds`) and why (`reason`). What it looks for is what the
pilot's verdict found on four of five cards (pilot fix 34): tense and status (an agreement, a
plan, a development, a qualification in progress or a hedge stated as present fact),
direction (who supplies, owns or buys from whom), figures and dates other than the quotes'
("six to eight weeks" is not "four to eight weeks"), and two facts merged into one claim
neither quote makes.

One finding per call: the request carries the finding and the cited Claims' metadata (by the
short reference the Editor used, `c1`, ...), and the retrieved data each Claim's exact quote
(`id` = its reference), quoted and low-trust like every role's. A misstated finding is
rewritten once by the Editor (`atlas.roles.editor.EDITOR_REVISE`) with the judge's reason and
judged again (`atlas.investigations.meaning`).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

FINDING_JUDGE_PROMPT_VERSION = 2

# How a finding goes beyond its quotes.
MisstatementKind = Literal[
    "tense_or_status",  # a plan, agreement, development, qualification or hedge as present fact
    "direction",  # who supplies, owns, buys from or invests in whom
    "figure_or_date",  # a number, unit, period or date other than the quotes'
    "merged",  # two facts joined into one claim no quote makes
    "attribution",  # who said it, or about which company, product or agreement
    "unstated",  # anything else the quotes do not say
]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JudgedClaim(_Request):
    """A cited Claim as the judge is sent it (its exact quote goes as retrieved data)."""

    ref: str  # `c1`, `c2`, ...: the retrieved quote's `id`
    subject: str  # the subject company's name
    predicate: str
    object: str
    epistemic_type: str
    source_title: str


class JudgedFinding(_Request):
    statement: str
    limitations: list[str]
    claim_refs: list[str]


class FindingJudgeRequest(_Request):
    research_question: str
    finding: JudgedFinding
    claims: list[JudgedClaim]


class FindingJudgement(RoleOutput):
    verdict: Literal["supported", "misstated"]
    # The finding's own words that go beyond the quotes, as it writes them (empty: supported).
    beyond: list[str]
    kinds: list[MisstatementKind]
    reason: str  # why, citing the quotes' own words


FINDING_JUDGE = Role(
    name="finding_judge",
    prompt=Prompt.load(PROMPTS_DIR, "finding_judge", FINDING_JUDGE_PROMPT_VERSION),
    request=FindingJudgeRequest,
    response=FindingJudgement,
    max_output_tokens=2048,
)
FINDING_JUDGE_VERSION = f"{FINDING_JUDGE.prompt.name}.v{FINDING_JUDGE.prompt.version}"
