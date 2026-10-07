"""The Reader role (bottleneck-argument ticket 03): one argument step of one question, worked
the way a researcher with a search box works it. It chooses what to search, reads what it
chooses and records Facts (`atlas.facts`), one action per call, in a loop of role calls
(`atlas.investigations.reader` runs the loop and carries out the actions).

Each call is one `reader` role call through the shared caller (versioned prompt, strict JSON
schema, one repair then quarantine, the run's token budget). The request carries the
question, the step and what it asks, the companies (the seeds first, then the universe's
researched companies with their layers), what this step has searched, read and recorded so
far (compact), and the last few results; the retrieved data carries the text of the passages
and memories of the last results, quoted and low-trust like every role's.

The answer is one **action**, named by `action` with its arguments in the field of the same
name (the other action fields null): `search_archive`, `recall`, `read`, `record_fact` or
`done`. A flat object rather than a union keeps the schema one LiteLLM can enforce strictly;
`ReaderAction` checks that exactly the named action's arguments are given, so an answer that
names one action and fills another is a validation error (repaired once, then quarantined).

The argument plan's Skeptic (`ARGUMENT_SKEPTIC`, role `skeptic`, prompt `skeptic-argument`;
ticket 05) is the same loop with the same actions: it is sent the Facts the Readers recorded
(`challenge`, their quotes as retrieved data by reference `f1`, ...) and records
counterevidence as Facts, each naming in `challenges` the Facts it speaks against (always
empty for a Reader).
"""

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

READER_PROMPT_VERSION = 1
ARGUMENT_SKEPTIC_PROMPT_VERSION = 1

# The argument's steps (spec, "The steps of the argument"; the Serenity method's bottleneck
# test M1 to M6), by the Fact step that records them.
ArgumentStep = Literal[
    "constraint", "demand_vs_supply", "relief", "control", "capture", "invalidation"
]


@dataclass(frozen=True)
class StepDefinition:
    key: ArgumentStep
    title: str
    asks: str  # what the step must establish
    looks_for: str  # what a researcher looks for, and where


ARGUMENT_STEPS: tuple[StepDefinition, ...] = (
    StepDefinition(
        "constraint",
        "What is constrained",
        "What exactly is constrained, in what units, and over what period.",
        "The product, material or process step named in the question, at its layer of the"
        " supply chain; capacity stated in units (wafers, units or lasers per month, a share"
        " of demand) and the period it covers; the companies' own words in results calls,"
        " annual and quarterly reports and results releases.",
    ),
    StepDefinition(
        "demand_vs_supply",
        "Demand exceeds qualified supply",
        "The evidence that demand exceeds the qualified supply of it.",
        "Statements that demand outstrips supply, allocation, lead times, backlog or orders"
        " waiting, sold-out capacity, customers asking for more than is shipped; with the"
        " magnitudes and dates as stated.",
    ),
    StepDefinition(
        "relief",
        "How fast it can be relieved",
        "How quickly added capacity, another supplier or a substitute can relieve it.",
        "Capacity additions with their size and date (and whether announced, under way or"
        " in production), second sources being qualified, substitute technologies, export"
        " or regulatory limits on relief, qualification times.",
    ),
    StepDefinition(
        "control",
        "Who controls the scarce capability",
        "Who controls the scarce capability.",
        "Sole or few suppliers, shares of supply, who owns the fabs, the process know-how or"
        " the licences, who has qualified with the customers, and who is still qualifying.",
    ),
    StepDefinition(
        "capture",
        "How the company captures it",
        "How the company that controls it captures more revenue or profit.",
        "Pricing (increases, contracts, prepayments), share of the bill of materials, revenue"
        " and margin of the segment, customer funding or financing of capacity, dilution.",
    ),
    StepDefinition(
        "invalidation",
        "What would invalidate it",
        "The observation that would invalidate the argument.",
        "New entrants, capacity coming online, qualification of others, substitutes,"
        " inventory build-up, cancellations or pushed-out orders, price cuts, financing"
        " needs; said by the companies or their customers and suppliers.",
    ),
)
STEPS: dict[str, StepDefinition] = {step.key: step for step in ARGUMENT_STEPS}

# A Fact's step and status, as `atlas.facts` defines them (`FactStep`, `FactStatus`; repeated
# here because `atlas.facts` imports `atlas.investigations`, which runs this role; a unit test
# holds them equal).
FactStepName = Literal[
    "constraint", "demand_vs_supply", "relief", "control", "capture", "invalidation", "context"
]
FactStatusName = Literal[
    "in_effect", "planned", "in_development", "hedged", "regulatory", "reported_by_third_party"
]

ReaderActionName = Literal["search_archive", "recall", "read", "record_fact", "done"]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReaderStep(_Request):
    key: str
    title: str
    asks: str
    looks_for: str


class ReaderCompany(_Request):
    slug: str
    name: str
    layer: str | None  # its layer of the theme's supply chain, when the config names one
    seed: bool  # a seed company of the question


class ReaderFactSummary(_Request):
    """A Fact this step recorded, compact (its quote is not sent again)."""

    ref: str  # `r1`, `r2`, ...
    company_slug: str
    step: str
    status: str
    statement: str
    quantity: str | None  # "3 x InP capacity" as value, unit and metric
    period: str | None
    challenges: list[str]  # the Skeptic's: the Facts it speaks against


class ChallengedFact(_Request):
    """A Fact a Reader recorded, as the argument Skeptic is sent it: what to challenge, never
    a witness. Its quote goes as retrieved data (`id` its reference)."""

    ref: str  # `f1`, `f2`, ...
    step: str
    company_slug: str
    statement: str
    status: str
    quantity: str | None
    period: str | None
    source_title: str


class ResultItem(_Request):
    """One thing an action returned: a hit (`h<n>`), a window read (`p<n>`) or a memory
    (`m<n>`, Memory: a pointer to a section, never a witness). Its text is in the retrieved
    data under the same id while the result is among the last ones."""

    id: str
    source_version_id: str
    company_slug: str | None
    title: str
    kind: str | None  # the document's kind: `10-K`, `8-K`, `EX-99.1`, a transcript type
    date: str  # when it became available
    section: str | None  # the section anchor
    note: str | None  # e.g. "window 2 of 5"


class ReaderResult(_Request):
    call: int
    action: str
    ok: bool
    message: str  # what happened, or why the action was refused
    items: list[ResultItem]


class ReaderRequest(_Request):
    research_question: str
    as_of: str  # nothing available after it is searched or read
    step: ReaderStep
    companies: list[ReaderCompany]
    challenge: list[ChallengedFact]  # the Skeptic's; empty for a Reader
    searched: list[str]  # the queries so far, with the companies searched
    recalled: list[str]
    read: list[str]  # the windows read so far: `p3: <title>, <section>, window 1 of 4`
    recorded: list[ReaderFactSummary]
    refused: int  # record_fact actions refused so far
    results: list[ReaderResult]  # the last few, oldest first
    calls_left: int  # after this one
    passages_left: int


class SearchArchive(RoleOutput):
    query: str
    company_slugs: list[str]  # empty: every company listed


class Recall(RoleOutput):
    query: str


class Read(RoleOutput):
    # A hit (`h<n>`), a memory (`m<n>`) or a window read (`p<n>`) to read; or a section by
    # its Source Version and anchor.
    ref: str | None
    source_version_id: str | None
    anchor: str | None
    window: int | None  # which window of the section, from 1 (default: where the ref is)


class QuantityArgs(RoleOutput):
    value: float
    unit: str
    metric: str


class RecordFact(RoleOutput):
    passage_id: str  # the hit or window (`h<n>`, `p<n>`) the quote is from
    quote: str  # exactly the passage's words
    company_slug: str  # the company the fact is about
    step: FactStepName
    statement: str
    quantity: QuantityArgs | None
    period: str | None
    status: FactStatusName
    challenges: list[str]  # the argument Skeptic's: the Facts (`f<n>`) it speaks against


class Done(RoleOutput):
    summary: str


class ReaderAction(RoleOutput):
    action: ReaderActionName
    search_archive: SearchArchive | None
    recall: Recall | None
    read: Read | None
    record_fact: RecordFact | None
    done: Done | None

    @model_validator(mode="after")
    def _one_action(self) -> Self:
        given = [
            name
            for name in ("search_archive", "recall", "read", "record_fact", "done")
            if getattr(self, name) is not None
        ]
        if given != [self.action]:
            raise ValueError(
                f"action {self.action!r} needs its arguments in the field {self.action!r} and"
                f" every other action field null (given: {', '.join(given) or 'none'})"
            )
        return self


READER = Role(
    name="reader",
    prompt=Prompt.load(PROMPTS_DIR, "reader", READER_PROMPT_VERSION),
    request=ReaderRequest,
    response=ReaderAction,
    max_output_tokens=2048,
)
READER_VERSION = f"{READER.prompt.name}.v{READER.prompt.version}"

ARGUMENT_SKEPTIC = Role(
    name="skeptic",
    prompt=Prompt.load(PROMPTS_DIR, "skeptic-argument", ARGUMENT_SKEPTIC_PROMPT_VERSION),
    request=ReaderRequest,
    response=ReaderAction,
    max_output_tokens=2048,
)
ARGUMENT_SKEPTIC_VERSION = f"{ARGUMENT_SKEPTIC.prompt.name}.v{ARGUMENT_SKEPTIC.prompt.version}"

# The argument Skeptic's own task, across every step (its session is recorded as the
# invalidation step's: what would invalidate the argument).
SKEPTIC_STEP = StepDefinition(
    "invalidation",
    "Counterevidence against the argument",
    "What limits, denies or dates the Facts the Readers recorded, step by step.",
    "Capacity additions and new entrants, second sources and substitutes being qualified,"
    " inventory build-up and cancelled orders, price cuts, customer concentration, financing"
    " and dilution, and later statements that a plan slipped or a qualification failed; in"
    " the same companies' and their competitors', customers' and suppliers' filings and calls.",
)
