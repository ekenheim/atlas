"""A published Hypothesis's predictions as rows, and their settlement (atlas-beliefs ticket 19).

A version's `measurable_predictions` are sentences. A prediction row says what is measured, the
range expected, the deadline and the source that settles it, so it can be scored when the day
comes: a Fact (its quantity), an XBRL observation (its value), or a TradingView close (the last
stored close on or before a day, through the price service's table; see
`atlas.tradingview.prices`: for scoring, never evidence).

- **Recorded on a published version only** (`409 version_not_published`), with a deadline after
  the day it was published (`422 deadline_not_after_publication`). A prediction names, optionally,
  the `measurable_predictions` item it makes measurable (`prediction_index`), and then its
  measure defaults to that sentence.
- **Insert-only.** A prediction is never changed; its one settlement is appended
  (`409 already_settled`). A prediction's state is read, not stored: `settled` with a settlement,
  `lapsed` with none once its deadline has passed, else `open`. A lapsed prediction can still be
  settled (the settlement says `late`), and a lapsed or rejected Hypothesis's predictions stay in
  the listing.
- **Settling** reads the value from the named source, never from the request: a Fact's
  `quantity.value` (`422 fact_has_no_quantity`), an observation's `value`, the stored close
  (`409 no_price`). The outcome is `met` when the value lies within the expected range, else
  `missed`.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.hypotheses.model import HypothesisStatus
from atlas.tradingview.prices import price_history

type SourceKind = Literal["fact", "financial_observation", "price"]
type PredictionState = Literal["open", "settled", "lapsed"]
type Outcome = Literal["met", "missed"]

PRICE_STALE_DAYS = 7  # a close counts for a day it is the last one before, at most this far back


class PredictionError(Exception):
    """A refusal; `status` and `code` are the API's."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class PredictionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, description="a published version of the Hypothesis")
    prediction_index: int | None = Field(
        default=None, ge=0, description="the item of the version's measurable_predictions"
    )
    measure: str | None = Field(
        default=None, min_length=1, description="what is measured; default: the indexed sentence"
    )
    unit: str | None = None
    expected_low: float | None = None
    expected_high: float | None = None
    deadline: date
    source: SourceKind
    company_id: uuid.UUID | None = Field(
        default=None, description="whose close or observation settles it (required for a price)"
    )

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.expected_low is None and self.expected_high is None:
            raise ValueError("name an expected range: expected_low, expected_high or both")
        if (
            self.expected_low is not None
            and self.expected_high is not None
            and self.expected_low > self.expected_high
        ):
            raise ValueError("expected_low is above expected_high")
        if self.source == "price" and self.company_id is None:
            raise ValueError("a price prediction names the company whose close settles it")
        if self.measure is None and self.prediction_index is None:
            raise ValueError("name the measure, or the prediction_index it makes measurable")
        return self


class PredictionSettle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: uuid.UUID | None = Field(default=None, description="source `fact`")
    observation_id: uuid.UUID | None = Field(
        default=None, description="source `financial_observation`"
    )
    day: date | None = Field(
        default=None,
        description="source `price`: the day whose close settles it; default the deadline",
    )
    note: str | None = None


class Settlement(BaseModel):
    outcome: Outcome
    value: float
    source_kind: SourceKind
    fact_id: uuid.UUID | None
    observation_id: uuid.UUID | None
    price_day: date | None
    price_symbol: str | None
    late: bool
    note: str | None
    actor: str
    settled_at: datetime


class Prediction(BaseModel):
    id: uuid.UUID
    hypothesis_id: uuid.UUID
    hypothesis_status: HypothesisStatus
    theme: str
    version: int
    version_published_at: datetime
    prediction_index: int | None
    measure: str
    unit: str | None
    expected_low: float | None
    expected_high: float | None
    deadline: date
    source_kind: SourceKind
    company_id: uuid.UUID | None
    state: PredictionState
    settlement: Settlement | None
    actor: str
    recorded_at: datetime


_SELECT = """
    SELECT p.id, p.hypothesis_id, h.status AS hypothesis_status, h.theme_id AS theme,
           v.version, v.published_at AS version_published_at, p.prediction_index, p.measure,
           p.unit, p.expected_low, p.expected_high, p.deadline, p.source_kind, p.company_id,
           p.actor, p.recorded_at,
           s.outcome, s.value, s.source_kind AS s_source_kind, s.fact_id, s.observation_id,
           s.price_day, s.price_symbol, s.late, s.note, s.actor AS s_actor, s.settled_at
    FROM prediction p
    JOIN hypothesis h ON h.id = p.hypothesis_id
    JOIN hypothesis_version v ON v.id = p.version_id
    LEFT JOIN prediction_settlement s ON s.prediction_id = p.id
"""


def _number(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _prediction(row: Any, today: date) -> Prediction:
    settlement: Settlement | None = None
    if row.outcome is not None:
        settlement = Settlement(
            outcome=row.outcome,
            value=float(row.value),
            source_kind=row.s_source_kind,
            fact_id=row.fact_id,
            observation_id=row.observation_id,
            price_day=row.price_day,
            price_symbol=row.price_symbol,
            late=row.late,
            note=row.note,
            actor=row.s_actor,
            settled_at=row.settled_at,
        )
    state: PredictionState = (
        "settled" if settlement else "lapsed" if row.deadline < today else "open"
    )
    return Prediction(
        id=row.id,
        hypothesis_id=row.hypothesis_id,
        hypothesis_status=row.hypothesis_status,
        theme=row.theme,
        version=row.version,
        version_published_at=row.version_published_at,
        prediction_index=row.prediction_index,
        measure=row.measure,
        unit=row.unit,
        expected_low=_number(row.expected_low),
        expected_high=_number(row.expected_high),
        deadline=row.deadline,
        source_kind=row.source_kind,
        company_id=row.company_id,
        state=state,
        settlement=settlement,
        actor=row.actor,
        recorded_at=row.recorded_at,
    )


def get_prediction(
    connection: Connection, prediction_id: uuid.UUID, today: date
) -> Prediction | None:
    row = connection.execute(
        text(_SELECT + " WHERE p.id = :id"), {"id": prediction_id}
    ).one_or_none()
    return _prediction(row, today) if row else None


def list_predictions(
    connection: Connection,
    today: date,
    *,
    hypothesis_id: uuid.UUID | None = None,
    state: PredictionState | None = None,
    hypothesis_status: HypothesisStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Prediction], int]:
    """The predictions, soonest deadline first. Every Hypothesis's are listed, rejected and
    closed ones included."""
    condition = (
        " WHERE (CAST(:hypothesis AS uuid) IS NULL OR p.hypothesis_id = :hypothesis)"
        " AND (CAST(:status AS text) IS NULL OR h.status = :status)"
        " AND (CAST(:state AS text) IS NULL OR CASE WHEN s.id IS NOT NULL THEN 'settled'"
        "   WHEN p.deadline < :today THEN 'lapsed' ELSE 'open' END = :state)"
    )
    params: dict[str, Any] = {
        "hypothesis": hypothesis_id,
        "status": hypothesis_status,
        "state": state,
        "today": today,
    }
    total = connection.execute(
        text(
            "SELECT count(*) FROM prediction p JOIN hypothesis h ON h.id = p.hypothesis_id"  # noqa: S608
            " LEFT JOIN prediction_settlement s ON s.prediction_id = p.id" + condition
        ),
        params,
    ).scalar_one()
    rows = connection.execute(
        text(
            _SELECT
            + condition
            + " ORDER BY p.deadline, p.recorded_at, p.id LIMIT :limit OFFSET :offset"
        ),
        params | {"limit": limit, "offset": offset},
    ).all()
    return [_prediction(row, today) for row in rows], total


class Predictions:
    def __init__(self, engine: Engine, actor: Actor) -> None:
        self._engine = engine
        self._actor = actor

    def create(
        self, hypothesis_id: uuid.UUID, request: PredictionCreate, today: date
    ) -> Prediction:
        with self._engine.begin() as connection:
            hypothesis = connection.execute(
                text("SELECT id FROM hypothesis WHERE id = :id"), {"id": hypothesis_id}
            ).one_or_none()
            if hypothesis is None:
                raise PredictionError(404, "not_found", "hypothesis not found")
            version = connection.execute(
                text(
                    "SELECT id, published_at, content->'measurable_predictions' AS sentences"
                    " FROM hypothesis_version WHERE hypothesis_id = :id AND version = :version"
                ),
                {"id": hypothesis_id, "version": request.version},
            ).one_or_none()
            if version is None:
                raise PredictionError(404, "not_found", "version not found")
            if version.published_at is None:
                raise PredictionError(
                    409, "version_not_published", "predictions are recorded on a published version"
                )
            if request.deadline <= version.published_at.astimezone(UTC).date():
                raise PredictionError(
                    422,
                    "deadline_not_after_publication",
                    "the deadline must fall after the day the version was published",
                )
            measure = request.measure
            sentences: list[str] = version.sentences or []
            if request.prediction_index is not None:
                if request.prediction_index >= len(sentences):
                    raise PredictionError(
                        422,
                        "unknown_prediction_index",
                        f"the version has {len(sentences)} measurable predictions",
                    )
                measure = measure or sentences[request.prediction_index]
            assert measure is not None
            if (
                request.company_id is not None
                and connection.execute(
                    text("SELECT 1 FROM company WHERE id = :id"), {"id": request.company_id}
                ).one_or_none()
                is None
            ):
                raise PredictionError(422, "unknown_company", "the company is not in the universe")
            prediction_id = uuid.uuid4()
            connection.execute(
                text(
                    "INSERT INTO prediction (id, hypothesis_id, version_id, prediction_index,"
                    " measure, unit, expected_low, expected_high, deadline, source_kind,"
                    " company_id, actor) VALUES (:id, :hypothesis, :version, :index, :measure,"
                    " :unit, :low, :high, :deadline, :source, :company, :actor)"
                ),
                {
                    "id": prediction_id,
                    "hypothesis": hypothesis_id,
                    "version": version.id,
                    "index": request.prediction_index,
                    "measure": measure,
                    "unit": request.unit,
                    "low": request.expected_low,
                    "high": request.expected_high,
                    "deadline": request.deadline,
                    "source": request.source,
                    "company": request.company_id,
                    "actor": self._actor.name,
                },
            )
            record(
                connection,
                self._actor,
                "prediction.recorded",
                entity_type="prediction",
                entity_id=str(prediction_id),
                new_hash=content_hash(request.model_dump(mode="json") | {"measure": measure}),
            )
            created = get_prediction(connection, prediction_id, today)
        assert created is not None
        return created

    def settle(
        self,
        hypothesis_id: uuid.UUID,
        prediction_id: uuid.UUID,
        request: PredictionSettle,
        now: datetime,
    ) -> Prediction:
        today = now.astimezone(UTC).date()
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT id, source_kind, company_id, deadline, expected_low, expected_high"
                    " FROM prediction WHERE id = :id AND hypothesis_id = :hypothesis FOR UPDATE"
                ),
                {"id": prediction_id, "hypothesis": hypothesis_id},
            ).one_or_none()
            if row is None:
                raise PredictionError(404, "not_found", "prediction not found")
            if connection.execute(
                text("SELECT 1 FROM prediction_settlement WHERE prediction_id = :id"),
                {"id": prediction_id},
            ).one_or_none():
                raise PredictionError(409, "already_settled", "the prediction is settled")
            fact_id = observation_id = price_day = None
            price_symbol: str | None = None
            if row.source_kind == "fact":
                if request.fact_id is None or request.observation_id or request.day:
                    raise PredictionError(
                        422, "wrong_source", "this prediction is settled by a Fact: name fact_id"
                    )
                value = _fact_value(connection, request.fact_id)
                fact_id = request.fact_id
            elif row.source_kind == "financial_observation":
                if request.observation_id is None or request.fact_id or request.day:
                    raise PredictionError(
                        422,
                        "wrong_source",
                        "this prediction is settled by an XBRL observation: name observation_id",
                    )
                value = _observation_value(connection, request.observation_id, row.company_id)
                observation_id = request.observation_id
            else:
                if request.fact_id or request.observation_id:
                    raise PredictionError(
                        422, "wrong_source", "this prediction is settled by a close: name only day"
                    )
                price_day = request.day or row.deadline
                if price_day > today:
                    raise PredictionError(422, "day_in_future", "that day has not happened")
                value, price_symbol = _close(connection, row.company_id, price_day)
            low, high = _number(row.expected_low), _number(row.expected_high)
            met = (low is None or value >= low) and (high is None or value <= high)
            connection.execute(
                text(
                    "INSERT INTO prediction_settlement (id, prediction_id, outcome, value,"
                    " source_kind, fact_id, observation_id, price_day, price_symbol, late, note,"
                    " actor, settled_at) VALUES (:id, :prediction, :outcome, :value, :source,"
                    " :fact, :observation, :day, :symbol, :late, :note, :actor, :now)"
                ),
                {
                    "id": uuid.uuid4(),
                    "prediction": prediction_id,
                    "outcome": "met" if met else "missed",
                    "value": value,
                    "source": row.source_kind,
                    "fact": fact_id,
                    "observation": observation_id,
                    "day": price_day,
                    "symbol": price_symbol,
                    "late": today > row.deadline,
                    "note": request.note,
                    "actor": self._actor.name,
                    "now": now,
                },
            )
            record(
                connection,
                self._actor,
                "prediction.settled",
                entity_type="prediction",
                entity_id=str(prediction_id),
                new_hash=content_hash({"outcome": met, "value": value}),
            )
            settled = get_prediction(connection, prediction_id, today)
        assert settled is not None
        return settled


def _fact_value(connection: Connection, fact_id: uuid.UUID) -> float:
    row = connection.execute(
        text(
            "SELECT a.value_json->'quantity'->>'value' AS value FROM fact f"
            " JOIN assertion a ON a.id = f.assertion_id WHERE f.assertion_id = :id"
        ),
        {"id": fact_id},
    ).one_or_none()
    if row is None:
        raise PredictionError(422, "unknown_fact", "no such Fact")
    if row.value is None:
        raise PredictionError(
            422, "fact_has_no_quantity", "the Fact states no quantity to settle a range with"
        )
    return float(row.value)


def _observation_value(
    connection: Connection, observation_id: uuid.UUID, company_id: uuid.UUID | None
) -> float:
    row = connection.execute(
        text("SELECT value, company_id FROM financial_observation WHERE id = :id"),
        {"id": observation_id},
    ).one_or_none()
    if row is None:
        raise PredictionError(422, "unknown_observation", "no such XBRL observation")
    if company_id is not None and row.company_id != company_id:
        raise PredictionError(
            422, "source_mismatch", "the observation is another company's than the prediction's"
        )
    return float(row.value)


def _close(connection: Connection, company_id: uuid.UUID, day: date) -> tuple[float, str]:
    """The stored close of `day` or the last day before it (at most a week back)."""
    history = price_history(
        connection,
        company_id=company_id,
        start=day - timedelta(days=PRICE_STALE_DAYS),
        end=day,
    )
    if not history.closes or history.symbol is None:
        raise PredictionError(
            409,
            "no_price",
            "no close is stored for that day; Atlas stores closes in its daily pass",
        )
    return history.closes[-1].close, history.symbol
