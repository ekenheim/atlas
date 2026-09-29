"""Storing and reading scenarios: each attached to a Hypothesis version (spec §5.7 "scenario").

**Creating.** A scenario is computed for one Hypothesis version from an assumption table,
with its sources checked as of the cutoff (the Hypothesis's investigation's as-of time unless
the request gives one):

- the researcher's own table (an analyst override): every source must stand, or nothing is
  stored (`ScenarioInvalid`, listing each problem); or
- the Financial Analyst's proposal from the Hypothesis's investigation: one scenario per
  proposed table; an input whose source no longer stands at the cutoff becomes missing.

The row is insert-only; its outputs are stored as the canonical JSON bytes that were hashed.

**Reading.** A scenario shows its inputs with their provenance (each XBRL observation with its
accession, concept, period, unit and `available_at`; each Assertion with its quote and span),
its outputs, both hashes, and whether recomputing it now gives the same bytes.
"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.audit import Actor, content_hash, record
from atlas.scenarios.model import (
    CASES,
    INPUTS,
    AssumptionTable,
    InputName,
    Measure,
    MissingInput,
    ScenarioOutputs,
    SourcedInput,
    compute,
    number,
    outputs_json,
)
from atlas.scenarios.sources import (
    ResolvedAssertion,
    ResolvedObservation,
    check_sources,
    resolve_sources,
)

Origin = Literal["financial_analyst", "researcher"]
# A table to store: its origin, the Analyst's task and role call.
type _Planned = tuple[AssumptionTable, Origin, uuid.UUID | None, uuid.UUID | None]


class ScenarioError(Exception):
    """A request a scenario can't honour; `code` and `status` for the API."""

    code = "invalid_scenario"
    status = 422

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ScenarioNotFound(ScenarioError):
    code = "not_found"
    status = 404


class ScenarioConflict(ScenarioError):
    code = "no_analyst_proposal"
    status = 409


class ScenarioInvalid(ScenarioError):
    """The assumption table's sources don't stand: `problems` lists each."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("the assumption table doesn't validate: " + "; ".join(problems))


# --- the read side --------------------------------------------------------------------------


class ScenarioInputView(BaseModel):
    """One input as the scenario used it, with its provenance."""

    model_config = ConfigDict(frozen=True)

    name: InputName
    measure: Measure
    meaning: str
    kind: Literal["sourced", "estimated", "missing"]
    low: str | None
    base: str | None
    high: str | None
    basis: str | None  # an estimate's basis
    reason: str | None  # why it is missing, if known
    source: ResolvedObservation | ResolvedAssertion | None  # a sourced input's source


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    hypothesis_id: uuid.UUID
    hypothesis_version: int
    hypothesis_version_id: uuid.UUID
    company_id: uuid.UUID
    product: str
    currency: str
    as_of: datetime
    model_version: str
    origin: Origin
    investigation_task_id: uuid.UUID | None
    role_call_id: uuid.UUID | None
    note: str | None
    created_by: str
    created_at: datetime
    inputs: list[ScenarioInputView]
    assumptions: dict[str, Any]  # the canonical assumption table that was computed
    assumptions_sha256: str
    outputs: ScenarioOutputs
    outputs_json: str  # the canonical bytes that were stored and hashed (UTF-8)
    outputs_sha256: str
    recomputed_outputs_sha256: str  # computing the stored table again, now
    recomputes_identically: bool


def list_scenarios(
    connection: Connection, hypothesis_id: uuid.UUID, version: int | None = None
) -> list[Scenario]:
    rows = connection.execute(
        text(
            f"{_SELECT} WHERE s.hypothesis_id = :id"
            " AND (CAST(:version AS integer) IS NULL OR v.version = :version)"
            " ORDER BY v.version, s.created_at, s.id"
        ),
        {"id": hypothesis_id, "version": version},
    ).mappings()
    return [_scenario(connection, row) for row in list(rows)]


def get_scenario(
    connection: Connection, hypothesis_id: uuid.UUID, scenario_id: uuid.UUID
) -> Scenario | None:
    row = (
        connection.execute(
            text(f"{_SELECT} WHERE s.hypothesis_id = :h AND s.id = :id"),
            {"h": hypothesis_id, "id": scenario_id},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _scenario(connection, row)


_SELECT = (
    "SELECT s.*, v.version AS hypothesis_version FROM scenario s"
    " JOIN hypothesis_version v ON v.id = s.hypothesis_version_id"
)


def _scenario(connection: Connection, row: RowMapping) -> Scenario:
    table = AssumptionTable.model_validate(row["assumptions"])
    stored: str = row["outputs"]
    recomputed = outputs_json(compute(table))
    sources = resolve_sources(connection, table)
    return Scenario(
        id=row["id"],
        hypothesis_id=row["hypothesis_id"],
        hypothesis_version=row["hypothesis_version"],
        hypothesis_version_id=row["hypothesis_version_id"],
        company_id=row["company_id"],
        product=table.product,
        currency=table.currency,
        as_of=row["as_of"],
        model_version=row["model_version"],
        origin=row["origin"],
        investigation_task_id=row["investigation_task_id"],
        role_call_id=row["role_call_id"],
        note=row["note"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        inputs=[_input_view(table, spec.name, sources) for spec in INPUTS],
        assumptions=row["assumptions"],
        assumptions_sha256=row["assumptions_sha256"],
        outputs=ScenarioOutputs.model_validate(json.loads(stored)),
        outputs_json=stored,
        outputs_sha256=row["outputs_sha256"],
        recomputed_outputs_sha256=_sha256(recomputed),
        recomputes_identically=recomputed == stored.encode("utf-8"),
    )


def _input_view(
    table: AssumptionTable,
    name: InputName,
    sources: dict[InputName, ResolvedObservation | ResolvedAssertion],
) -> ScenarioInputView:
    spec = next(each for each in INPUTS if each.name == name)
    common: dict[str, Any] = {"name": name, "measure": spec.measure, "meaning": spec.meaning}
    each = table.inputs.get(name, MissingInput(kind="missing"))
    if isinstance(each, MissingInput):
        return ScenarioInputView(
            **common,
            kind="missing",
            low=None,
            base=None,
            high=None,
            basis=None,
            reason=each.reason,
            source=None,
        )
    low, base, high = (number(each.value(case)) for case in CASES)
    return ScenarioInputView(
        **common,
        kind=each.kind,
        low=low,
        base=base,
        high=high,
        basis=None if isinstance(each, SourcedInput) else each.basis,
        reason=None,
        source=sources.get(name),
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


# --- creating -------------------------------------------------------------------------------


class Scenarios:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(
        self,
        actor: Actor,
        hypothesis_id: uuid.UUID,
        version: int,
        *,
        assumptions: AssumptionTable | None,
        as_of: datetime | None,
        note: str | None,
    ) -> list[uuid.UUID]:
        """Compute and store the scenarios (see the module); their IDs."""
        with self._engine.begin() as connection:
            hypothesis = (
                connection.execute(
                    text(
                        "SELECT h.id, h.investigation_id, h.related_company_ids,"
                        " i.as_of AS investigation_as_of FROM hypothesis h"
                        " JOIN investigation i ON i.id = h.investigation_id WHERE h.id = :id"
                    ),
                    {"id": hypothesis_id},
                )
                .mappings()
                .one_or_none()
            )
            if hypothesis is None:
                raise ScenarioNotFound("hypothesis not found")
            version_id = connection.execute(
                text(
                    "SELECT id FROM hypothesis_version"
                    " WHERE hypothesis_id = :id AND version = :version"
                ),
                {"id": hypothesis_id, "version": version},
            ).scalar_one_or_none()
            if version_id is None:
                raise ScenarioNotFound(f"the Hypothesis has no version {version}")
            cutoff: datetime = as_of or hypothesis["investigation_as_of"]
            if assumptions is not None:
                related: list[uuid.UUID] = hypothesis["related_company_ids"]
                if assumptions.company_id not in related:
                    raise ScenarioError(
                        "the company isn't one of the Hypothesis's related companies"
                    )
                problems = check_sources(connection, assumptions, cutoff)
                if problems:
                    raise ScenarioInvalid([str(each) for each in problems])
                planned: list[_Planned] = [(assumptions, "researcher", None, None)]
            else:
                planned = self._analyst_tables(connection, hypothesis, cutoff)
            ids: list[uuid.UUID] = []
            for table, origin, task_id, role_call_id in planned:
                ids.append(
                    _insert(
                        connection,
                        actor,
                        hypothesis_id=hypothesis_id,
                        version_id=version_id,
                        table=table,
                        as_of=cutoff,
                        origin=origin,
                        task_id=task_id,
                        role_call_id=role_call_id,
                        note=note,
                    )
                )
        return ids

    def _analyst_tables(
        self, connection: Connection, hypothesis: RowMapping, cutoff: datetime
    ) -> list[_Planned]:
        task = (
            connection.execute(
                text(
                    "SELECT id, artifacts FROM investigation_task WHERE investigation_id = :id"
                    " AND role = 'financial_analyst' AND status = 'succeeded'"
                    " ORDER BY round DESC LIMIT 1"
                ),
                {"id": hypothesis["investigation_id"]},
            )
            .mappings()
            .one_or_none()
        )
        artifacts: dict[str, Any] = task["artifacts"] if task is not None else {}
        proposals: list[Any] = artifacts.get("scenario_proposals") or []
        if task is None or not proposals:
            raise ScenarioConflict(
                "the investigation's Financial Analyst proposed no scenario: send an"
                " assumption table"
            )
        role_call = artifacts.get("role_call_id")
        role_call_id = uuid.UUID(str(role_call)) if role_call else None
        planned: list[_Planned] = []
        for proposal in proposals:
            table = AssumptionTable.model_validate(proposal)
            problems = check_sources(connection, table, cutoff)
            if problems:
                inputs = dict(table.inputs)
                for problem in problems:
                    inputs[problem.input] = MissingInput(
                        kind="missing", reason=f"rejected at {cutoff.isoformat()}: {problem.reason}"
                    )
                table = table.model_copy(update={"inputs": inputs})
            planned.append((table, "financial_analyst", task["id"], role_call_id))
        return planned


def _insert(
    connection: Connection,
    actor: Actor,
    *,
    hypothesis_id: uuid.UUID,
    version_id: uuid.UUID,
    table: AssumptionTable,
    as_of: datetime,
    origin: Origin,
    task_id: uuid.UUID | None,
    role_call_id: uuid.UUID | None,
    note: str | None,
) -> uuid.UUID:
    outputs = compute(table)
    stored = outputs_json(outputs)
    scenario_id = uuid.uuid4()
    values = {
        "id": scenario_id,
        "hypothesis_id": hypothesis_id,
        "version_id": version_id,
        "company_id": table.company_id,
        "as_of": as_of,
        "model_version": outputs.model_version,
        "assumptions": json.dumps(table.canonical()),
        "assumptions_sha256": table.sha256(),
        "outputs": stored.decode("utf-8"),
        "outputs_sha256": _sha256(stored),
        "origin": origin,
        "task_id": task_id,
        "role_call_id": role_call_id,
        "note": note,
        "actor": actor.name,
    }
    connection.execute(
        text(
            "INSERT INTO scenario (id, hypothesis_id, hypothesis_version_id, company_id, as_of,"
            " model_version, assumptions, assumptions_sha256, outputs, outputs_sha256, origin,"
            " investigation_task_id, role_call_id, note, created_by) VALUES (:id,"
            " :hypothesis_id, :version_id, :company_id, :as_of, :model_version,"
            " CAST(:assumptions AS jsonb), :assumptions_sha256, :outputs, :outputs_sha256,"
            " :origin, :task_id, :role_call_id, :note, :actor)"
        ),
        values,
    )
    record(
        connection,
        actor,
        "scenario.created",
        entity_type="scenario",
        entity_id=str(scenario_id),
        new_hash=content_hash(
            {
                "hypothesis_version_id": version_id,
                "assumptions_sha256": values["assumptions_sha256"],
                "outputs_sha256": values["outputs_sha256"],
                "origin": origin,
            }
        ),
    )
    return scenario_id
