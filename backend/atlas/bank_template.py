"""The research bank's versioned template, and applying it (spec Part B stories 30-31).

The template file (`configs/hindsight/bank-template.json`) holds a `template_version` and the
Hindsight manifest (missions, dispositions, directives and the mental models). Applying it
goes through the gateway: a dry run, then the import, so a bad template never half-applies.
Each application is recorded with its version and manifest hash, and audited; a run takes its
template version from the bank's latest application.

Every mental model must say `refresh_after_consolidation: false` explicitly (Hindsight's
default for an imported model is `true`, and upstream issue #4532 is a refresh loop), and
give a `refresh_cron` and a positive `min_refresh_interval_seconds`, so no refresh can run
away (spec Part B story 28). A template that doesn't is invalid and is never sent.
"""

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError
from sqlalchemy import Connection, Engine, text

from atlas import audit
from atlas.hindsight import HindsightGateway, TemplateImportResult


class InvalidTemplate(ValueError):
    """The template file is missing, isn't JSON, or lacks its version or manifest."""


# A 5-field cron expression, as Hindsight's `refresh_cron` takes (UTC).
_CRON = r"^\S+( \S+){4}$"


class TemplateTrigger(BaseModel):
    """A template mental model's trigger: never after consolidation, on a cron, rate-limited."""

    model_config = ConfigDict(extra="allow", frozen=True)

    refresh_after_consolidation: Literal[False]  # required, and must be false
    refresh_cron: str = Field(pattern=_CRON)
    min_refresh_interval_seconds: int = Field(gt=0)


class TemplateMentalModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1)
    source_query: str = Field(min_length=1)
    max_tokens: int | None = None
    trigger: TemplateTrigger


_MENTAL_MODELS = TypeAdapter(list[TemplateMentalModel])


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: str = Field(min_length=1)  # Hindsight's manifest schema version ("1")
    mental_models: list[TemplateMentalModel] = []


class BankTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)

    template_version: str = Field(min_length=1)
    manifest: dict[str, JsonValue]

    @classmethod
    def load(cls, path: Path) -> "BankTemplate":
        try:
            template = cls.model_validate_json(path.read_bytes())
            manifest = _Manifest.model_validate(template.manifest)
        except OSError as error:
            raise InvalidTemplate(f"{path}: {error.strerror}") from None
        except ValidationError as error:
            raise InvalidTemplate(f"{path}: {error}") from None
        ids = [model.id for model in manifest.mental_models]
        if len(set(ids)) != len(ids):
            raise InvalidTemplate(f"{path}: mental model IDs must be unique (got {ids})")
        return template

    @property
    def mental_models(self) -> list[TemplateMentalModel]:
        """The template's mental models, in template order (validated by `load`)."""
        return _MENTAL_MODELS.validate_python(self.manifest.get("mental_models") or [])

    def mental_model(self, mental_model_id: str) -> TemplateMentalModel | None:
        return next((m for m in self.mental_models if m.id == mental_model_id), None)

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


def is_applied(connection: Connection, bank_id: str, template: "BankTemplate") -> bool:
    """Whether this exact template (same manifest hash) is the bank's latest application."""
    latest = _latest(connection, bank_id)
    return latest is not None and latest[1] == template.manifest_sha256


def _latest(connection: Connection, bank_id: str) -> tuple[str, str] | None:
    row = connection.execute(
        text(
            "SELECT template_version, manifest_sha256 FROM bank_template_application"
            " WHERE bank_id = :bank_id ORDER BY applied_at DESC, id LIMIT 1"
        ),
        {"bank_id": bank_id},
    ).one_or_none()
    return (row.template_version, row.manifest_sha256) if row else None
