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

v3 (pilot 0.5.3's review: the judge missed 17 of 17 narrow overstatements and nothing in its
answer could be checked) shows its basis clause by clause: the statement split into its claims
(`clauses`), each tied to the one cited quote that states it (`ref`) by that quote's own words
copied (`basis`), and code checks every basis occurs in its quote
(`atlas.investigations.meaning.verify_bases`): a `supported` verdict with a clause it can't
verify is a misstatement. A cited Fact (the argument plan) carries how its Reader read it:
`status`, `period`, `quantity` and the Reader's statement (`reading`); a Claim leaves them None.

v4 (R2-04) tells it each quote's date: `source_date`, the day the quote's document became
available. Transcript titles ("Q3 2026") carry none, so the `merged` rule had no dates to
compare; two quotes more than 90 days apart joined as one current statement are `merged`.

v5 (ticket 24) judges a Hypothesis's thesis, and only a thesis: the request's
`finding.thesis` is true, and the thesis's bare hedged proposition ("may be straining ...", no
fact of its own) is a clause with no basis that does not make it misstated; its facts (actors,
figures, scope words) still need theirs. It is its own role definition (`THESIS_JUDGE`, the
same role name, so `ATLAS_LLM_ROLE_MODELS` routes both alike); every other statement (a card
finding, an argument statement, `POST /statements/judge`, a session's Fact or Belief) is
judged by `FINDING_JUDGE`, v4, with a request serialised exactly as before (no `thesis` key).
`judge_role` picks the role from the request.

Ticket 25 sends a transcript quote's speaker beside it (`JudgedClaim.speaker`: name, title and
firm from the paragraph's label), because a statement that names whose words a quote is ("AXT's
VP of business development") can be checked against nothing else. It is a field of the claim's
metadata, not of the quote's text and not of the retrieved-data envelope every role shares. A
filing quote has no `speaker` key at all. The prompts are unchanged (v4 and v5): the key names
the speaker for what it is, and the lead's measurement on the labelled statements decides
whether one sentence is needed (a new version of both roles, never an edit of these).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, model_serializer

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

FINDING_JUDGE_PROMPT_VERSION = 4
# A Hypothesis's thesis (ticket 24): v4 plus one paragraph that applies only to a thesis.
THESIS_JUDGE_PROMPT_VERSION = 5

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


class JudgedSpeaker(_Request):
    """Who says a transcript quote, as its paragraph's label gives it ("Name (Title, Firm)";
    `atlas.claims.speakers`): metadata beside the quote, never part of its text."""

    name: str
    title: str | None
    firm: str | None


class JudgedClaim(_Request):
    """A cited Claim or Fact as the judge is sent it (its exact quote goes as retrieved data)."""

    ref: str  # `c1`, `c2`, ...: the retrieved quote's `id`
    subject: str  # the subject company's name
    predicate: str
    object: str
    epistemic_type: str
    source_title: str
    # The day the quote's document became available (ISO date; a call's or filing's date).
    source_date: str | None = None
    # A Fact's reading by its Reader (the argument plan): its status (`in_effect`, `planned`,
    # `hedged`, `in_development`, ...), period, quantity and statement. None for a Claim.
    status: str | None = None
    period: str | None = None
    # What code resolved the quote's relative phrases to on the document's date (a reading to
    # hold the statement's dates to, beside the quote); null for a Claim or a plain period.
    period_resolved: str | None = None
    quantity: str | None = None
    reading: str | None = None
    # A call or conference transcript's quote: its speaker, so a statement naming whose words
    # they are (a title, a firm) can be held to the paragraph's label (ticket 25). Sent only
    # for a transcript quote: a filing's request is v4's byte for byte.
    speaker: JudgedSpeaker | None = None

    @model_serializer(mode="wrap")
    def _speaker_only_when_known(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.speaker is None:
            data.pop("speaker", None)
        return data


class JudgedFinding(_Request):
    statement: str
    limitations: list[str]
    claim_refs: list[str]
    # True: a Hypothesis's thesis, judged by `THESIS_JUDGE` (v5): its bare hedged proposition
    # needs no basis. Sent only when true, so a finding's request is v4's byte for byte.
    thesis: bool = False

    @model_serializer(mode="wrap")
    def _thesis_only_when_true(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if not self.thesis:
            data.pop("thesis", None)
        return data


class FindingJudgeRequest(_Request):
    research_question: str
    finding: JudgedFinding
    claims: list[JudgedClaim]


class JudgedClause(RoleOutput):
    """One claim of the statement (or a limitation) and the quote words that state it."""

    text: str  # the clause, copied as the finding writes it
    ref: str | None  # the cited reference whose quote states it; None: no quote does
    basis: str | None  # that quote's own words stating it, copied verbatim; None: none


class FindingJudgement(RoleOutput):
    # The statement split into its claims, each with its basis (checked by code).
    clauses: list[JudgedClause]
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

THESIS_JUDGE = Role(
    name="finding_judge",
    prompt=Prompt.load(PROMPTS_DIR, "finding_judge", THESIS_JUDGE_PROMPT_VERSION),
    request=FindingJudgeRequest,
    response=FindingJudgement,
    max_output_tokens=2048,
)
THESIS_JUDGE_VERSION = f"{THESIS_JUDGE.prompt.name}.v{THESIS_JUDGE.prompt.version}"


def judge_role(request: FindingJudgeRequest) -> Role[FindingJudgeRequest, FindingJudgement]:
    """The role that judges `request`: `THESIS_JUDGE` for a thesis, else `FINDING_JUDGE`."""
    return THESIS_JUDGE if request.finding.thesis else FINDING_JUDGE


def judge_version(thesis: bool) -> str:
    """The prompt version a thesis (`thesis`) or any other statement is judged by."""
    return THESIS_JUDGE_VERSION if thesis else FINDING_JUDGE_VERSION
