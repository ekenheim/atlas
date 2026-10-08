"""The counter-judge (pilot-review T3): what a Skeptic Fact does to the Facts it challenges.

The argument Skeptic (`atlas.roles.reader.ARGUMENT_SKEPTIC`) records counterevidence as Facts,
each naming in `challenges` the Readers' Facts it speaks against. On the four 0.5.3 cards none
of its 50 Facts denied, limited or dated what it was filed against: they bore on a step (a
competitor's qualification under way), were off the question, or repeated what they
challenged. Yet a step was `disputed` whenever one was filed under it. The judge reads each
Skeptic Fact against the Facts it challenges, by their quotes, and labels each pair; code
lets only a contradicting label (`CONTRADICTING`) dispute a step (atlas.investigations.argument).

One Skeptic Fact per call: the request carries the counter-Fact (`k1`) and the Facts it
challenges (by the Skeptic's references, `f1`, ...), each with its company, step, statement,
status, quantity, period and source title; the retrieved data carries every one's exact quote
under its reference, quoted and low-trust like every role's. The answer is one relation per
challenged Fact.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

COUNTER_JUDGE_PROMPT_VERSION = 1

# What a counter-Fact's quote does to a challenged Fact.
Relation = Literal[
    "contradicts",  # denies what the Fact states
    "limits",  # narrows its scope, size or period
    "dates",  # a later statement: the plan slipped, the agreement ended, a qualification failed
    "qualifies",  # bears on the step (relief, a second source, a competitor, a customer)
    # without contradicting the Fact
    "supports",  # states the same or more of what the Fact states
    "unrelated",  # neither
]
RELATIONS: tuple[str, ...] = (
    "contradicts",
    "limits",
    "dates",
    "qualifies",
    "supports",
    "unrelated",
)
# The relations that speak against a Fact: only these (and a pair the judge could not label,
# `UNJUDGED`) dispute a step.
CONTRADICTING = frozenset({"contradicts", "limits", "dates"})
# A pair whose judge call failed (quarantined, cut off, the run's budget spent) or whose
# answer left it out.
UNJUDGED = "unjudged"

COUNTER_REF = "k1"


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JudgedFactItem(_Request):
    """A Fact as the judge is sent it (its exact quote goes as retrieved data under `ref`)."""

    ref: str  # `k1` for the counter-Fact; the Skeptic's `f<n>` for a challenged one
    company: str
    step: str
    statement: str
    status: str
    quantity: str | None
    period: str | None
    period_resolved: str | None = None  # what code resolved the quote's relative phrases to
    source_title: str


class CounterJudgeRequest(_Request):
    research_question: str
    counter: JudgedFactItem
    challenged: list[JudgedFactItem]


class CounterRelation(RoleOutput):
    ref: str  # a challenged Fact's reference (`f<n>`)
    relation: Relation
    reason: str  # one sentence, citing both quotes' words


class CounterJudgement(RoleOutput):
    relations: list[CounterRelation]


COUNTER_JUDGE = Role(
    name="counter_judge",
    prompt=Prompt.load(PROMPTS_DIR, "counter_judge", COUNTER_JUDGE_PROMPT_VERSION),
    request=CounterJudgeRequest,
    response=CounterJudgement,
    max_output_tokens=2048,
)
COUNTER_JUDGE_VERSION = f"{COUNTER_JUDGE.prompt.name}.v{COUNTER_JUDGE.prompt.version}"
