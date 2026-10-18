"""The board's shapes and its fold: what an event holds, what a request carries, what a read
answers, and the pure function from a chokepoint's events to its current state."""

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
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

STEPS: tuple[StepKey, ...] = ("a", "b", "c", "d", "e", "f")
THESIS_STEPS: tuple[StepKey, ...] = ("a", "b", "d")
STALE_AFTER = timedelta(days=56)  # no event for 8 weeks


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
    or an Issue."""

    model_config = ConfigDict(extra="forbid")

    fact_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])
    lead_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])
    issue_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])


class CreatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint: Text
    layer: Text
    holders: list[Holder] = Field(default_factory=list[Holder])


class FieldSetPayload(BaseModel):
    """The fields an event sets; the others stay as they were. `relief_horizon` and `crowding`
    may be set to null."""

    model_config = ConfigDict(extra="forbid")

    constraint: Text | None = None
    layer: Text | None = None
    holders: list[Holder] | None = None
    relief_horizon: ReliefHorizon | None = None
    crowding: Crowding | None = None
    kill_criteria: list[Text] | None = None
    issue_ids: list[uuid.UUID] | None = None

    @model_validator(mode="after")
    def _something_and_not_null(self) -> Self:
        given = self.model_fields_set
        if not given:
            raise ValueError("set at least one field")
        for key in ("constraint", "layer", "holders", "kill_criteria", "issue_ids"):
            if key in given and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class StepSetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: StepKey
    status: StepStatus
    evidence: StepEvidence = Field(default_factory=StepEvidence)


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

    theme: Text
    constraint: Text = Field(description="the scarce thing")
    layer: Text = Field(description="where in the chain it sits")
    holders: list[Holder] = Field(default_factory=list[Holder])
    session_id: uuid.UUID | None = Field(default=None, description="the research session")
    run_id: uuid.UUID | None = Field(default=None, description="the run that created it")
    actor: Text | None = Field(default=None, description="who; default: the API's actor")


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: WriteKind
    payload: dict[str, JsonValue] = Field(
        description="by kind: `field_set` any of constraint, layer, holders, relief_horizon"
        " ({horizon, basis} or null), crowding (early|emerging|consensus|null), kill_criteria,"
        " issue_ids; `step_set` {step a-f, status, evidence {fact_ids, lead_ids, issue_ids}};"
        " `status_set` {status}; `note` {text}"
    )
    reason: str | None = Field(default=None, description="why; `killed` needs one")
    session_id: uuid.UUID | None = Field(
        default=None, description="the research session: its as-of time bounds the Facts cited"
    )
    run_id: uuid.UUID | None = None
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
    status: StepStatus
    evidence: StepEvidence
    set_at: datetime | None = Field(description="when the status was last set; null: never")


class Chokepoint(BaseModel):
    """The fold of the chokepoint's events."""

    id: uuid.UUID
    theme: str
    created_at: datetime
    created_by_session: uuid.UUID | None
    created_by_run: uuid.UUID | None
    constraint: str
    layer: str
    holders: list[Holder]
    status: ChokepointStatus = Field(description="the status last set; `stale` is not stored")
    status_reason: str | None = Field(description="the reason given with that status")
    stale: bool = Field(description="derived: no event for 56 days (never for a killed one)")
    steps: list[StepState] = Field(description="the six bottleneck-test steps, a to f")
    kill_criteria: list[str]
    relief_horizon: ReliefHorizon | None
    crowding: Crowding | None = Field(description="context, never evidence")
    issue_ids: list[uuid.UUID] = Field(description="the Issues linked to it")
    last_event_at: datetime
    event_count: int


class ChokepointDetail(Chokepoint):
    history: list[ChokepointEvent] = Field(description="every event, oldest first")


class WatchRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: Text
    run_date: date
    mode: WatchMode = Field(description="`architect`: the first run, decomposing the industry")
    memo: Text = Field(description="the memo, markdown")
    counts: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    tool_calls: int | None = Field(
        default=None, ge=0, description="default: the session's recorded calls, else 0"
    )
    session_id: uuid.UUID | None = None


class WatchRun(BaseModel):
    id: uuid.UUID
    theme: str
    run_date: date
    mode: WatchMode
    memo: str
    counts: dict[str, JsonValue]
    tool_calls: int
    session_id: uuid.UUID | None
    created_at: datetime


# --- the fold ------------------------------------------------------------------------------


def fold(
    head: dict[str, Any], events: Sequence[ChokepointEvent], now: datetime
) -> ChokepointDetail:
    """The chokepoint's current state from its events, oldest first. Pure."""
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
        key: StepState(step=key, status="unexamined", evidence=StepEvidence(), set_at=None)
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
                step=step.step, status=step.status, evidence=step.evidence, set_at=event.at
            )
        elif event.kind == "status_set":
            status = StatusSetPayload.model_validate(event.payload).status
            status_reason = event.reason
    last = events[-1].at
    return ChokepointDetail(
        id=head["id"],
        theme=head["theme"],
        created_at=head["created_at"],
        created_by_session=head["created_by_session"],
        created_by_run=head["created_by_run"],
        status=status,
        status_reason=status_reason,
        stale=status != "killed" and now - last >= STALE_AFTER,
        steps=list(steps.values()),
        last_event_at=last,
        event_count=len(events),
        history=list(events),
        **fields,
    )
