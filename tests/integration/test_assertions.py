"""Assertions: record a statement bound to an exact quote span, then review and supersede it.

Seam: the `/api/v1` API, on a fresh database holding Lumentum's recorded EDGAR filings,
ingested through the fixture path (the `ingest` job, one worker pass). Quotes and their
offsets come from the recorded Q4 FY26 press release (EX-99.1) as parsed by
`html-text-v1`, whose output is pinned by `tests/fixtures/parser/golden.json`.
"""

import json
import os
import subprocess
import sys
import uuid
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from atlas.api.app import create_app
from atlas.audit import Actor
from atlas.db.migrate import upgrade
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from atlas.settings import Settings

REPO = Path(__file__).parents[2]
THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"
EDGAR_FIXTURES = REPO / "tests" / "fixtures" / "edgar"
GOLDEN_PARSES = json.loads((REPO / "tests" / "fixtures" / "parser" / "golden.json").read_text())

ARCHIVES = "https://www.sec.gov/Archives/edgar/data/1633978"
URL_EX991 = f"{ARCHIVES}/000162828026055726/lite_ex991xq4fy26.htm"
URL_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json"
ACTOR = "assertion-test-reviewer"

# From the parsed EX-99.1 (content hash pinned in golden.json). Offsets are characters
# (Unicode code points) into the parsed text. Curly quotes and a dash come before the
# revenue sentence, so its UTF-8 byte offset differs from its character offset.
REVENUE_QUOTE = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
REVENUE_SPAN = (1604, 1676)
REVENUE_BYTE_OFFSET = 1630
MARGIN_QUOTE = "GAAP gross margin of 47.4%"
MARGIN_SPAN = (186, 212)
NAME_QUOTE = "Lumentum Holdings Inc. (“Lumentum” or the “Company”)"
NAME_SPAN = (546, 598)


class Atlas:
    def __init__(self, database_url: str, tmp_path: Path) -> None:
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.archive = tmp_path / "archive"
        self.archive.mkdir(exist_ok=True)
        self.engine = create_engine(database_url)
        self.settings = Settings.model_validate(
            {
                "database_url": database_url,
                "actor": ACTOR,
                "archive_root": self.archive,
                "themes_config": THEMES,
                "sec_fixtures_dir": EDGAR_FIXTURES,
            }
        )
        self.api = TestClient(create_app(self.settings))

    def ingest_lumentum(self) -> None:
        queue = JobQueue(self.engine, actor=Actor(ACTOR))  # as `atlas ingest` would
        queue.enqueue(INGEST_KIND, "lumentum", ingest_payload("lumentum", ["8-K"], None))
        assert Worker(queue, builtin_registry(self.settings)).run_once() == 1

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp_path),
            "ATLAS_DATABASE_URL": self.database_url,
            "ATLAS_ACTOR": ACTOR,
            "ATLAS_ARCHIVE_ROOT": str(self.archive),
            "ATLAS_THEMES_CONFIG": str(THEMES),
        }
        return subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=self.tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def company_id(self, slug: str = "lumentum") -> str:
        companies = self.get("/api/v1/companies")["items"]
        return next(company["id"] for company in companies if company["slug"] == slug)

    def version_id(self, url: str) -> str:
        documents = self.get(f"/api/v1/companies/{self.company_id()}/sources", limit=100)
        document = next(d for d in documents["items"] if d["canonical_url"] == url)
        return document["latest_version_id"]

    def assertion_body(self, **overrides: Any) -> dict[str, Any]:
        start, end = REVENUE_SPAN
        body: dict[str, Any] = {
            "subject_company_id": self.company_id(),
            "predicate": "reported_net_revenue",
            "value_json": {"amount": 1.01e9, "currency": "USD", "period": "Q4 FY2026"},
            "source_version_id": self.version_id(URL_EX991),
            "quote": REVENUE_QUOTE,
            "span_start": start,
            "span_end": end,
            "page_or_anchor": "Fiscal Fourth Quarter",
            "epistemic_type": "company_claim",
        }
        return body | overrides

    def create(self, **overrides: Any) -> dict[str, Any]:
        response = self.api.post("/api/v1/assertions", json=self.assertion_body(**overrides))
        assert response.status_code == 201, response.text
        return response.json()["assertion"]

    def review(self, assertion_id: str, **body: Any) -> Any:
        return self.api.post(f"/api/v1/assertions/{assertion_id}/review", json=body)

    def reviewed(self, assertion_id: str, **body: Any) -> dict[str, Any]:
        response = self.review(assertion_id, **body)
        assert response.status_code == 200, response.text
        return response.json()["assertion"]

    def assertions(self, **params: Any) -> dict[str, Any]:
        return self.get("/api/v1/assertions", **params)

    def audit_events(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT id, actor, action, entity_type, entity_id, old_hash, new_hash"
                    " FROM audit_event ORDER BY id"
                )
            )
            return [dict(row._mapping) for row in rows]  # pyright: ignore[reportPrivateUsage]

    def assertion_events(self) -> list[dict[str, Any]]:
        return [e for e in self.audit_events() if e["entity_type"] == "assertion"]


@pytest.fixture
def atlas(empty_database_url: str, tmp_path: Path) -> Iterator[Atlas]:
    upgrade(empty_database_url)
    harness = Atlas(empty_database_url, tmp_path)
    harness.ingest_lumentum()
    yield harness
    harness.engine.dispose()


STATEMENT_FIELDS = (
    "subject_company_id",
    "predicate",
    "object_company_id",
    "value_json",
    "source_version_id",
    "quote",
    "span_start",
    "span_end",
    "page_or_anchor",
    "event_start",
    "event_end",
    "epistemic_type",
    "extracted_at",
    "extractor_version",
    "created_by",
)


def statement(assertion: dict[str, Any]) -> dict[str, Any]:
    return {field: assertion[field] for field in STATEMENT_FIELDS}


def assert_error(response: Any, status: int, code: str) -> str:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    return body["error"]["message"]


# --- creation binds an exact quote span ---


def test_the_fixture_parse_is_the_pinned_golden_text(atlas: Atlas) -> None:
    version = atlas.get(f"/api/v1/source-versions/{atlas.version_id(URL_EX991)}")
    assert version["content_sha256"] == GOLDEN_PARSES["html-text-v1"]["lite_ex991xq4fy26.htm"]


def test_an_assertion_whose_quote_occurs_exactly_at_its_offsets_is_recorded_unreviewed(
    atlas: Atlas,
) -> None:
    body = atlas.assertion_body()

    response = atlas.api.post("/api/v1/assertions", json=body)

    assert response.status_code == 201, response.text
    created = response.json()
    assertion = created["assertion"]
    assert isinstance(created["audit_event_id"], int)
    assert {key: assertion[key] for key in body} == body
    assert assertion["review_state"] == "unreviewed"
    assert assertion["reviewer_id"] is None
    assert assertion["reviewed_at"] is None
    assert assertion["superseded_by"] is None
    assert assertion["object_company_id"] is None
    assert assertion["independence_family_id"] is None
    assert assertion["extractor_version"] == "manual"
    assert assertion["created_by"] == ACTOR
    assert atlas.get(f"/api/v1/assertions/{assertion['id']}") == assertion


@pytest.mark.parametrize(
    ("quote", "span"),
    [
        (NAME_QUOTE, NAME_SPAN),  # non-ASCII punctuation inside the quote
        (MARGIN_QUOTE, MARGIN_SPAN),
    ],
)
def test_offsets_are_characters_of_the_parsed_text(
    atlas: Atlas, quote: str, span: tuple[int, int]
) -> None:
    assertion = atlas.create(quote=quote, span_start=span[0], span_end=span[1])

    assert (assertion["quote"], assertion["span_start"], assertion["span_end"]) == (quote, *span)


@pytest.mark.parametrize(
    ("quote", "span"),
    [
        pytest.param(REVENUE_QUOTE.replace("1.01", "1.02"), REVENUE_SPAN, id="altered-quote"),
        pytest.param(
            REVENUE_QUOTE, (REVENUE_SPAN[0] + 1, REVENUE_SPAN[1] + 1), id="shifted-offsets"
        ),
        pytest.param(
            REVENUE_QUOTE,
            (REVENUE_BYTE_OFFSET, REVENUE_BYTE_OFFSET + len(REVENUE_QUOTE)),
            id="utf8-byte-offsets",
        ),
        pytest.param(REVENUE_QUOTE, (REVENUE_SPAN[0], REVENUE_SPAN[1] - 1), id="short-span"),
        pytest.param(REVENUE_QUOTE[:-8], REVENUE_SPAN, id="span-longer-than-quote"),
        pytest.param(
            REVENUE_QUOTE.replace(" was ", "  was "),
            (REVENUE_SPAN[0], REVENUE_SPAN[1] + 1),
            id="whitespace-differs",
        ),
        pytest.param(REVENUE_QUOTE.lower(), REVENUE_SPAN, id="case-differs"),
        pytest.param(REVENUE_QUOTE, (400_000, 400_000 + len(REVENUE_QUOTE)), id="past-the-end"),
        pytest.param("Lumentum will double revenue", (0, 28), id="not-in-the-source"),
    ],
)
def test_an_assertion_whose_quote_is_not_at_its_offsets_in_the_parse_is_rejected(
    atlas: Atlas, quote: str, span: tuple[int, int]
) -> None:
    events_before = atlas.audit_events()

    response = atlas.api.post(
        "/api/v1/assertions",
        json=atlas.assertion_body(quote=quote, span_start=span[0], span_end=span[1]),
    )

    message = assert_error(response, 422, "quote_mismatch")
    assert atlas.version_id(URL_EX991) in message
    assert atlas.assertions()["total"] == 0
    assert atlas.audit_events() == events_before


def test_a_rejected_quote_found_elsewhere_in_the_parse_says_where(atlas: Atlas) -> None:
    start, end = REVENUE_SPAN
    response = atlas.api.post(
        "/api/v1/assertions", json=atlas.assertion_body(span_start=start + 7, span_end=end + 7)
    )

    message = assert_error(response, 422, "quote_mismatch")
    assert f"[{start}, {end})" in message


def test_a_source_version_without_parsed_text_cannot_be_quoted(atlas: Atlas) -> None:
    response = atlas.api.post(
        "/api/v1/assertions",
        json=atlas.assertion_body(source_version_id=atlas.version_id(URL_FACTS)),
    )

    assert_error(response, 422, "no_parsed_text")
    assert atlas.assertions()["total"] == 0


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"source_version_id": str(uuid.uuid4())}, "unknown_source_version"),
        ({"subject_company_id": str(uuid.uuid4())}, "unknown_company"),
        ({"object_company_id": str(uuid.uuid4())}, "unknown_company"),
    ],
)
def test_an_assertion_must_reference_existing_records(
    atlas: Atlas, overrides: dict[str, Any], code: str
) -> None:
    response = atlas.api.post("/api/v1/assertions", json=atlas.assertion_body(**overrides))

    assert_error(response, 422, code)
    assert atlas.assertions()["total"] == 0


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"epistemic_type": None}, id="no-epistemic-type"),
        pytest.param({"epistemic_type": "strong_hunch"}, id="unknown-epistemic-type"),
        pytest.param({"predicate": "  "}, id="blank-predicate"),
        pytest.param({"quote": "", "span_start": 0, "span_end": 0}, id="empty-quote"),
        pytest.param({"span_start": -1}, id="negative-offset"),
        pytest.param({"review_state": "corroborated"}, id="born-reviewed"),
        pytest.param({"created_by": "someone-else"}, id="chosen-actor"),
        pytest.param(
            {"event_start": "2026-06-27T00:00:00Z", "event_end": "2026-03-28T00:00:00Z"},
            id="event-ends-before-it-starts",
        ),
    ],
)
def test_a_malformed_assertion_is_rejected_in_the_error_envelope(
    atlas: Atlas, change: dict[str, Any]
) -> None:
    body = atlas.assertion_body() | change
    body = {key: value for key, value in body.items() if value is not None}

    response = atlas.api.post("/api/v1/assertions", json=body)

    assert_error(response, 422, "invalid_request")
    assert atlas.assertions()["total"] == 0


# --- review ---


def test_review_moves_through_the_allowed_states_without_touching_the_statement(
    atlas: Atlas,
) -> None:
    created = atlas.create()
    states: list[str] = []

    for state in ("disputed", "corroborated", "disputed", "rejected"):
        reviewed = atlas.reviewed(created["id"], review_state=state)
        states.append(reviewed["review_state"])
        assert reviewed["reviewer_id"] == ACTOR
        assert reviewed["reviewed_at"] is not None
        assert statement(reviewed) == statement(created)

    assert states == ["disputed", "corroborated", "disputed", "rejected"]
    assert atlas.get(f"/api/v1/assertions/{created['id']}")["review_state"] == "rejected"


@pytest.mark.parametrize(
    ("path", "attempt"),
    [
        pytest.param([], "unreviewed", id="unreviewed-to-unreviewed"),
        pytest.param(["corroborated"], "unreviewed", id="back-to-unreviewed"),
        pytest.param(["corroborated"], "corroborated", id="same-state-again"),
        pytest.param(["disputed"], "disputed", id="disputed-again"),
        pytest.param(["rejected"], "corroborated", id="rejected-is-final"),
        pytest.param(["rejected"], "disputed", id="rejected-cannot-be-disputed"),
    ],
)
def test_a_disallowed_transition_is_refused_and_changes_nothing(
    atlas: Atlas, path: list[str], attempt: str
) -> None:
    created = atlas.create()
    for state in path:
        atlas.reviewed(created["id"], review_state=state)
    before = atlas.get(f"/api/v1/assertions/{created['id']}")
    events_before = atlas.audit_events()

    response = atlas.review(created["id"], review_state=attempt)

    assert_error(response, 409, "invalid_transition")
    assert atlas.get(f"/api/v1/assertions/{created['id']}") == before
    assert atlas.audit_events() == events_before


def test_reviewing_an_unknown_assertion_is_not_found(atlas: Atlas) -> None:
    response = atlas.review(str(uuid.uuid4()), review_state="corroborated")

    assert_error(response, 404, "not_found")
    assert_error(atlas.api.get(f"/api/v1/assertions/{uuid.uuid4()}"), 404, "not_found")


def test_an_unknown_review_state_is_rejected(atlas: Atlas) -> None:
    created = atlas.create()

    assert_error(atlas.review(created["id"], review_state="approved"), 422, "invalid_request")


# --- supersession ---


def test_supersession_links_to_the_successor_and_never_edits_the_superseded(
    atlas: Atlas,
) -> None:
    original = atlas.create(predicate="net_revenue", epistemic_type="direct_source_statement")
    atlas.reviewed(original["id"], review_state="corroborated")
    successor = atlas.create()

    superseded = atlas.reviewed(
        original["id"], review_state="superseded", superseded_by=successor["id"]
    )

    assert superseded["review_state"] == "superseded"
    assert superseded["superseded_by"] == successor["id"]
    assert superseded["reviewer_id"] == ACTOR
    assert statement(superseded) == statement(original)
    assert superseded["predicate"] == "net_revenue"
    assert atlas.get(f"/api/v1/assertions/{successor['id']}") == successor
    # A superseded Assertion is history: it takes no further review.
    assert_error(
        atlas.review(original["id"], review_state="corroborated"), 409, "invalid_transition"
    )
    assert_error(
        atlas.review(original["id"], review_state="superseded", superseded_by=successor["id"]),
        409,
        "invalid_transition",
    )


@pytest.mark.parametrize(
    "successor",
    [
        pytest.param("missing", id="superseded-without-a-successor"),
        pytest.param("self", id="superseded-by-itself"),
        pytest.param("unknown", id="superseded-by-an-unknown-assertion"),
        pytest.param("rejected", id="superseded-by-a-rejected-assertion"),
        pytest.param("superseded", id="superseded-by-a-superseded-assertion"),
    ],
)
def test_supersession_needs_a_live_successor(atlas: Atlas, successor: str) -> None:
    original = atlas.create()
    body: dict[str, Any] = {"review_state": "superseded"}
    if successor == "self":
        body["superseded_by"] = original["id"]
    elif successor == "unknown":
        body["superseded_by"] = str(uuid.uuid4())
    elif successor == "rejected":
        rejected = atlas.create()
        atlas.reviewed(rejected["id"], review_state="rejected")
        body["superseded_by"] = rejected["id"]
    elif successor == "superseded":
        older, newer = atlas.create(), atlas.create()
        atlas.reviewed(older["id"], review_state="superseded", superseded_by=newer["id"])
        body["superseded_by"] = older["id"]
    events_before = atlas.audit_events()

    response = atlas.review(original["id"], **body)

    assert_error(response, 422, "invalid_successor")
    assert atlas.get(f"/api/v1/assertions/{original['id']}") == original
    assert atlas.audit_events() == events_before


def test_a_successor_is_named_only_when_superseding(atlas: Atlas) -> None:
    original, other = atlas.create(), atlas.create()

    response = atlas.review(original["id"], review_state="disputed", superseded_by=other["id"])

    assert_error(response, 422, "invalid_successor")
    assert atlas.get(f"/api/v1/assertions/{original['id']}") == original


def test_the_database_refuses_edits_deletes_and_reviewed_inserts(atlas: Atlas) -> None:
    created = atlas.create()
    review = (
        "UPDATE assertion SET verification_status = 'corroborated', reviewer_id = 'x',"
        " reviewed_at = now() WHERE id = :id"
    )
    # Each list is one transaction whose last statement the database must refuse.
    transactions: list[list[str]] = [
        ["UPDATE assertion SET quote = 'Net revenue' WHERE id = :id"],
        ["UPDATE assertion SET span_start = span_start + 1 WHERE id = :id"],
        ["UPDATE assertion SET predicate = 'guided_revenue' WHERE id = :id"],
        ["UPDATE assertion SET created_by = 'someone-else' WHERE id = :id"],
        ["DELETE FROM assertion WHERE id = :id"],
        ["TRUNCATE assertion"],
        [
            review,
            "UPDATE assertion SET verification_status = 'unreviewed', reviewer_id = NULL,"
            " reviewed_at = NULL WHERE id = :id",
        ],
        [review, review],  # the same state again
        [
            "UPDATE assertion SET verification_status = 'rejected', reviewer_id = 'x',"
            " reviewed_at = now() WHERE id = :id",
            review,
        ],
        [review.replace("reviewed_at = now()", "reviewed_at = now(), superseded_by = id")],
        [
            "INSERT INTO assertion (id, subject_company_id, predicate, source_version_id,"
            " quote, span_start, span_end, epistemic_type, verification_status,"
            " extractor_version, created_by, reviewer_id, reviewed_at)"
            " SELECT gen_random_uuid(), subject_company_id, predicate, source_version_id,"
            " quote, span_start, span_end, epistemic_type, 'corroborated', 'manual', 'x', 'x',"
            " now() FROM assertion WHERE id = :id"
        ],
    ]
    for transaction in transactions:
        with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
            for sql in transaction:
                connection.execute(text(sql), {"id": created["id"]})

    assert atlas.get(f"/api/v1/assertions/{created['id']}") == created
    assert atlas.assertions()["total"] == 1


# --- listing ---


def test_assertions_are_listed_by_company_and_review_state(atlas: Atlas) -> None:
    assert atlas.cli("companies", "seed").returncode == 0
    lumentum, coherent = atlas.company_id("lumentum"), atlas.company_id("coherent")
    about_lumentum = atlas.create()
    margin = atlas.create(quote=MARGIN_QUOTE, span_start=MARGIN_SPAN[0], span_end=MARGIN_SPAN[1])
    naming_coherent = atlas.create(predicate="competes_with", object_company_id=coherent)
    about_coherent = atlas.create(subject_company_id=coherent, predicate="competes_with")
    atlas.reviewed(margin["id"], review_state="corroborated")
    atlas.reviewed(about_coherent["id"], review_state="disputed")

    def ids(**params: Any) -> list[str]:
        page = atlas.assertions(**params)
        assert page["total"] == len(page["items"])
        return [item["id"] for item in page["items"]]

    everything = [about_lumentum["id"], margin["id"], naming_coherent["id"], about_coherent["id"]]
    assert ids() == everything  # oldest first
    assert ids(company_id=lumentum) == everything[:3]
    # A company's Assertions are those naming it as subject or object.
    assert ids(company_id=coherent) == [naming_coherent["id"], about_coherent["id"]]
    assert ids(review_state="unreviewed") == [about_lumentum["id"], naming_coherent["id"]]
    assert ids(review_state="corroborated") == [margin["id"]]
    assert ids(company_id=lumentum, review_state="unreviewed") == [
        about_lumentum["id"],
        naming_coherent["id"],
    ]
    assert ids(company_id=coherent, review_state="disputed") == [about_coherent["id"]]
    assert ids(company_id=coherent, review_state="corroborated") == []
    assert ids(review_state="superseded") == []
    assert ids(source_version_id=atlas.version_id(URL_EX991)) == everything
    assert ids(source_version_id=str(uuid.uuid4())) == []

    page = atlas.assertions(company_id=lumentum, limit=2, offset=1)
    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 1)
    assert [item["id"] for item in page["items"]] == everything[1:3]
    listed = next(item for item in atlas.assertions()["items"] if item["id"] == margin["id"])
    assert listed == atlas.get(f"/api/v1/assertions/{margin['id']}")


def test_listing_rejects_an_unknown_review_state(atlas: Atlas) -> None:
    response = atlas.api.get("/api/v1/assertions", params={"review_state": "approved"})

    assert_error(response, 422, "invalid_request")


# --- audit ---


def test_every_create_and_review_is_audited_in_a_chain_that_verifies(atlas: Atlas) -> None:
    ingest_events = len(atlas.audit_events())
    original_response = atlas.api.post("/api/v1/assertions", json=atlas.assertion_body())
    original = original_response.json()["assertion"]
    successor = atlas.create()
    corroborated = atlas.review(original["id"], review_state="corroborated").json()
    superseded = atlas.review(
        original["id"], review_state="superseded", superseded_by=successor["id"]
    ).json()
    atlas.api.post("/api/v1/assertions", json=atlas.assertion_body(quote="not in the source"))
    atlas.review(original["id"], review_state="disputed")  # refused: superseded is final

    events = atlas.assertion_events()

    assert len(atlas.audit_events()) == ingest_events + len(events)
    assert [(e["action"], e["entity_id"]) for e in events] == [
        ("assertion.created", original["id"]),
        ("assertion.created", successor["id"]),
        ("assertion.reviewed", original["id"]),
        ("assertion.reviewed", original["id"]),
    ]
    assert {e["actor"] for e in events} == {ACTOR}
    assert [e["id"] for e in events] == [
        original_response.json()["audit_event_id"],
        events[1]["id"],
        corroborated["audit_event_id"],
        superseded["audit_event_id"],
    ]
    created, _, first_review, second_review = events
    assert created["old_hash"] is None
    assert first_review["old_hash"] == created["new_hash"]
    assert second_review["old_hash"] == first_review["new_hash"]
    assert len({created["new_hash"], first_review["new_hash"], second_review["new_hash"]}) == 3
    assert Counter(e["actor"] for e in atlas.audit_events()) == {ACTOR: len(atlas.audit_events())}

    verify = atlas.cli("audit", "verify")
    assert verify.returncode == 0, verify.stderr
    assert f"{len(atlas.audit_events())} events" in verify.stdout
