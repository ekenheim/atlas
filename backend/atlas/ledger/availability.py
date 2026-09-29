"""Recorded availability corrections for Source Versions ingested before a rule tightened.

A Source Version is immutable, so when the availability rule becomes more conservative the
versions already recorded are not edited. Instead `correct_availability` appends one
correction per affected version (`source_version_availability_correction`, migration 0012),
audited in the same transaction, and every reader takes availability from the
`source_version_availability` view: the correction if any, else the version's own.

Today's rule: an EDGAR filing is available when EDGAR disseminated it (docs/decisions.md,
"EDGAR dissemination time"). Versions recorded with basis `sec_acceptance` before that rule
were dated at acceptance even when EDGAR held them to the next business day. Their
`metadata.acceptance_datetime` and `metadata.form` give everything needed to recompute it.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.sources.edgar import PROVIDER_ID as SEC_EDGAR
from atlas.sources.edgar_calendar import EdgarCalendarRangeError, edgar_dissemination_time

log = logging.getLogger(__name__)

SEC_DISSEMINATION_REASON = (
    "accepted outside EDGAR's dissemination window: available at the next business day's"
    " opening (docs/decisions.md, EDGAR dissemination time)"
)


@dataclass
class CorrectionSummary:
    corrected: list[str] = field(default_factory=list[str])  # Source Version IDs
    out_of_calendar: list[str] = field(default_factory=list[str])  # left as recorded


def correct_availability(engine: Engine, actor: Actor) -> CorrectionSummary:
    """Record a correction for each SEC version dated at acceptance that EDGAR held back.

    Idempotent: a version with a correction is never considered again. A version whose dates
    fall outside the EDGAR holiday table is left as recorded, reported and logged.
    """
    summary = CorrectionSummary()
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT v.id, v.available_at, v.available_at_basis, v.metadata"
                " FROM source_version v JOIN source_document d ON d.id = v.source_document_id"
                " WHERE d.provider = :provider AND v.available_at_basis = 'sec_acceptance'"
                " AND v.metadata ? 'acceptance_datetime' AND NOT EXISTS (SELECT FROM"
                " source_version_availability_correction c WHERE c.source_version_id = v.id)"
                " ORDER BY v.ingested_at, v.id FOR UPDATE OF v"
            ),
            {"provider": SEC_EDGAR},
        ).mappings()
        for row in list(rows):
            metadata: dict[str, Any] = row["metadata"]
            accepted = datetime.fromisoformat(metadata["acceptance_datetime"])
            try:
                public = edgar_dissemination_time(accepted, metadata.get("form") or "")
            except EdgarCalendarRangeError as error:
                log.warning(f"source version {row['id']} left as recorded: {error}")
                summary.out_of_calendar.append(str(row["id"]))
                continue
            if public <= row["available_at"]:
                continue
            correction: dict[str, Any] = {
                "id": uuid.uuid4(),
                "source_version_id": row["id"],
                "available_at": public,
                "available_at_basis": "sec_dissemination",
                "reason": SEC_DISSEMINATION_REASON,
            }
            connection.execute(
                text(
                    "INSERT INTO source_version_availability_correction (id,"
                    " source_version_id, available_at, available_at_basis, reason) VALUES"
                    " (:id, :source_version_id, :available_at, :available_at_basis, :reason)"
                ),
                correction,
            )
            record(
                connection,
                actor,
                "source_version.availability_corrected",
                entity_type="source_version",
                entity_id=str(row["id"]),
                old_hash=content_hash(
                    {
                        "available_at": row["available_at"],
                        "available_at_basis": row["available_at_basis"],
                    }
                ),
                new_hash=content_hash(correction),
            )
            summary.corrected.append(str(row["id"]))
    return summary
