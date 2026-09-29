"""The mental model read side: content, history and resolved citations (spec Part B story 29).

A mental model's content and its history come from Hindsight (the gateway's model and
history reads). Its citations, and each earlier revision's, are resolved like any reflect
answer's by the provenance resolver: every cited memory to a Source Version section (or why
not), and every double-quoted passage in the content against the archived parsed text. Only
resolved citations are presented as Evidence. Atlas's own refresh records come with it.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import Engine, text

from atlas.archive import Archive
from atlas.bank_template import BankTemplate, TemplateMentalModel
from atlas.hindsight import HindsightGateway, HindsightNotFound
from atlas.research.provenance import (
    Citation,
    CitationState,
    Evidence,
    ProvenanceResolver,
    evidence_from,
    state_counts,
)
from atlas.research.quotes import QUOTE_RULE

# Atlas's refresh records shown with a model, newest first.
REFRESHES_SHOWN = 30


class RefreshTrigger(BaseModel):
    """When the model is refreshed, as the bank template defines it."""

    refresh_after_consolidation: bool
    refresh_cron: str  # UTC
    min_refresh_interval_seconds: int


class MentalModelRefresh(BaseModel):
    """One decision of a `refresh_mental_model` job."""

    id: uuid.UUID
    job_id: uuid.UUID
    scheduled_for: date | None  # None: enqueued by hand
    template_version: str | None
    min_refresh_interval_seconds: int
    status: Literal["skipped", "submitted", "completed", "failed"]
    skip_reason: Literal["min_interval", "not_stale"] | None
    operation_id: str | None
    operation_status: str | None
    error: str | None
    error_class: Literal["quota", "unavailable", "permanent"] | None
    previous_refreshed_at: datetime | None  # Hindsight's last_refreshed_at before
    refreshed_at: datetime | None  # after (for a skip: as found)
    content_sha256: str | None
    requested_at: datetime
    completed_at: datetime | None


class MentalModelRevision(BaseModel):
    """The content a refresh replaced at `changed_at`, with its citations resolved."""

    changed_at: datetime
    previous_content: str | None
    citations: list[Citation]
    counts: dict[CitationState, int]


class MentalModelView(BaseModel):
    id: str
    name: str
    source_query: str
    trigger: RefreshTrigger
    bank_id: str
    in_bank: bool  # False: the template hasn't been applied to the bank yet
    content: str | None
    last_refreshed_at: datetime | None
    is_stale: bool | None  # Hindsight: a memory in scope is newer than the last refresh
    citations: list[Citation]  # every cited memory and quote, with its state
    counts: dict[CitationState, int]
    evidence: list[Evidence]  # the sections behind resolved citations only
    evidence_missing: bool | None  # in the bank, with no resolved citation
    quote_rule: str
    history: list[MentalModelRevision]  # newest first
    refreshes: list[MentalModelRefresh]  # Atlas's refresh records, newest first


class MentalModelList(BaseModel):
    bank_id: str
    template_version: str  # of the template file the models are defined in
    mental_models: list[MentalModelView]


class MentalModelReader:
    def __init__(
        self, engine: Engine, archive: Archive, gateway: HindsightGateway, template: BankTemplate
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._gateway = gateway
        self._template = template
        self._resolver = ProvenanceResolver(engine, archive, gateway)  # one per read

    def all(self) -> MentalModelList:
        return MentalModelList(
            bank_id=self._gateway.bank_id,
            template_version=self._template.template_version,
            mental_models=[self._view(model) for model in self._template.mental_models],
        )

    def one(self, mental_model_id: str) -> MentalModelView | None:
        """The model, or None when the template defines no such model."""
        definition = self._template.mental_model(mental_model_id)
        return None if definition is None else self._view(definition)

    def _view(self, definition: TemplateMentalModel) -> MentalModelView:
        trigger = RefreshTrigger(
            refresh_after_consolidation=definition.trigger.refresh_after_consolidation,
            refresh_cron=definition.trigger.refresh_cron,
            min_refresh_interval_seconds=definition.trigger.min_refresh_interval_seconds,
        )
        try:
            model = self._gateway.get_mental_model(definition.id)
        except HindsightNotFound:
            model = None
        citations: list[Citation] = []
        history: list[MentalModelRevision] = []
        if model is not None:
            citations = self._resolver.resolve_answer(model.content or "", model.based_on)
            for revision in self._gateway.mental_model_history(definition.id):
                resolved = self._resolver.resolve_answer(
                    revision.previous_content or "", revision.based_on
                )
                history.append(
                    MentalModelRevision(
                        changed_at=revision.changed_at,
                        previous_content=revision.previous_content,
                        citations=resolved,
                        counts=state_counts(resolved),
                    )
                )
        evidence = evidence_from(citations)
        return MentalModelView(
            id=definition.id,
            name=definition.name,
            source_query=definition.source_query,
            trigger=trigger,
            bank_id=self._gateway.bank_id,
            in_bank=model is not None,
            content=model.content if model is not None else None,
            last_refreshed_at=model.last_refreshed_at if model is not None else None,
            is_stale=model.is_stale if model is not None else None,
            citations=citations,
            counts=state_counts(citations),
            evidence=evidence,
            evidence_missing=not evidence if model is not None else None,
            quote_rule=QUOTE_RULE,
            history=history,
            refreshes=self._refreshes(definition.id),
        )

    def _refreshes(self, mental_model_id: str) -> list[MentalModelRefresh]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT * FROM mental_model_refresh"
                    " WHERE bank_id = :bank AND mental_model_id = :model"
                    " ORDER BY requested_at DESC, updated_at DESC LIMIT :limit"
                ),
                {"bank": self._gateway.bank_id, "model": mental_model_id, "limit": REFRESHES_SHOWN},
            ).mappings()
            return [MentalModelRefresh.model_validate(dict(row)) for row in rows]
