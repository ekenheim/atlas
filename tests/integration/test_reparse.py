"""Re-parsing recorded Source Versions with the current parser (pilot-fixes ticket 11).

Seam: the `atlas` CLI (`sources import`, `companies seed`, `ledger reparse`, `jobs enqueue
extract_claims`), single worker passes, and `/api/v1`, on a fresh database. The document is
shaped like Coherent's FY2026 10-K around two page breaks (the markup of the recorded filing,
styles shortened), with a sentence split by the first one. The version "recorded before
`text-v3`" is inserted directly, as the ledger recorded it then: the same raw bytes, with its
`text-v2` parse (written here by hand from v2's rules: page numbers and back-links in the
text) in the archive. LiteLLM is the scripted chat fake: the Investigator's answer is written
here, quoting the passages it is sent.
"""

import hashlib
import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.archive import Namespace, open_archive
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.harness import Atlas

ORIGIN = "https://filings.example.test/coherent/fy2026-10-k.htm"
ORIGIN_BEFORE = "https://filings.example.test/coherent/fy2026-10-k-recorded-earlier.htm"
PAGE_BREAK = '<hr style="page-break-after:always"/>'
BACK_LINK = (
    '<div style="min-height:42.75pt;width:100%"><div><span>'
    '<a href="#i994ba7cf1bc444699c20cbef454a6f29_7">Table of Contents</a></span></div></div>'
)
FIRST_HALF = "In fiscal 2026 we continued to supply transceivers and many of their critical parts"
SECOND_HALF = "to Lumentum Holdings Inc. under a multi-year agreement."
CAPACITY = "We continue to expand our global InP capacity."


def footer(page_number: int) -> str:
    return (
        '<div style="height:42.75pt;position:relative;width:100%">'
        '<div style="bottom:0;position:absolute;width:100%">'
        f'<div style="text-align:center"><span>{page_number}</span></div></div></div>'
    )


def paragraph(line: str) -> str:
    return f'<div style="margin-top:6pt;text-align:justify"><span>{line}</span></div>'


def filing() -> bytes:
    body = (
        paragraph("Customers")
        + paragraph(f"{FIRST_HALF} ")
        + footer(9)
        + PAGE_BREAK
        + BACK_LINK
        + paragraph(SECOND_HALF)
        + paragraph(CAPACITY)
        + footer(10)
        + PAGE_BREAK
        + BACK_LINK
        + paragraph("Item 1A. RISK FACTORS")
    )
    return f"<html><body>{body}</body></html>".encode()


PARSE_V2 = (
    f"Customers\n{FIRST_HALF}\n9\nTable of Contents\n{SECOND_HALF}\n{CAPACITY}\n"
    "10\nTable of Contents\nItem 1A. RISK FACTORS\n"
)
PARSE_V3 = f"Customers\n{FIRST_HALF} {SECOND_HALF}\n{CAPACITY}\nItem 1A. RISK FACTORS\n"
V2_SHA = hashlib.sha256(PARSE_V2.encode()).hexdigest()
V3_SHA = hashlib.sha256(PARSE_V3.encode()).hexdigest()
# A true quote across the page break: a span of the v3 parse only.
SUPPLY_QUOTE = (
    "we continued to supply transceivers and many of their critical parts to Lumentum Holdings Inc."
)


# --- fixtures -----------------------------------------------------------------------------------


@pytest.fixture
def llm() -> FakeLiteLLM:
    return FakeLiteLLM()


@pytest.fixture
def litellm(llm: FakeLiteLLM) -> Iterator[Served]:
    with serve(llm.handle) as served:
        yield served
        served.raise_errors()


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, hindsight[1].url, litellm.url)
    harness.apply_template()
    seeded = harness.cli("companies", "seed")
    assert seeded.returncode == 0, seeded.stderr
    yield harness
    harness.engine.dispose()


# --- helpers ------------------------------------------------------------------------------------


def import_filing(atlas: Atlas, origin: str) -> dict[str, Any]:
    file = atlas.tmp_path / "fy2026-10-k.htm"
    file.write_bytes(filing())
    result = atlas.cli(
        "sources",
        "import",
        "--company",
        "coherent",
        "--file",
        str(file),
        "--origin-url",
        origin,
        "--published-at",
        "2026-08-18T16:30-04:00",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def record_under_text_v2(atlas: Atlas) -> str:
    """The document as the ledger recorded it under `text-v2`, at `ORIGIN_BEFORE`: the raw
    bytes a `text-v3` import archived, the v2 parse archived, the parse columns saying so."""
    recorded = import_filing(atlas, ORIGIN)
    parsed_uri = open_archive(atlas.settings()).put(Namespace.PARSED, PARSE_V2.encode())
    with atlas.engine.begin() as connection:
        document_id = connection.execute(
            text(
                "INSERT INTO source_document (id, company_id, provider, canonical_url,"
                " origin_url, accession, form_type, document_type, source_type, title,"
                " publisher, source_tier, license_class, first_seen_at)"
                " SELECT gen_random_uuid(), company_id, provider, :url, :url, accession,"
                " form_type, document_type, source_type, title, publisher, source_tier,"
                " license_class, first_seen_at"
                " FROM source_document WHERE id = :document RETURNING id"
            ),
            {"document": recorded["source_document_id"], "url": ORIGIN_BEFORE},
        ).scalar_one()
        return str(
            connection.execute(
                text(
                    "INSERT INTO source_version (id, source_document_id, version_number,"
                    " raw_sha256, comparison_sha256, comparison_rule, object_uri, byte_size,"
                    " media_type, content_sha256, parsed_object_uri, parser_version,"
                    " parse_status, language, available_at, available_at_basis, fetched_at,"
                    " fetch_status, metadata)"
                    " SELECT gen_random_uuid(), :document, 1, raw_sha256, comparison_sha256,"
                    " comparison_rule, object_uri, byte_size, media_type, :content_sha256,"
                    " :parsed_object_uri, 'text-v2', parse_status, language, available_at,"
                    " available_at_basis, fetched_at, fetch_status, metadata"
                    " FROM source_version WHERE id = :id RETURNING id"
                ),
                {
                    "document": document_id,
                    "id": recorded["source_version_id"],
                    "content_sha256": V2_SHA,
                    "parsed_object_uri": parsed_uri,
                },
            ).scalar_one()
        )


def create_assertion(atlas: Atlas, version_id: str, quote: str, start: int, **extra: Any) -> Any:
    return atlas.api.post(
        "/api/v1/assertions",
        json={
            "subject_company_id": atlas.company("coherent")["id"],
            "predicate": "expands_capacity_for",
            "value_json": {"product": "InP"},
            "source_version_id": version_id,
            "quote": quote,
            "span_start": start,
            "span_end": start + len(quote),
            "epistemic_type": "company_claim",
            **extra,
        },
    )


def reparse(atlas: Atlas, *args: str) -> dict[str, Any]:
    """`atlas ledger reparse`, then one worker pass; the job."""
    job_id = atlas.enqueue("ledger", "reparse", *args)
    atlas.worker_pass()
    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    return job


def parse_text(atlas: Atlas, version_id: str, parser_version: str | None = None) -> Any:
    params = {"kind": "parsed"} | ({"parser_version": parser_version} if parser_version else {})
    return atlas.api.get(f"/api/v1/source-versions/{version_id}/content", params=params)


def audit_events(atlas: Atlas, entity_type: str) -> list[dict[str, Any]]:
    with atlas.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT action, entity_id, new_hash FROM audit_event"
                " WHERE entity_type = :type ORDER BY id"
            ),
            {"type": entity_type},
        ).mappings()
        return [dict(row) for row in rows]


def claim(**fields: JsonValue) -> dict[str, JsonValue]:
    return {
        "object_company_id": None,
        "object_name": None,
        "object_text": None,
        "product": None,
        "layer": "module",
        "epistemic_type": "company_claim",
        **fields,
    }


def quoting(*claims: dict[str, JsonValue]) -> Callable[[dict[str, Any]], JsonValue]:
    """An Investigator answer quoting the passages it is sent (the passage holding each quote,
    at the quote's offsets there)."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = json.loads(body["messages"][1]["content"])["retrieved_data"]
        answered: list[JsonValue] = []
        for each in claims:
            quote = str(each["quote"])
            holding = [p for p in passages if quote in p["text"]]
            assert holding, f"no passage sent holds {quote!r}"
            start = holding[0]["text"].index(quote)
            answered.append(
                each
                | {
                    "passage_id": holding[0]["id"],
                    "quote_start": start,
                    "quote_end": start + len(quote),
                }
            )
        return {"claims": answered}

    return respond


# --- the re-parse ---------------------------------------------------------------------------------


def test_a_text_v2_version_reparsed_to_text_v3_gets_a_separate_audited_parse_record(
    atlas: Atlas,
) -> None:
    earlier = record_under_text_v2(atlas)
    # An Assertion made on the v2 parse, before the re-parse.
    start = PARSE_V2.index(CAPACITY)
    assert start != PARSE_V3.index(CAPACITY)
    made = create_assertion(atlas, earlier, CAPACITY, start)
    assert made.status_code == 201, made.text
    older = made.json()["assertion"]
    assert older["parser_version"] == "text-v2"

    job = reparse(atlas, "--company", "coherent", "--parser-version", "text-v3")

    # Only the version recorded under an older parser is re-parsed (the import is text-v3).
    artifacts = job["artifacts"]
    assert (artifacts["parser_version"], artifacts["selected"], artifacts["inserted"]) == (
        "text-v3",
        1,
        1,
    )
    (made_parse,) = artifacts["parses"]
    assert made_parse["source_version_id"] == earlier
    assert made_parse["recorded_parser_version"] == "text-v2"
    assert (made_parse["parse_status"], made_parse["content_sha256"]) == ("parsed", V3_SHA)
    assert made_parse["same_text_as_recorded"] is False

    version = atlas.get(f"/api/v1/source-versions/{earlier}")
    # The recorded parse is unchanged ...
    assert (version["parser_version"], version["content_sha256"]) == ("text-v2", V2_SHA)
    assert atlas.parsed(earlier) == PARSE_V2
    # ... and the re-parse is a second parse record, with a different content hash.
    recorded, reparsed = version["parses"]
    assert {k: recorded[k] for k in ("parser_version", "recorded", "content_sha256")} == {
        "parser_version": "text-v2",
        "recorded": True,
        "content_sha256": V2_SHA,
    }
    assert (recorded["source_parse_id"], recorded["job_id"]) == (None, None)
    assert {
        k: reparsed[k] for k in ("parser_version", "recorded", "parse_status", "content_sha256")
    } == {
        "parser_version": "text-v3",
        "recorded": False,
        "parse_status": "parsed",
        "content_sha256": V3_SHA,
    }
    assert reparsed["source_parse_id"] == made_parse["source_parse_id"]
    assert reparsed["job_id"] == job["id"]
    assert reparsed["content"] == (
        f"/api/v1/source-versions/{earlier}/content?kind=parsed&parser_version=text-v3"
    )
    assert version["current_parser_version"] == "text-v3"
    served = parse_text(atlas, earlier, "text-v3")
    assert served.status_code == 200, served.text
    assert served.text == PARSE_V3
    assert served.headers["X-Content-SHA256"] == V3_SHA
    assert parse_text(atlas, earlier, "text-v2").text == PARSE_V2
    assert parse_text(atlas, earlier, "text-v9").status_code == 404
    # The raw bytes were re-read from the archive, not refetched: they are the import's.
    raw = atlas.api.get(f"/api/v1/source-versions/{earlier}/content", params={"kind": "raw"})
    assert raw.content == filing()

    # The audit trail records the new parse record.
    (event,) = audit_events(atlas, "source_parse")
    assert (event["action"], event["entity_id"]) == (
        "source_parse.created",
        made_parse["source_parse_id"],
    )
    verified = atlas.cli("audit", "verify")
    assert verified.returncode == 0, verified.stdout + verified.stderr

    # The older Assertion stays bound to the v2 parse, and its span still verifies there.
    still = atlas.get(f"/api/v1/assertions/{older['id']}")
    assert still == older
    assert atlas.parsed(earlier)[still["span_start"] : still["span_end"]] == CAPACITY

    # Running it again inserts nothing.
    again = reparse(atlas)
    assert (again["artifacts"]["selected"], again["artifacts"]["inserted"]) == (0, 0)
    assert len(audit_events(atlas, "source_parse")) == 1
    assert atlas.get(f"/api/v1/source-versions/{earlier}")["parses"] == version["parses"]


def test_a_reparse_is_never_overwritten_and_never_the_recorded_parser(atlas: Atlas) -> None:
    earlier = record_under_text_v2(atlas)
    reparse(atlas)
    refused = [
        "UPDATE source_parse SET content_sha256 = :sha",
        "DELETE FROM source_parse",
        "TRUNCATE source_parse",
        # A re-parse under the parser the version was recorded with.
        "INSERT INTO source_parse (id, source_version_id, parser_version, parse_status,"
        " content_sha256, parsed_object_uri) SELECT gen_random_uuid(), id, 'text-v2', 'parsed',"
        " :sha, parsed_object_uri FROM source_version WHERE id = :version",
    ]
    for sql in refused:
        with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
            connection.execute(text(sql), {"sha": V2_SHA, "version": earlier})
    (reparsed,) = [
        p for p in atlas.get(f"/api/v1/source-versions/{earlier}")["parses"] if not p["recorded"]
    ]
    assert reparsed["content_sha256"] == V3_SHA


def test_only_the_current_parser_reparses(atlas: Atlas) -> None:
    refused = atlas.cli("ledger", "reparse", "--parser-version", "text-v2")
    assert refused.returncode == 2
    assert "text-v3" in refused.stderr
    unknown = atlas.cli("ledger", "reparse", "--company", "no-such-company")
    assert unknown.returncode == 2


# --- readers choose the parse -------------------------------------------------------------------


def test_an_extraction_on_a_reparsed_version_quotes_the_new_parse(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    earlier = record_under_text_v2(atlas)
    older = create_assertion(atlas, earlier, CAPACITY, PARSE_V2.index(CAPACITY)).json()
    reparse(atlas)
    coherent, lumentum = atlas.company("coherent")["id"], atlas.company("lumentum")["id"]
    llm.script_chat(
        ChatReply.answer(
            quoting(
                claim(
                    subject_company_id=coherent,
                    predicate="supplies",
                    object_company_id=lumentum,
                    product="transceivers",
                    quote=SUPPLY_QUOTE,
                )
            )
        )
    )

    job_id = atlas.enqueue(
        "jobs",
        "enqueue",
        "extract_claims",
        "--key",
        "reparsed",
        "--payload",
        json.dumps({"source_version_ids": [earlier]}),
    )
    atlas.worker_pass()

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    assert (job["artifacts"]["accepted"], job["artifacts"]["rejected"]) == (1, 0)
    extraction = atlas.get(f"/api/v1/claim-extractions/{job['artifacts']['extraction_id']}")
    assert {p["parser_version"] for p in extraction["passages"]} == {"text-v3"}
    (accepted,) = atlas.get("/api/v1/claims", extraction_id=extraction["id"])["items"]
    assert (accepted["outcome"], accepted["parser_version"]) == ("accepted", "text-v3")
    assertion = atlas.get(f"/api/v1/assertions/{accepted['assertion_id']}")
    assert (assertion["source_version_id"], assertion["parser_version"]) == (earlier, "text-v3")
    start, end = assertion["span_start"], assertion["span_end"]
    assert (start, end) == (
        PARSE_V3.index(SUPPLY_QUOTE),
        PARSE_V3.index(SUPPLY_QUOTE) + len(SUPPLY_QUOTE),
    )
    assert parse_text(atlas, earlier, "text-v3").text[start:end] == SUPPLY_QUOTE
    assert SUPPLY_QUOTE not in PARSE_V2
    # The older Assertion still verifies against text-v2, the parse it was made on.
    before = atlas.get(f"/api/v1/assertions/{older['assertion']['id']}")
    assert before["parser_version"] == "text-v2"
    assert atlas.parsed(earlier)[before["span_start"] : before["span_end"]] == CAPACITY


def test_an_assertion_is_checked_against_the_parse_it_names(atlas: Atlas) -> None:
    earlier = record_under_text_v2(atlas)
    reparse(atlas)
    v3_start = PARSE_V3.index(CAPACITY)

    # The recorded parse by default: v3 offsets are not the quote's there.
    default = create_assertion(atlas, earlier, CAPACITY, v3_start)
    assert default.status_code == 422, default.text
    assert default.json()["error"]["code"] == "quote_mismatch"

    named = create_assertion(atlas, earlier, CAPACITY, v3_start, parser_version="text-v3")
    assert named.status_code == 201, named.text
    assert named.json()["assertion"]["parser_version"] == "text-v3"

    missing = create_assertion(atlas, earlier, CAPACITY, v3_start, parser_version="text-v9")
    assert missing.status_code == 422, missing.text
    assert missing.json()["error"]["code"] == "no_parsed_text"

    # An Assertion's parse is a statement column: immutable.
    with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
        connection.execute(
            text("UPDATE assertion SET parser_version = 'text-v2' WHERE id = :id"),
            {"id": named.json()["assertion"]["id"]},
        )
    # The database refuses an Assertion citing a parse the version doesn't have.
    with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO assertion (id, subject_company_id, predicate, source_version_id,"
                " quote, span_start, span_end, epistemic_type, extractor_version, created_by,"
                " parser_version) SELECT :id, subject_company_id, predicate, source_version_id,"
                " quote, span_start, span_end, epistemic_type, 'manual', 'x', 'text-v9'"
                " FROM assertion WHERE parser_version = 'text-v3'"
            ),
            {"id": uuid.uuid4()},
        )
