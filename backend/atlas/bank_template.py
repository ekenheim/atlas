"""The research bank's versioned template, and applying it (spec Part B stories 30-31).

The template file (`configs/hindsight/bank-template.json`) holds a `template_version` and the
Hindsight manifest (missions, dispositions, directives and the mental models). Applying it
goes through the gateway: a dry run, then the import, so a bad template never half-applies.
Each application is recorded with its version and manifest hash, and audited; a run takes its
template version from the bank's latest application.

Every mental model must say `refresh_after_consolidation: false` explicitly (Hindsight's
default for an imported model is `true`, and upstream issue #4532 is a refresh loop), and
give a positive `min_refresh_interval_seconds`, so no refresh can run away (spec Part B story
28). Since memory-quality ticket 10 Atlas's daily job is the only scheduler: every model
says `refresh_cron: null` explicitly (Hindsight's own cron would refresh outside Atlas's
budget, uncounted), and `exclude_mental_models: true` (no model reads another). A template
that breaks any of these is invalid and is never sent.

The research bank's template must also say `enable_auto_consolidation: false` (memory-quality
ticket 19): Atlas decides when Memory consolidates (the `consolidate` job,
`atlas.retention.consolidation`), so Hindsight never consolidates by itself after a retain. A
template that leaves it out, or turns it on, is invalid too. Replay and evaluation banks take
the template without the field (`without_auto_consolidation_setting`), as before.

It must also pin the server defaults Atlas's memory relies on (memory-quality ticket 23,
template 1.5.0): the temporal, graph, keyword and rerank arms of recall, the stored document
text, free-form entities, the extraction mode, the chunk size and a consolidation round's
size are each set explicitly, so a change of the server's defaults (by the owner or a
Hindsight upgrade) cannot change Atlas's memory silently. A template that leaves one out, or
sets it to null (the server's default), is invalid. Replay and evaluation banks take them as
the template sets them.
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
from atlas.hindsight import Budget, HindsightGateway, TemplateImportResult


class InvalidTemplate(ValueError):
    """The template file is missing, isn't JSON, or lacks its version or manifest."""


class TemplateTrigger(BaseModel):
    """A template mental model's trigger: never refreshed by Hindsight on its own (not after
    consolidation, no cron: Atlas's daily job refreshes it), rate-limited, and reading
    memories only, never another mental model."""

    model_config = ConfigDict(extra="allow", frozen=True)

    refresh_after_consolidation: Literal[False]  # required, and must be false
    refresh_cron: None  # required, and must be null: Atlas's job is the only scheduler
    min_refresh_interval_seconds: int = Field(gt=0)
    exclude_mental_models: Literal[True]  # required, and must be true
    budget: Budget | None = None  # Hindsight: null means `mid` for a refresh
    keep_trace: bool = False


class TemplateMentalModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1)
    source_query: str = Field(min_length=1)
    tags: list[str] = []  # the memories a refresh reads (Hindsight: all_strict when tagged)
    max_tokens: int | None = None
    trigger: TemplateTrigger


_MENTAL_MODELS = TypeAdapter(list[TemplateMentalModel])
AUTO_CONSOLIDATION = "enable_auto_consolidation"


class _Bank(BaseModel):
    """The research bank's settings: Hindsight never consolidates by itself, and the server
    defaults Atlas's memory relies on are set explicitly (memory-quality ticket 23)."""

    model_config = ConfigDict(extra="allow", strict=True)
    enable_auto_consolidation: Literal[False]  # required, and must be false
    # Pinned: required and never null, so no server default decides them (template 1.5.0).
    enable_temporal_retrieval: bool
    enable_graph_retrieval: bool
    enable_text_search: bool
    enable_reranking: bool
    store_document_text: bool
    entities_allow_free_form: bool
    retain_extraction_mode: str = Field(min_length=1)
    retain_chunk_size: int = Field(gt=0)
    consolidation_max_memories_per_round: int = Field(gt=0)


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: str = Field(min_length=1)  # Hindsight's manifest schema version ("1")
    bank: _Bank
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

    def without_auto_consolidation_setting(self) -> "BankTemplate":
        """This template with the bank's `enable_auto_consolidation` left to the server's
        default, for a replay or evaluation bank, which consolidates as it did before."""
        bank = self.manifest.get("bank")
        if not isinstance(bank, dict):
            return self
        settings = {key: value for key, value in bank.items() if key != AUTO_CONSOLIDATION}
        return self.model_copy(update={"manifest": {**self.manifest, "bank": settings}})

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
