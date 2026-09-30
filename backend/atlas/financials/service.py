"""Storing and reading financial observations.

`normalize_source_version` reads an archived companyfacts Source Version, turns its facts
into observations (`atlas.financials.xbrl.normalize`, with the filer's submissions index for
acceptance times) and inserts the new ones, with one `financial_normalization` row and one
audit event, in one transaction, in filing order so every restatement link names a stored
row. It runs at most once per (version, normalizer version). A failed attempt stores nothing;
the ingest records it with `record_normalization_failure` (`financial_normalization_failure`,
audited) and the version is tried again at the next ingest.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import Connection, Engine, text

from atlas.archive import Archive
from atlas.audit import Actor, content_hash, record
from atlas.financials.xbrl import (
    Linkage,
    Observation,
    ObservationBasis,
    SuspectReason,
    normalize,
    parse_companyfacts,
)
from atlas.sources.adapter import SecFiling

# Bump when the normalization rules change, so stored versions are normalized again.
NORMALIZER_VERSION = "xbrl-normalizer-v1"


@dataclass(frozen=True)
class NormalizationSummary:
    id: uuid.UUID
    source_version_id: uuid.UUID
    normalizer_version: str
    facts_read: int
    observations_created: int
    created: bool  # False: this version was already normalized, nothing was done


def normalize_source_version(
    engine: Engine,
    archive: Archive,
    actor: Actor,
    *,
    source_version_id: uuid.UUID,
    company_id: uuid.UUID,
    filings: Sequence[SecFiling],
) -> NormalizationSummary:
    with engine.begin() as connection:
        done = _normalization(connection, source_version_id)
        if done is not None:
            return done
        version = (
            connection.execute(
                text(
                    "SELECT v.object_uri, a.available_at, d.source_type"
                    " FROM source_version v"
                    " JOIN source_version_availability a ON a.source_version_id = v.id"
                    " JOIN source_document d ON d.id = v.source_document_id"
                    " WHERE v.id = :id"
                ),
                {"id": source_version_id},
            )
            .mappings()
            .one()
        )
        if version["source_type"] != "xbrl_companyfacts":
            raise ValueError(f"source version {source_version_id} is not XBRL companyfacts")
        companyfacts = parse_companyfacts(archive.get(version["object_uri"]))
        # One filer's normalizations are serialized, so linkage sees every stored predecessor.
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('financial_observation:' || :cik))"),
            {"cik": companyfacts.cik},
        )
        # A concurrent normalization of this version may have committed while we waited.
        done = _normalization(connection, source_version_id)
        if done is not None:
            return done
        existing = _load(connection, "cik = :cik", {"cik": companyfacts.cik})
        new = normalize(
            companyfacts,
            filings,
            source_version_id=source_version_id,
            snapshot_available_at=version["available_at"],
            existing=existing,
        )
        _check_links(existing, new)
        if new:
            # In filing order, so each restatement link names a row already inserted.
            connection.execute(_INSERT, [_row(o, company_id) for o in new])
        summary = NormalizationSummary(
            id=uuid.uuid4(),
            source_version_id=source_version_id,
            normalizer_version=NORMALIZER_VERSION,
            facts_read=len(companyfacts.facts),
            observations_created=len(new),
            created=True,
        )
        connection.execute(
            text(
                "INSERT INTO financial_normalization (id, source_version_id, company_id,"
                " normalizer_version, facts_read, observations_created) VALUES (:id,"
                " :source_version_id, :company_id, :normalizer_version, :facts_read,"
                " :observations_created)"
            ),
            {
                "id": summary.id,
                "source_version_id": source_version_id,
                "company_id": company_id,
                "normalizer_version": NORMALIZER_VERSION,
                "facts_read": summary.facts_read,
                "observations_created": summary.observations_created,
            },
        )
        record(
            connection,
            actor,
            "financial_normalization.created",
            entity_type="financial_normalization",
            entity_id=str(summary.id),
            new_hash=content_hash(
                {
                    "source_version_id": source_version_id,
                    "normalizer_version": NORMALIZER_VERSION,
                    "observation_ids": sorted(str(o.id) for o in new),
                }
            ),
        )
    return summary


class NormalizationLinkError(Exception):
    """A new observation's predecessor is neither stored nor inserted before it."""


def _check_links(existing: Sequence[Observation], new: Sequence[Observation]) -> None:
    present = {observation.id for observation in existing}
    for observation in new:
        previous = observation.previous_observation_id
        if previous is not None and previous not in present:
            raise NormalizationLinkError(
                f"observation {observation.id} ({observation.concept}, {observation.accession})"
                f" links to {previous}, which is neither stored nor inserted before it"
            )
        present.add(observation.id)


@dataclass(frozen=True)
class NormalizationFailure:
    id: uuid.UUID
    source_version_id: uuid.UUID
    normalizer_version: str
    error_class: str
    error: str


def record_normalization_failure(
    engine: Engine,
    actor: Actor,
    *,
    source_version_id: uuid.UUID,
    company_id: uuid.UUID,
    error: Exception,
    job_id: uuid.UUID | None = None,
) -> NormalizationFailure:
    """Record (insert-only, audited) that normalizing `source_version_id` failed. Nothing of
    the attempt was stored, so the version stays unnormalized and is tried again later."""
    failure = NormalizationFailure(
        id=uuid.uuid4(),
        source_version_id=source_version_id,
        normalizer_version=NORMALIZER_VERSION,
        error_class=type(error).__name__,
        error=str(error)[:_MAX_ERROR],
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO financial_normalization_failure (id, source_version_id,"
                " company_id, normalizer_version, error_class, error, job_id) VALUES (:id,"
                " :source_version_id, :company_id, :normalizer_version, :error_class, :error,"
                " :job_id)"
            ),
            {
                "id": failure.id,
                "source_version_id": source_version_id,
                "company_id": company_id,
                "normalizer_version": NORMALIZER_VERSION,
                "error_class": failure.error_class,
                "error": failure.error,
                "job_id": job_id,
            },
        )
        record(
            connection,
            actor,
            "financial_normalization.failed",
            entity_type="financial_normalization_failure",
            entity_id=str(failure.id),
            new_hash=content_hash(
                {
                    "source_version_id": source_version_id,
                    "normalizer_version": NORMALIZER_VERSION,
                    "error_class": failure.error_class,
                    "error": failure.error,
                }
            ),
        )
    return failure


_MAX_ERROR = 2000  # an IntegrityError's message carries its whole parameter list


def is_normalized(connection: Connection, source_version_id: uuid.UUID) -> bool:
    return _normalization(connection, source_version_id) is not None


def _normalization(
    connection: Connection, source_version_id: uuid.UUID
) -> NormalizationSummary | None:
    row = (
        connection.execute(
            text(
                "SELECT id, source_version_id, normalizer_version, facts_read,"
                " observations_created FROM financial_normalization"
                " WHERE source_version_id = :id AND normalizer_version = :normalizer"
            ),
            {"id": source_version_id, "normalizer": NORMALIZER_VERSION},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else NormalizationSummary(**row, created=False)


_COLUMNS = (
    "id, company_id, cik, source_version_id, accession, form, filed, fiscal_year,"
    " fiscal_period, frame, taxonomy, concept, unit, currency, period_start, period_end,"
    " value, available_at, available_at_basis, accepted_at, previous_observation_id,"
    " linkage, suspect_reasons"
)
_VALUES = ", ".join(f":{column.strip()}" for column in _COLUMNS.split(","))
_INSERT = text(f"INSERT INTO financial_observation ({_COLUMNS}) VALUES ({_VALUES})")  # noqa: S608


def _row(observation: Observation, company_id: uuid.UUID) -> dict[str, Any]:
    return {
        "id": observation.id,
        "company_id": company_id,
        "cik": observation.cik,
        "source_version_id": observation.source_version_id,
        "accession": observation.accession,
        "form": observation.form,
        "filed": observation.filed,
        "fiscal_year": observation.fiscal_year,
        "fiscal_period": observation.fiscal_period,
        "frame": observation.frame,
        "taxonomy": observation.taxonomy,
        "concept": observation.concept,
        "unit": observation.unit,
        "currency": observation.currency,
        "period_start": observation.period_start,
        "period_end": observation.period_end,
        "value": observation.value,
        "available_at": observation.available_at,
        "available_at_basis": observation.available_at_basis,
        "accepted_at": observation.accepted_at,
        "previous_observation_id": observation.previous_observation_id,
        "linkage": observation.linkage,
        "suspect_reasons": list(observation.suspect_reasons),
    }


def _load(connection: Connection, where: str, params: dict[str, Any]) -> list[Observation]:
    rows = connection.execute(
        text(f"SELECT {_COLUMNS} FROM financial_observation WHERE {where}"),  # noqa: S608
        params,
    ).mappings()
    return [_observation(row) for row in rows]


def _observation(row: Any) -> Observation:
    return Observation(
        id=cast(uuid.UUID, row["id"]),
        cik=cast(str, row["cik"]),
        source_version_id=cast(uuid.UUID, row["source_version_id"]),
        taxonomy=cast(str, row["taxonomy"]),
        concept=cast(str, row["concept"]),
        unit=cast(str, row["unit"]),
        period_start=cast(date | None, row["period_start"]),
        period_end=cast(date, row["period_end"]),
        value=cast(Decimal, row["value"]),
        accession=cast(str, row["accession"]),
        form=cast(str, row["form"]),
        filed=cast(date, row["filed"]),
        fiscal_year=cast(int | None, row["fiscal_year"]),
        fiscal_period=cast(str | None, row["fiscal_period"]),
        frame=cast(str | None, row["frame"]),
        available_at=cast(datetime, row["available_at"]),
        available_at_basis=cast(ObservationBasis, row["available_at_basis"]),
        accepted_at=cast(datetime | None, row["accepted_at"]),
        previous_observation_id=cast(uuid.UUID | None, row["previous_observation_id"]),
        linkage=cast(Linkage, row["linkage"]),
        suspect_reasons=tuple(cast(list[SuspectReason], row["suspect_reasons"])),
    )


def company_observations(connection: Connection, company_id: uuid.UUID) -> list[Observation]:
    return _load(connection, "company_id = :company_id", {"company_id": company_id})


def get_observation(connection: Connection, observation_id: uuid.UUID) -> Observation | None:
    found = _load(connection, "id = :id", {"id": observation_id})
    return found[0] if found else None


def key_history(connection: Connection, observation: Observation) -> list[Observation]:
    """Every observation of `observation`'s period key, in filing order."""
    history = _load(
        connection,
        "cik = :cik AND taxonomy = :taxonomy AND concept = :concept AND unit = :unit"
        " AND period_start IS NOT DISTINCT FROM CAST(:start AS date) AND period_end = :end",
        {
            "cik": observation.cik,
            "taxonomy": observation.taxonomy,
            "concept": observation.concept,
            "unit": observation.unit,
            "start": observation.period_start,
            "end": observation.period_end,
        },
    )
    return sorted(history, key=lambda o: o.order)
