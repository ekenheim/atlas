"""Assertions: statements bound to an exact quote span of one Source Version, then reviewed.

A Claim becomes an Assertion only once its span is confirmed in the archived text
(CONTEXT.md). So `Assertions.create` reads the Source Version's archived parse and
accepts the Assertion only if `parsed_text[span_start:span_end] == quote` exactly: no
case folding, no whitespace normalization, no searching elsewhere. Offsets are
characters (Unicode code points) of the parsed text, as served by
`GET /source-versions/{id}/content?kind=parsed` (UTF-8). `page_or_anchor` is a label for
people; the offsets are the binding. When it is omitted and the Source Version has page
anchors (a PDF), it is the page the span lies on, by the page's label: "page 7", or
"page iv (PDF page 2)" when the label isn't the page's number, and "pages 7-8" (with an
en dash) across pages.

**The parse.** A span is in one parse of the Source Version, recorded on the Assertion as
`parser_version`: the parse the version was recorded with unless the request names another of
its parses (a re-parse under a later parser, `source_parse`; pilot-fixes ticket 11). The span
is checked against that parse only, and an Assertion never moves to another parse: a quote on
a re-parse is a new Assertion.

Review follows build plan §5.4's `verification_status` (the API calls it `review_state`):

- a new Assertion is `unreviewed`
- `unreviewed`, `corroborated` and `disputed` are open: each may move to any other
  state except back to `unreviewed`
- `rejected` and `superseded` are final
- `superseded` names a successor Assertion (`superseded_by`), which must exist, differ,
  and not itself be rejected or superseded. The superseded Assertion's statement is
  never edited; a correction is the successor.

Every create and review writes an audit event in the same transaction, with the
configured actor. Migration 0006 enforces the same invariants in the database.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
from sqlalchemy import Connection, Engine, text

from atlas.archive import Archive
from atlas.audit import Actor, content_hash, record
from atlas.proposed_updates.triggers import on_assertion_reviewed

EpistemicType = Literal[
    "direct_source_statement",
    "company_claim",
    "third_party_report",
    "agent_inference",
    "quantitative_derived",
]
ReviewState = Literal["unreviewed", "corroborated", "disputed", "rejected", "superseded"]

EXTRACTOR_VERSION = "manual"  # researcher-created; the Investigator passes its own
_PARSED = ("parsed", "incomplete")
_OPEN: frozenset[ReviewState] = frozenset({"unreviewed", "corroborated", "disputed"})
_REVIEWED: frozenset[ReviewState] = frozenset(
    {"corroborated", "disputed", "rejected", "superseded"}
)


def allowed_transitions(state: ReviewState) -> frozenset[ReviewState]:
    """The review states an Assertion in `state` may move to."""
    return _REVIEWED - {state} if state in _OPEN else frozenset()


class AssertionCreate(BaseModel):
    """A researcher's new Assertion. Review fields are not accepted: it starts unreviewed."""

    model_config = ConfigDict(extra="forbid")

    subject_company_id: uuid.UUID
    predicate: str = Field(min_length=1)
    object_company_id: uuid.UUID | None = None
    value_json: JsonValue = None
    source_version_id: uuid.UUID
    quote: str = Field(min_length=1, description="exactly the parsed text at the offsets")
    span_start: int = Field(ge=0, description="first character of the quote in the parse")
    span_end: int = Field(ge=0, description="one past the quote's last character")
    page_or_anchor: str | None = None
    event_start: datetime | None = None
    event_end: datetime | None = None
    epistemic_type: EpistemicType
    parser_version: str | None = Field(
        default=None,
        description="the parse the offsets are in (one of the version's `parses`); default the"
        " parse the version was recorded with",
    )

    @field_validator("predicate", "page_or_anchor")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def _event_order(self) -> Self:
        if self.event_start and self.event_end and self.event_end < self.event_start:
            raise ValueError("event_end must not be before event_start")
        return self


class AssertionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_state: ReviewState
    superseded_by: uuid.UUID | None = Field(
        default=None, description="the successor; required exactly when superseding"
    )


class Assertion(BaseModel):
    id: uuid.UUID
    subject_company_id: uuid.UUID
    predicate: str
    object_company_id: uuid.UUID | None
    value_json: JsonValue
    source_version_id: uuid.UUID
    quote: str
    span_start: int
    span_end: int
    page_or_anchor: str | None
    event_start: datetime | None
    event_end: datetime | None
    epistemic_type: EpistemicType
    review_state: ReviewState
    independence_family_id: uuid.UUID | None
    extracted_at: datetime
    extractor_version: str
    created_by: str
    parser_version: str  # the parse of the Source Version the span is in
    reviewer_id: str | None
    reviewed_at: datetime | None
    superseded_by: uuid.UUID | None


class AssertionRecorded(BaseModel):
    """A mutation's result: the Assertion as it now is, and the audit event recording it."""

    assertion: Assertion
    audit_event_id: int


class AssertionRefused(Exception):
    """A create or review the ledger refuses; `code` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class InvalidAssertion(AssertionRefused):
    """The request cannot be recorded as asked (e.g. the quote is not at its offsets)."""


class InvalidTransition(AssertionRefused):
    """The review does not follow from the Assertion's current state."""


class AssertionNotFound(AssertionRefused):
    def __init__(self) -> None:
        super().__init__("not_found", "assertion not found")


_SELECT = """
    SELECT id, subject_company_id, predicate, object_company_id, value_json,
           source_version_id, quote, span_start, span_end, page_or_anchor, event_start,
           event_end, epistemic_type, verification_status AS review_state,
           independence_family_id, extracted_at, extractor_version, created_by,
           parser_version, reviewer_id, reviewed_at, superseded_by
    FROM assertion
"""


# Each filter applies only when its parameter is set.
_FILTER = """
    WHERE (CAST(:company AS uuid) IS NULL
           OR subject_company_id = :company OR object_company_id = :company)
      AND (CAST(:state AS text) IS NULL OR verification_status = :state)
      AND (CAST(:version AS uuid) IS NULL OR source_version_id = :version)
"""
_COUNT = "SELECT count(*) FROM assertion" + _FILTER  # noqa: S608 (constant fragments)


@dataclass(frozen=True)
class _Cited:
    parser_version: str | None
    parse_status: str
    parsed_object_uri: str | None
    page_anchors: list[dict[str, Any]] | None


@dataclass(frozen=True)
class _CitedText:
    """A cited parse's text, its parser version and, for a PDF, its page anchors."""

    text: str
    parser_version: str
    page_anchors: list[dict[str, Any]] | None


class Assertions:
    """The write side: create and review, each audited in its own transaction."""

    def __init__(self, engine: Engine, archive: Archive, actor: Actor) -> None:
        self._engine = engine
        self._archive = archive
        self._actor = actor

    def create(
        self, request: AssertionCreate, *, extractor_version: str = EXTRACTOR_VERSION
    ) -> AssertionRecorded:
        with self._engine.connect() as connection:
            parsed = self._parsed_text(connection, request)
        # A parse, once recorded, never changes (migration 0004), so the text read here is
        # the text the new row cites.
        check_quote(parsed.text, request)
        with self._engine.begin() as connection:
            return self._insert(connection, request, parsed, extractor_version)

    def create_within(
        self, connection: Connection, request: AssertionCreate, *, extractor_version: str
    ) -> AssertionRecorded:
        """`create` inside the caller's transaction (the same checks, row and audit event)."""
        parsed = self._parsed_text(connection, request)
        check_quote(parsed.text, request)
        return self._insert(connection, request, parsed, extractor_version)

    def _parsed_text(self, connection: Connection, request: AssertionCreate) -> _CitedText:
        cited = self._check_references(connection, request)
        assert cited.parsed_object_uri is not None and cited.parser_version is not None
        text_ = self._archive.get(cited.parsed_object_uri).decode("utf-8")
        return _CitedText(
            text=text_, parser_version=cited.parser_version, page_anchors=cited.page_anchors
        )

    def _insert(
        self,
        connection: Connection,
        request: AssertionCreate,
        cited: _CitedText,
        extractor_version: str,
    ) -> AssertionRecorded:
        anchor = request.page_or_anchor
        if anchor is None and cited.page_anchors:
            anchor = _pages_label(cited.page_anchors, request.span_start, request.span_end)
        row = connection.execute(
            text(
                "INSERT INTO assertion (id, subject_company_id, predicate,"
                " object_company_id, value_json, source_version_id, quote, span_start,"
                " span_end, page_or_anchor, event_start, event_end, epistemic_type,"
                " extractor_version, created_by, parser_version)"
                " VALUES (:id, :subject, :predicate, :object, CAST(:value AS jsonb),"
                " :version, :quote, :start, :end, :anchor, :event_start, :event_end,"
                " :epistemic_type, :extractor, :actor, :parser) RETURNING id"
            ),
            {
                "id": uuid.uuid4(),
                "subject": request.subject_company_id,
                "predicate": request.predicate,
                "object": request.object_company_id,
                "value": None if request.value_json is None else json.dumps(request.value_json),
                "version": request.source_version_id,
                "quote": request.quote,
                "start": request.span_start,
                "end": request.span_end,
                "anchor": anchor,
                "event_start": request.event_start,
                "event_end": request.event_end,
                "epistemic_type": request.epistemic_type,
                "extractor": extractor_version,
                "actor": self._actor.name,
                "parser": cited.parser_version,
            },
        ).one()
        assertion = _get(connection, row.id)
        assert assertion is not None
        event = record(
            connection,
            self._actor,
            "assertion.created",
            entity_type="assertion",
            entity_id=str(assertion.id),
            new_hash=_hash(assertion),
        )
        return AssertionRecorded(assertion=assertion, audit_event_id=event.id)

    def review(self, assertion_id: uuid.UUID, request: AssertionReview) -> AssertionRecorded:
        state, successor_id = request.review_state, request.superseded_by
        if (state == "superseded") != (successor_id is not None):
            raise InvalidAssertion(
                "invalid_successor",
                "superseded_by names the successor when (and only when) review_state is superseded",
            )
        if successor_id == assertion_id:
            raise InvalidAssertion("invalid_successor", "an assertion cannot supersede itself")
        with self._engine.begin() as connection:
            # Lock the Assertion and its successor (in a fixed order, so two opposite
            # supersessions cannot deadlock) until the review commits.
            ids = sorted({assertion_id, *([successor_id] if successor_id else [])})
            locked = {
                row.id: row.verification_status
                for row in connection.execute(
                    text(
                        "SELECT id, verification_status FROM assertion"
                        " WHERE id = ANY(:ids) ORDER BY id FOR UPDATE"
                    ),
                    {"ids": ids},
                )
            }
            if assertion_id not in locked:
                raise AssertionNotFound
            current: ReviewState = locked[assertion_id]
            if state not in allowed_transitions(current):
                raise InvalidTransition("invalid_transition", _transition_refusal(current, state))
            if successor_id is not None:
                if successor_id not in locked:
                    raise InvalidAssertion(
                        "invalid_successor", f"successor assertion {successor_id} not found"
                    )
                if locked[successor_id] in ("rejected", "superseded"):
                    raise InvalidAssertion(
                        "invalid_successor",
                        f"successor assertion {successor_id} is {locked[successor_id]};"
                        " only an assertion that is not rejected or superseded can succeed"
                        " another",
                    )
            before = _get(connection, assertion_id)
            assert before is not None
            connection.execute(
                text(
                    "UPDATE assertion SET verification_status = :state, reviewer_id = :actor,"
                    " reviewed_at = now(), superseded_by = :successor WHERE id = :id"
                ),
                {
                    "state": state,
                    "actor": self._actor.name,
                    "successor": successor_id,
                    "id": assertion_id,
                },
            )
            after = _get(connection, assertion_id)
            assert after is not None
            event = record(
                connection,
                self._actor,
                "assertion.reviewed",
                entity_type="assertion",
                entity_id=str(assertion_id),
                old_hash=_hash(before),
                new_hash=_hash(after),
            )
            # A published Hypothesis version citing it gets a proposed update (ticket 21).
            on_assertion_reviewed(connection, assertion_id, state)
        return AssertionRecorded(assertion=after, audit_event_id=event.id)

    def _check_references(self, connection: Connection, request: AssertionCreate) -> _Cited:
        for company_id in (request.subject_company_id, request.object_company_id):
            if (
                company_id is not None
                and not connection.execute(
                    text("SELECT EXISTS (SELECT FROM company WHERE id = :id)"), {"id": company_id}
                ).scalar_one()
            ):
                raise InvalidAssertion("unknown_company", f"company {company_id} not found")
        row = connection.execute(
            text(
                "SELECT parser_version, parse_status, parsed_object_uri, page_anchors"
                " FROM source_version WHERE id = :id"
            ),
            {"id": request.source_version_id},
        ).one_or_none()
        if row is None:
            raise InvalidAssertion(
                "unknown_source_version", f"source version {request.source_version_id} not found"
            )
        if request.parser_version is not None and request.parser_version != row.parser_version:
            # One of the version's re-parses (pilot-fixes ticket 11).
            row = connection.execute(
                text(
                    "SELECT parser_version, parse_status, parsed_object_uri, page_anchors"
                    " FROM source_parse WHERE source_version_id = :id AND parser_version = :parser"
                ),
                {"id": request.source_version_id, "parser": request.parser_version},
            ).one_or_none()
            if row is None:
                raise InvalidAssertion(
                    "no_parsed_text",
                    f"source version {request.source_version_id} has no parse under"
                    f" {request.parser_version}",
                )
        cited = _Cited(
            row.parser_version, row.parse_status, row.parsed_object_uri, row.page_anchors
        )
        if cited.parse_status not in _PARSED or cited.parsed_object_uri is None:
            raise InvalidAssertion(
                "no_parsed_text",
                f"source version {request.source_version_id} has no parsed text"
                f" (parse status {cited.parse_status}); only parsed text can be quoted",
            )
        return cited


def check_quote(parsed: str, request: AssertionCreate) -> None:
    """The span check: raises `InvalidAssertion` (`quote_mismatch`) unless the quote is exactly
    `parsed[span_start:span_end]`. The message says where the quote does occur, if anywhere."""
    start, end, quote = request.span_start, request.span_end, request.quote
    if end - start == len(quote) and parsed[start:end] == quote:
        return
    message = (
        f"the quote does not occur exactly at characters [{start}, {end}) of the parsed text"
        f" of source version {request.source_version_id} ({len(parsed)} characters)"
    )
    found = parsed.find(quote)
    if found >= 0:
        count = parsed.count(quote)
        where = f"[{found}, {found + len(quote)})"
        message += (
            f"; it occurs at {where}"
            if count == 1
            else f"; it first occurs at {where} (one of {count} occurrences)"
        )
    raise InvalidAssertion("quote_mismatch", message)


def _pages_label(anchors: list[dict[str, Any]], start: int, end: int) -> str:
    """The page(s) `[start, end)` lies on, by label, with the PDF page numbers when a
    label differs from its number."""
    pages = [a for a in anchors if a["start"] < end and start < a["end"]]
    first, last = pages[0], pages[-1]
    numbered = all(a["label"] == str(a["page"]) for a in (first, last))
    if first is last:
        label = f"page {first['label']}"
        return label if numbered else f"{label} (PDF page {first['page']})"
    label = f"pages {first['label']}\u2013{last['label']}"
    return label if numbered else f"{label} (PDF pages {first['page']}\u2013{last['page']})"


def _transition_refusal(current: ReviewState, state: ReviewState) -> str:
    allowed = sorted(allowed_transitions(current))
    reason = (
        f"a {current} assertion takes no further review"
        if not allowed
        else f"a {current} assertion can become {', '.join(allowed)}"
    )
    return f"review {current} -> {state} is not allowed: {reason}"


def _hash(assertion: Assertion) -> str:
    return content_hash(assertion.model_dump(mode="json"))


def _get(connection: Connection, assertion_id: uuid.UUID) -> Assertion | None:
    row = (
        connection.execute(text(f"{_SELECT} WHERE id = :id"), {"id": assertion_id})
        .mappings()
        .one_or_none()
    )
    return None if row is None else Assertion.model_validate(dict(row))


def get_assertion(connection: Connection, assertion_id: uuid.UUID) -> Assertion | None:
    return _get(connection, assertion_id)


def list_assertions(
    connection: Connection,
    *,
    company_id: uuid.UUID | None = None,
    review_state: ReviewState | None = None,
    source_version_id: uuid.UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Assertion], int]:
    """Assertions oldest first. A company's are those naming it as subject or object."""
    params: dict[str, Any] = {
        "company": company_id,
        "state": review_state,
        "version": source_version_id,
        "limit": limit,
        "offset": offset,
    }
    total = connection.execute(text(_COUNT), params)
    rows = connection.execute(
        text(f"{_SELECT} {_FILTER} ORDER BY extracted_at, id LIMIT :limit OFFSET :offset"), params
    ).mappings()
    return [Assertion.model_validate(dict(row)) for row in rows], total.scalar_one()
