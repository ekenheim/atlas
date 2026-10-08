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
It also reads the answer in the other forms MiniMax writes it (arguments beside `action` or
under another key such as `"args"`; see `ReaderAction._as_the_model_writes_it`).

`record_fact` carries every fact one passage states (`{"facts": [...]}`, 1 to
`MAX_FACTS_PER_CALL`), each placed and recorded on its own (`reader.v2`; under `reader.v1` a
call recorded one Fact, and Readers recorded one or two in a step). One Fact's arguments
without `facts` (the `reader.v1` form) are still accepted, as a list of one. `reader.v3` sets a
Fact's status by a table of cues and keeps its period as the quote gives it; code refuses two
status mistakes (`atlas.facts.service.check_status`).

The argument plan's Skeptic (`ARGUMENT_SKEPTIC`, role `skeptic`, prompt `skeptic-argument`;
ticket 05) is the same loop with the same actions: it is sent the Facts the Readers recorded
(`challenge`, their quotes as retrieved data by reference `f1`, ...) and records
counterevidence as Facts, each naming in `challenges` the Facts it speaks against (always
empty for a Reader). Under `skeptic-argument.v3` (pilot-review T3) `challenges` names only the
Facts a quote denies, limits or dates; capacity coming, a second source or a competitor is
recorded under `relief` or `control` with no challenge, and the counter-judge
(`atlas.roles.counter_judge`) labels what each counter-Fact does to the Facts it names.
"""

from dataclasses import dataclass
from typing import Any, Literal, Self, cast, get_args

from pydantic import BaseModel, ConfigDict, model_validator

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

READER_PROMPT_VERSION = 3
ARGUMENT_SKEPTIC_PROMPT_VERSION = 3

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
        " the licences, who has qualified with the customers, and who is still qualifying;"
        " how many suppliers the customers have qualified and which competitors the company"
        " itself names.",
    ),
    StepDefinition(
        "capture",
        "How the company captures it",
        "How the company that controls it captures more revenue or profit.",
        "Pricing (increases, contracts, prepayments), share of the bill of materials, revenue"
        " and margin of the segment, customer funding or financing of capacity, dilution;"
        " customer concentration: customers over 10% of revenue and their share (the annual"
        " report's customers paragraph, 'accounted for').",
    ),
    StepDefinition(
        "invalidation",
        "What would invalidate it",
        # Pilot-review R2-03: only what bears against the argument; what the constrained
        # company adds is Relief's (atlas.investigations.argument judges each Fact).
        "What would break the argument: evidence that supply has caught up or will, that"
        " demand is slowing, or that another supplier or a substitute takes the scarce"
        " capability.",
        "Only what would weaken or break the argument: the constrained company's own words"
        " that the constraint eased (lead times normalising, 'no longer constrained', supply"
        " caught up); customers' or the company's inventory build-up; orders cancelled or"
        " pushed out; price cuts or falling ASPs; a competitor or second source qualified at a"
        " named customer or shipping in volume; a substitute (another laser type, silicon"
        " photonics, CPO, another material) displacing the constrained part in volume; demand"
        " slowing in the companies' or their customers' filings and calls. Capacity the"
        " constrained company itself adds is relief: record it under `relief`, not here. A"
        " statement that repeats the constraint, a record quarter or a plan to expand is never"
        " an invalidation Fact. Search for these in the seeds', their competitors', customers'"
        " and suppliers' filings and calls; say in your summary what you searched for and did"
        " not find.",
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

# The most Facts one `record_fact` carries.
MAX_FACTS_PER_CALL = 8


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


class RecordFacts(RoleOutput):
    """`record_fact`'s arguments: every fact one passage states, each placed and recorded on
    its own (1 to `MAX_FACTS_PER_CALL`; the bound is checked here, not in the schema)."""

    facts: list[RecordFact]

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if not 1 <= len(self.facts) <= MAX_FACTS_PER_CALL:
            raise ValueError(
                f"record_fact carries 1 to {MAX_FACTS_PER_CALL} facts (given: {len(self.facts)})"
            )
        return self


class Done(RoleOutput):
    summary: str


class ReaderAction(RoleOutput):
    action: ReaderActionName
    search_archive: SearchArchive | None
    recall: Recall | None
    read: Read | None
    record_fact: RecordFacts | None
    done: Done | None

    @model_validator(mode="before")
    @classmethod
    def _as_the_model_writes_it(cls, data: Any) -> Any:
        """The answer in the forms the model writes it, made the schema's (the strict schema
        sent to the model is unchanged):

        - the action's arguments beside `action` instead of in its field (`{"action": "read",
          "ref": "h5"}`), all of them or some; on 0.5.0's first argument run (2026-10-07)
          MiniMax wrote this flat form in 15 of 27 Reader calls and the repair prompt didn't
          change it;
        - the action's field written inside `action` (`{"action": {"read": {...}}}`);
        - the arguments under another key (`"args"`, `"arguments"`, `"action_args"`,
          `"params"`, ...) while the action's own field is missing or null: taken as the
          action's when exactly one such key holds an object and it is not an action's or an
          argument's name (and unwrapped once more when that object holds only the action's
          field); 12 of 59 Reader calls on 0.5.1's run were quarantined this way;
        - an optional argument left out, or null where it stands for an empty list;
        - `record_fact` with one Fact's arguments rather than `facts` (the `reader.v1` form),
          or with the list of Facts itself: made `{"facts": [...]}`.
        """
        if not isinstance(data, dict):
            return data
        answer = dict(cast(dict[str, Any], data))
        action = answer.get("action")
        if isinstance(action, dict):
            # The action's field written inside `action`: {"action": {"read": {...}}}.
            named = [k for k, v in cast(dict[str, Any], action).items() if v is not None]
            if len(named) == 1 and named[0] in _ACTION_FIELDS:
                answer[named[0]] = cast(dict[str, Any], action)[named[0]]
                action = answer["action"] = named[0]
        if not isinstance(action, str) or action not in _ACTION_FIELDS:
            return answer
        model, defaults = _ACTION_FIELDS[action]
        names = set(model.model_fields) | ({"facts"} if action == "record_fact" else set[str]())
        nested = answer.get(action)
        # Arguments written beside `action`, all of them or some (the rest in its field).
        flat = {name: answer.pop(name) for name in list(answer) if name in names}
        if nested is None:
            nested = _wrapped(answer, action, names)
        if isinstance(nested, dict):
            nested = {**flat, **cast(dict[str, Any], nested)}
        elif nested is None and flat:
            nested = flat
        if action == "record_fact":
            nested = _as_facts(nested, defaults)
        elif isinstance(nested, dict):
            nested = _with_defaults(cast(dict[str, Any], nested), defaults)
        if nested is not None:
            answer[action] = nested
        for other in _ACTION_FIELDS:
            if other != action:
                answer.setdefault(other, None)
        return answer

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


# Each action's arguments model, and what an argument the model leaves out stands for (an
# optional argument; a required one stays required).
_ACTION_FIELDS: dict[str, tuple[type[RoleOutput], dict[str, Any]]] = {
    "search_archive": (SearchArchive, {"company_slugs": []}),
    "recall": (Recall, {}),
    "read": (Read, {"ref": None, "source_version_id": None, "anchor": None, "window": None}),
    # Each Fact's (`record_fact`'s arguments are `{"facts": [...]}`).
    "record_fact": (RecordFact, {"quantity": None, "period": None, "challenges": []}),
    "done": (Done, {}),
}


def _with_defaults(args: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """`args` with each optional argument left out or null set to what it stands for."""
    given = dict(args)
    for name, default in defaults.items():
        if given.get(name) is None:
            given[name] = default
    return given


def _wrapped(answer: dict[str, Any], action: str, names: set[str]) -> Any:
    """The action's arguments under some other key (`"args"`, `"arguments"`, ...), removed
    from `answer`: the one key holding an object that is not `action`, an action's field or
    an argument's name. None when there is no such key, or more than one."""
    keys = [
        key
        for key, value in answer.items()
        if key != "action"
        and key not in _ACTION_FIELDS
        and key not in names
        and isinstance(value, dict)
    ]
    if len(keys) != 1:
        return None
    wrapped = cast(dict[str, Any], answer.pop(keys[0]))
    # The action's field inside the wrapper: {"args": {"record_fact": {...}}}.
    given = [key for key, value in wrapped.items() if value is not None]
    if given == [action] and isinstance(wrapped[action], dict | list):
        return wrapped[action]
    return wrapped


def _as_facts(nested: Any, defaults: dict[str, Any]) -> Any:
    """`record_fact`'s arguments as `{"facts": [...]}`, each Fact's optional arguments set:
    from the list of Facts itself, or from one Fact's arguments (the `reader.v1` form)."""
    if isinstance(nested, list):
        nested = {"facts": cast(list[Any], nested)}
    if not isinstance(nested, dict):
        return nested
    args = dict(cast(dict[str, Any], nested))
    if args.get("facts") is None and set(args) & set(RecordFact.model_fields):
        args = {"facts": [{k: v for k, v in args.items() if k != "facts"}]}
    facts: Any = args.get("facts")
    if isinstance(facts, dict):
        facts = [cast(dict[str, Any], facts)]  # one Fact written as an object
    if isinstance(facts, list):
        args["facts"] = [
            _with_quantity(_with_defaults(cast(dict[str, Any], each), defaults))
            if isinstance(each, dict)
            else each
            for each in cast(list[Any], facts)
        ]
    return args


def _with_quantity(fact: dict[str, Any]) -> dict[str, Any]:
    """`fact` with a `quantity` that isn't `{value: number, unit, metric}` taken as none, so one
    malformed quantity doesn't cost the call's every Fact (the quote, statement and status keep
    what the quote says). A value written as a number in a string ("1.6") is the number; other
    keys (`as_of`) are dropped; a missing unit or metric is empty. On 0.5.2's argument run
    (2026-10-07) MiniMax wrote quantities as text ("70%-80%"), ranges and objects missing a
    metric in every quarantined Skeptic call, and those calls held its counterevidence."""
    step = fact.get("step")
    if isinstance(step, str) and step not in get_args(FactStepName):
        # A step that isn't one: the fact is context, not a claim on a step of the argument
        # (one such Fact quarantined a whole Skeptic call on 0.5.2's run).
        fact = {**fact, "step": "context"}
    quantity = fact.get("quantity")
    if quantity is None:
        return fact
    kept: dict[str, Any] | None = None
    if isinstance(quantity, dict):
        given = cast(dict[str, Any], quantity)
        value = given.get("value")
        if isinstance(value, str):
            try:
                value = float(value.replace(",", "").strip())
            except ValueError:
                value = None
        if isinstance(value, int | float) and not isinstance(value, bool):
            unit, metric = given.get("unit"), given.get("metric")
            kept = {
                "value": float(value),
                "unit": unit if isinstance(unit, str) else "",
                "metric": metric if isinstance(metric, str) else "",
            }
    return {**fact, "quantity": kept}


READER = Role(
    name="reader",
    prompt=Prompt.load(PROMPTS_DIR, "reader", READER_PROMPT_VERSION),
    request=ReaderRequest,
    response=ReaderAction,
    # Up to MAX_FACTS_PER_CALL Facts in one answer, each with its quote and statement: 2,048
    # tokens cut one call off on 0.5.2's run.
    max_output_tokens=6144,
)
READER_VERSION = f"{READER.prompt.name}.v{READER.prompt.version}"

ARGUMENT_SKEPTIC = Role(
    name="skeptic",
    prompt=Prompt.load(PROMPTS_DIR, "skeptic-argument", ARGUMENT_SKEPTIC_PROMPT_VERSION),
    request=ReaderRequest,
    response=ReaderAction,
    max_output_tokens=6144,
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
