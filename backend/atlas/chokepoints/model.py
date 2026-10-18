"""The board's shapes and its fold: what an event holds, what a request carries, what a read
answers, and the pure function from a chokepoint's events to its current state.

The six steps of the bottleneck test are a to f: **a constraint, b demand_vs_supply, c relief,
d control, e capture, f invalidation**. A payload names a step by its letter or its name; it is
stored, and answered, by the letter (with the name beside it)."""

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

type StepKey = Literal["a", "b", "c", "d", "e", "f"]
type StepStatus = Literal["unexamined", "lead", "primary", "contradicted"]
type ChokepointStatus = Literal["lead", "candidate", "thesis_ready", "killed"]
type Crowding = Literal["early", "emerging", "consensus"]
type EventKind = Literal["created", "field_set", "step_set", "status_set", "note"]
type WriteKind = Literal["field_set", "step_set", "status_set", "note"]
type WatchMode = Literal["architect", "delta"]
type Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
# A theme is a slug, as the theme configs write it (`photonics`, `memory-packaging`).
type Theme = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,40}$")]

STEPS: tuple[StepKey, ...] = ("a", "b", "c", "d", "e", "f")
STEP_NAMES: dict[str, StepKey] = {
    "constraint": "a",
    "demand_vs_supply": "b",
    "relief": "c",
    "control": "d",
    "capture": "e",
    "invalidation": "f",
}
STEP_NAME_OF: dict[str, str] = {letter: name for name, letter in STEP_NAMES.items()}
THESIS_STEPS: tuple[StepKey, ...] = ("a", "b", "d")
EVIDENCE_KINDS = frozenset({"created", "field_set", "step_set"})  # a note or a status is not
STALE_AFTER = timedelta(days=56)  # no evidence-bearing event for 8 weeks
PROSPECTIVE_WINDOW = timedelta(hours=36)  # the board is prospective: a session is of now


def _step_letter(value: Any) -> Any:
    return STEP_NAMES.get(value, value) if isinstance(value, str) else value


StepRef = Annotated[
    StepKey,
    BeforeValidator(_step_letter),
    Field(
        description="a step by letter or name: a constraint, b demand_vs_supply, c relief,"
        " d control, e capture, f invalidation"
    ),
]


class ChokepointError(Exception):
    """A refusal; `status`, `code` and `detail` are the API's."""

    def __init__(self, status: int, code: str, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail


# --- what an event holds -------------------------------------------------------------------


class Holder(BaseModel):
    """Who holds the scarce input: a name, with the universe's slug and a CIK when known. A
    holder outside the universe is allowed (the board looks beyond the universe)."""

    model_config = ConfigDict(extra="forbid")

    name: Text
    slug: Text | None = Field(default=None, description="the company's slug, if it has one")
    cik: str | None = Field(default=None, pattern=r"^\d{1,10}$")


class ReliefHorizon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon: Text = Field(description="when supply could catch up")
    basis: Text = Field(description="what that rests on")


class StepEvidence(BaseModel):
    """What justifies a step's status: `primary` and `contradicted` need Facts, `lead` a lead
    or an Issue. Given as `evidence`, it replaces the step's whole evidence."""

    model_config = ConfigDict(extra="forbid")

    fact_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])
    lead_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])
    issue_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])

    def merged(self, more: "StepEvidence") -> "StepEvidence":
        def join(old: list[uuid.UUID], new: list[uuid.UUID]) -> list[uuid.UUID]:
            return old + [each for each in dict.fromkeys(new) if each not in old]

        return StepEvidence(
            fact_ids=join(self.fact_ids, more.fact_ids),
            lead_ids=join(self.lead_ids, more.lead_ids),
            issue_ids=join(self.issue_ids, more.issue_ids),
        )


class CreatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint: Text
    layer: Text
    holders: list[Holder] = Field(default_factory=list[Holder])


class FieldSetPayload(BaseModel):
    """The fields an event sets; the others stay as they were. A list field given here
    (`holders`, `kill_criteria`, `issue_ids`) **replaces the whole list**; `add_issue_ids`
    appends instead. `relief_horizon` and `crowding` may be set to null."""

    model_config = ConfigDict(extra="forbid")

    constraint: Text | None = None
    layer: Text | None = None
    holders: list[Holder] | None = Field(default=None, description="replaces the whole list")
    relief_horizon: ReliefHorizon | None = None
    crowding: Crowding | None = None
    kill_criteria: list[Text] | None = Field(default=None, description="replaces the whole list")
    issue_ids: list[uuid.UUID] | None = Field(default=None, description="replaces the whole list")
    add_issue_ids: list[uuid.UUID] | None = Field(
        default=None, description="Issues to link in addition to those already linked"
    )

    @model_validator(mode="after")
    def _something_and_not_null(self) -> Self:
        given = self.model_fields_set
        if not given:
            raise ValueError("set at least one field")
        for key in (
            "constraint",
            "layer",
            "holders",
            "kill_criteria",
            "issue_ids",
            "add_issue_ids",
        ):
            if key in given and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        if "issue_ids" in given and "add_issue_ids" in given:
            raise ValueError("give issue_ids (replace) or add_issue_ids (append), not both")
        return self


class StepSetPayload(BaseModel):
    """A step's status and what justifies it. `evidence` replaces the step's whole evidence;
    `add_evidence` appends to it."""

    model_config = ConfigDict(extra="forbid")

    step: StepRef
    status: StepStatus
    evidence: StepEvidence = Field(
        default_factory=StepEvidence, description="replaces the step's whole evidence"
    )
    add_evidence: StepEvidence | None = Field(
        default=None, description="Facts, leads and Issues to add to the step's evidence"
    )

    @model_validator(mode="after")
    def _one_way(self) -> Self:
        if "evidence" in self.model_fields_set and self.add_evidence is not None:
            raise ValueError("give evidence (replace) or add_evidence (append), not both")
        return self


class StatusSetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ChokepointStatus


class NotePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Text


PAYLOADS: dict[str, type[BaseModel]] = {
    "created": CreatedPayload,
    "field_set": FieldSetPayload,
    "step_set": StepSetPayload,
    "status_set": StatusSetPayload,
    "note": NotePayload,
}


# --- requests and answers ------------------------------------------------------------------


class ChokepointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: Theme
    constraint: Text = Field(description="the scarce thing")
    layer: Text = Field(description="where in the chain it sits")
    holders: list[Holder] = Field(default_factory=list[Holder])
    session_id: uuid.UUID | None = Field(
        default=None, description="the research session (its theme must be the chokepoint's)"
    )
    run_id: uuid.UUID | None = Field(
        default=None,
        description="a row of the `run` table (the pipeline's run record), not a watch run",
    )
    actor: Text | None = Field(
        default=None, description="who; default: the session's actor, else the API's"
    )


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: WriteKind
    payload: dict[str, JsonValue] = Field(
        description="by kind: `field_set` any of constraint, layer, holders, relief_horizon"
        " ({horizon, basis} or null), crowding (early|emerging|consensus|null), kill_criteria,"
        " issue_ids (a list given replaces the whole list; add_issue_ids appends);"
        " `step_set` {step (a constraint, b demand_vs_supply, c relief, d control, e capture,"
        " f invalidation; the letter or the name), status, evidence {fact_ids, lead_ids,"
        " issue_ids} (replaces the step's evidence) or add_evidence (appends)};"
        " `status_set` {status}; `note` {text}"
    )
    reason: str | None = Field(default=None, description="why; `killed` needs one")
    session_id: uuid.UUID | None = Field(
        default=None,
        description="the research session: its as-of time bounds the Facts, leads and Issues"
        " cited, its theme must be the chokepoint's, and it must be open and of now",
    )
    run_id: uuid.UUID | None = Field(default=None, description="a row of the `run` table")
    actor: Text | None = None


class ChokepointEvent(BaseModel):
    id: uuid.UUID
    chokepoint_id: uuid.UUID
    at: datetime
    actor: str
    session_id: uuid.UUID | None
    run_id: uuid.UUID | None
    kind: EventKind
    payload: dict[str, JsonValue]
    reason: str | None


class StepState(BaseModel):
    step: StepKey
    name: str = Field(
        description="constraint, demand_vs_supply, relief, control, capture or invalidation"
    )
    status: StepStatus
    evidence: StepEvidence
    set_at: datetime | None = Field(description="when the status was last set; null: never")


class ThesisGate(BaseModel):
    """What `thesis_ready` needs: steps a, b and d `primary`, a kill criterion, an open linked
    Issue. `missing` names what does not hold (`step_a_primary`, `kill_criteria`,
    `open_issue`, ...)."""

    holds: bool
    missing: list[str]


class Chokepoint(BaseModel):
    """The fold of the chokepoint's events."""

    id: uuid.UUID
    theme: str
    created_at: datetime
    created_by_session: uuid.UUID | None
    created_by_run: uuid.UUID | None = Field(description="a row of the `run` table")
    constraint: str
    layer: str
    holders: list[Holder]
    status: ChokepointStatus = Field(description="the status last set; `stale` is not stored")
    status_reason: str | None = Field(description="the reason given with that status")
    thesis_gate: ThesisGate = Field(description="whether `thesis_ready` would be allowed now")
    needs_review: bool = Field(
        description="`thesis_ready` whose gate no longer holds (a step changed under it)"
    )
    stale: bool = Field(
        description="derived: no field_set or step_set event for 56 days, a note and a status"
        " change not counting (never for a killed one)"
    )
    steps: list[StepState] = Field(description="the six bottleneck-test steps, a to f")
    kill_criteria: list[str]
    relief_horizon: ReliefHorizon | None
    crowding: Crowding | None = Field(description="context, never evidence")
    issue_ids: list[uuid.UUID] = Field(description="the Issues linked to it")
    last_event_at: datetime
    last_evidence_at: datetime = Field(
        description="the last created, field_set or step_set event: what staleness reads"
    )
    event_count: int


class ChokepointDetail(Chokepoint):
    history: list[ChokepointEvent] = Field(description="every event, oldest first")


class WatchRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: Theme
    run_date: date
    mode: WatchMode = Field(description="`architect`: the first run, decomposing the industry")
    memo: Text = Field(description="the memo, markdown")
    counts: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    tool_calls: int | None = Field(
        default=None, ge=0, description="default: the session's recorded calls, else 0"
    )
    cost_usd: float | None = Field(default=None, ge=0, description="the run's cost, if known")
    tokens: int | None = Field(default=None, ge=0, description="the run's tokens, if known")
    session_id: uuid.UUID | None = None


class WatchRun(BaseModel):
    id: uuid.UUID
    theme: str
    run_date: date
    mode: WatchMode
    memo: str
    counts: dict[str, JsonValue]
    tool_calls: int
    cost_usd: float | None
    tokens: int | None
    session_id: uuid.UUID | None
    created_at: datetime


# --- the fold ------------------------------------------------------------------------------


def fold(
    head: dict[str, Any],
    events: Sequence[ChokepointEvent],
    now: datetime,
    open_issues: frozenset[uuid.UUID] = frozenset(),
) -> ChokepointDetail:
    """The chokepoint's current state from its events, oldest first; `open_issues` are the
    linked Issues that are still active. Pure."""
    fields: dict[str, Any] = {
        "constraint": "",
        "layer": "",
        "holders": [],
        "relief_horizon": None,
        "crowding": None,
        "kill_criteria": [],
        "issue_ids": [],
    }
    steps: dict[str, StepState] = {
        key: StepState(
            step=key,
            name=STEP_NAME_OF[key],
            status="unexamined",
            evidence=StepEvidence(),
            set_at=None,
        )
        for key in STEPS
    }
    status: ChokepointStatus = "lead"
    status_reason: str | None = None
    for event in events:
        if event.kind == "created":
            created = CreatedPayload.model_validate(event.payload)
            fields.update(
                constraint=created.constraint, layer=created.layer, holders=created.holders
            )
        elif event.kind == "field_set":
            given = FieldSetPayload.model_validate(event.payload)
            for key in given.model_fields_set:
                fields[key] = getattr(given, key)
        elif event.kind == "step_set":
            step = StepSetPayload.model_validate(event.payload)
            steps[step.step] = StepState(
                step=step.step,
                name=STEP_NAME_OF[step.step],
                status=step.status,
                evidence=step.evidence,
                set_at=event.at,
            )
        elif event.kind == "status_set":
            status = StatusSetPayload.model_validate(event.payload).status
            status_reason = event.reason
    last = events[-1].at
    last_evidence = max(event.at for event in events if event.kind in EVIDENCE_KINDS)
    missing = [
        f"step_{each.step}_primary"
        for each in steps.values()
        if each.step in THESIS_STEPS and each.status != "primary"
    ]
    if not fields["kill_criteria"]:
        missing.append("kill_criteria")
    if not any(each in open_issues for each in fields["issue_ids"]):
        missing.append("open_issue")
    gate = ThesisGate(holds=not missing, missing=missing)
    return ChokepointDetail(
        id=head["id"],
        theme=head["theme"],
        created_at=head["created_at"],
        created_by_session=head["created_by_session"],
        created_by_run=head["created_by_run"],
        status=status,
        status_reason=status_reason,
        thesis_gate=gate,
        needs_review=status == "thesis_ready" and not gate.holds,
        stale=status != "killed" and now - last_evidence >= STALE_AFTER,
        steps=list(steps.values()),
        last_event_at=last,
        last_evidence_at=last_evidence,
        event_count=len(events),
        history=list(events),
        **fields,
    )
