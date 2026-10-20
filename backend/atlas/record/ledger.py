"""The scheduled tasks' ledgers, typed (atlas-record ticket 01).

A theme task publishes a `ThemeLedger`; the council publishes a `CouncilLedger`. Both tolerate
what the tasks' prompts have not always written (`earliest_evidence`, `consensus`,
`council_answers`, `notes`: absent is `None`, never an error) and keep every field they do not
name (`extra="allow"`, so a task's new field survives the parse and the read). Dates the
ledger writes as strings that the record does not itself compute with (`made`, `deadline`,
`first_seen`, a source's `date`) stay strings: a task may write "2027-03" and the record shows
what it wrote.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class LedgerChokepoint(_Open):
    id: str
    name: str
    layer: str | None = None
    status: str | None = None
    verdicts: dict[str, Any] = {}
    holders: list[str] = []
    kill_criteria: list[str] = []
    first_seen: str | None = None
    earliest_evidence: str | None = None
    consensus: str | None = None


class LedgerPrediction(_Open):
    id: str
    chokepoint: str | None = None  # a theme's prediction names its chokepoint; the council's no
    made: str | None = None
    deadline: str | None = None
    text: str
    source_type: str | None = None
    state: str | None = None
    settled_on: str | None = None
    settlement_quote: str | None = None
    settlement_url: str | None = None


class LedgerSource(_Open):
    who: str | None = None
    doc: str | None = None
    date: str | None = None
    url: str
    quote: str


class ThemeLedger(_Open):
    theme: str
    as_of: date
    edition: int
    chokepoints: list[LedgerChokepoint]
    predictions: list[LedgerPrediction] = []
    rejected: list[dict[str, Any]] = []
    cross_theme_hooks: list[Any] = []
    council_answers: list[Any] | None = None
    primary_sources: list[LedgerSource] = []
    notes: Any | None = None


class LedgerBoardItem(_Open):
    rank: int
    theme: str
    chokepoint_id: str
    earliest_evidence: str | None = None
    consensus: str | None = None
    why: str | None = None


class CouncilLedger(_Open):
    council_as_of: date
    edition: int
    themes: dict[str, str] = {}  # each theme's edition date it read
    board: list[LedgerBoardItem]
    stacks: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    predictions: list[LedgerPrediction] = []
    assignments: dict[str, Any] | list[Any] = {}
    assignments_answered: list[dict[str, Any]] = []
    subagents: list[dict[str, Any]] = []
    primary_sources: list[LedgerSource] = []  # asked for, not yet there

    @property
    def as_of(self) -> date:
        return self.council_as_of


type Ledger = ThemeLedger | CouncilLedger

COUNCIL = "council"
