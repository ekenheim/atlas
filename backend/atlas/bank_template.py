"""The research bank's versioned template, and applying it (spec Part B stories 30-31).

The template file (`configs/hindsight/bank-template.json`) holds a `template_version` and the
Hindsight manifest (missions, dispositions, directives; mental models from ticket 16). Applying
it goes through the gateway: a dry run, then the import, so a bad template never half-applies.
Each application is recorded with its version and manifest hash, and audited; a run takes its
template version from the bank's latest application.
"""

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from sqlalchemy import Connection, Engine, text

from atlas import audit
from atlas.hindsight import HindsightGateway, TemplateImportResult


class InvalidTemplate(ValueError):
    """The template file is missing, isn't JSON, or lacks its version or manifest."""


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: str = Field(min_length=1)  # Hindsight's manifest schema version ("1")


class BankTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)

    template_version: str = Field(min_length=1)
    manifest: dict[str, JsonValue]

    @classmethod
    def load(cls, path: Path) -> "BankTemplate":
        try:
            template = cls.model_validate_json(path.read_bytes())
            _Manifest.model_validate(template.manifest)
        except OSError as error:
            raise InvalidTemplate(f"{path}: {error.strerror}") from None
        except ValidationError as error:
            raise InvalidTemplate(f"{path}: {error}") from None
        return template

    @property
    def manifest_sha256(self) -> str:
        """SHA-256 of the canonical manifest JSON, so an unversioned edit is still visible."""
        canonical = json.dumps(self.manifest, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class TemplateApplied(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    bank_id: str
    template_version: str
    manifest_sha256: str
    dry_run: TemplateImportResult
    applied: TemplateImportResult
    applied_at: datetime
    audit_event_id: int


def apply_template(
    engine: Engine, gateway: HindsightGateway, template: BankTemplate, actor: audit.Actor
) -> TemplateApplied:
    """Dry-run then import the template into the gateway's bank, then record and audit it.

    Hindsight errors propagate before anything is recorded. Re-applying is safe: Hindsight
    matches directives by name and mental models by ID.
    """
    application = gateway.apply_bank_template(template.manifest)
    application_id = uuid.uuid4()
    with engine.begin() as connection:
        previous = _latest(connection, gateway.bank_id)
        row = connection.execute(
            text(
                "INSERT INTO bank_template_application (id, bank_id, template_version,"
                " manifest_sha256, dry_run_result, import_result)"
                " VALUES (:id, :bank_id, :version, :sha, CAST(:dry AS jsonb), CAST(:real AS jsonb))"
                " RETURNING applied_at"
            ),
            {
                "id": application_id,
                "bank_id": gateway.bank_id,
                "version": template.template_version,
                "sha": template.manifest_sha256,
                "dry": application.dry_run.model_dump_json(),
                "real": application.applied.model_dump_json(),
            },
        ).one()
        event = audit.record(
            connection,
            actor,
            "bank_template.applied",
            entity_type="hindsight_bank",
            entity_id=gateway.bank_id,
            old_hash=previous[1] if previous else None,
            new_hash=template.manifest_sha256,
        )
    return TemplateApplied(
        id=application_id,
        bank_id=gateway.bank_id,
        template_version=template.template_version,
        manifest_sha256=template.manifest_sha256,
        dry_run=application.dry_run,
        applied=application.applied,
        applied_at=row.applied_at,
        audit_event_id=event.id,
    )


def applied_template_version(connection: Connection, bank_id: str) -> str | None:
    """The version of the template most recently applied to the bank, or None if none was."""
    latest = _latest(connection, bank_id)
    return latest[0] if latest else None


def _latest(connection: Connection, bank_id: str) -> tuple[str, str] | None:
    row = connection.execute(
        text(
            "SELECT template_version, manifest_sha256 FROM bank_template_application"
            " WHERE bank_id = :bank_id ORDER BY applied_at DESC, id LIMIT 1"
        ),
        {"bank_id": bank_id},
    ).one_or_none()
    return (row.template_version, row.manifest_sha256) if row else None
