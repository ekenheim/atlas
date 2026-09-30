"""The owner's decision on a proposed update, each in one audited transaction.

- **Accept** starts a correction (spec §5.6; atlas.hypotheses): a new, unpublished version
  from the Hypothesis's latest one, whose findings resting on a contradicted Assertion are
  marked `needs_review` with the update's summary as a limitation. The owner edits it with
  further corrections and publishes it behind the publish gate, as any correction. Audited
  `hypothesis.corrected` (or `hypothesis.version_created` when the latest version was a
  draft) and `proposed_update.accepted`.
- **Dismiss** keeps the version as it is, with the owner's reason
  (`proposed_update.dismissed`).

Either resolves the update once; the published version and its Research Snapshot are never
touched.
"""

import uuid

from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.audit import Actor, content_hash, record
from atlas.hypotheses.model import HypothesisContent, version_from_row
from atlas.hypotheses.service import (
    HypothesisConflict,
    HypothesisError,
    HypothesisNotFound,
    insert_version,
)
from atlas.proposed_updates.model import AffectedFinding

__all__ = ["HypothesisError", "ProposedUpdates"]


class ProposedUpdates:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def accept(self, actor: Actor, proposed_update_id: uuid.UUID, note: str | None) -> int:
        """Start the correction; the new version's number."""
        with self._engine.begin() as connection:
            update = _lock_open(connection, proposed_update_id)
            hypothesis = (
                connection.execute(
                    text("SELECT * FROM hypothesis WHERE id = :id FOR UPDATE"),
                    {"id": update["hypothesis_id"]},
                )
                .mappings()
                .one()
            )
            if hypothesis["status"] in ("closed", "rejected"):
                raise HypothesisConflict(
                    f"the Hypothesis is {hypothesis['status']}: dismiss the update instead"
                )
            base = version_from_row(
                connection.execute(
                    text(
                        "SELECT * FROM hypothesis_version WHERE hypothesis_id = :id"
                        " ORDER BY version DESC LIMIT 1"
                    ),
                    {"id": update["hypothesis_id"]},
                )
                .mappings()
                .one()
            )
            contradicted = {
                assertion_id
                for each in update["affected_findings"]
                for assertion_id in AffectedFinding.model_validate(each).assertion_ids
            }
            limitation = f"Proposed update {update['id']}: {update['summary']}"
            findings = [
                finding.model_copy(
                    update={
                        "needs_review": True,
                        "limitations": [*finding.limitations, limitation],
                    }
                )
                if any(span.assertion_id in contradicted for span in finding.source_spans)
                else finding
                for finding in base.content.findings
            ]
            content = HypothesisContent.model_validate(
                base.content.model_dump() | {"findings": findings}
            )
            version = insert_version(
                connection,
                update["hypothesis_id"],
                base.version + 1,
                origin="correction",
                based_on=base.version,
                content=content,
                provenance=base.provenance.model_copy(
                    update={"draft_run_id": None, "editor_role_call_id": None}
                ),
                note=note or f"Accepts proposed update {update['id']}: {update['summary']}",
                created_by=actor.name,
            )
            connection.execute(
                text("UPDATE hypothesis SET updated_at = now() WHERE id = :id"),
                {"id": update["hypothesis_id"]},
            )
            record(
                connection,
                actor,
                "hypothesis.corrected" if base.published else "hypothesis.version_created",
                entity_type="hypothesis_version",
                entity_id=str(version.id),
                old_hash=base.content_sha256,
                new_hash=version.content_sha256,
            )
            _resolve(
                connection,
                actor,
                update,
                "accepted",
                note=note,
                reason=None,
                correction_version=version.version,
            )
        return version.version

    def dismiss(self, actor: Actor, proposed_update_id: uuid.UUID, reason: str) -> None:
        with self._engine.begin() as connection:
            update = _lock_open(connection, proposed_update_id)
            _resolve(
                connection,
                actor,
                update,
                "dismissed",
                note=None,
                reason=reason,
                correction_version=None,
            )


def _lock_open(connection: Connection, proposed_update_id: uuid.UUID) -> RowMapping:
    row = (
        connection.execute(
            text("SELECT * FROM proposed_update WHERE id = :id FOR UPDATE"),
            {"id": proposed_update_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HypothesisNotFound("proposed update not found")
    if row["state"] != "open":
        raise HypothesisConflict(f"the proposed update is already {row['state']}")
    return row


def _resolve(
    connection: Connection,
    actor: Actor,
    update: RowMapping,
    state: str,
    *,
    note: str | None,
    reason: str | None,
    correction_version: int | None,
) -> None:
    after = (
        connection.execute(
            text(
                "UPDATE proposed_update SET state = :state, resolved_by = :actor,"
                " resolved_at = now(), resolution_note = :note, dismiss_reason = :reason,"
                " correction_version = :correction WHERE id = :id RETURNING *"
            ),
            {
                "id": update["id"],
                "state": state,
                "actor": actor.name,
                "note": note,
                "reason": reason,
                "correction": correction_version,
            },
        )
        .mappings()
        .one()
    )
    record(
        connection,
        actor,
        f"proposed_update.{state}",
        entity_type="proposed_update",
        entity_id=str(update["id"]),
        old_hash=content_hash(dict(update)),
        new_hash=content_hash(dict(after)),
    )
