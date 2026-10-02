import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from atlas.db.migrate import upgrade


def test_migrate_upgrades_an_empty_database_to_head(
    empty_database_url: str, tmp_path: Path
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "ATLAS_DATABASE_URL": empty_database_url,
        "ATLAS_ACTOR": "local-researcher",
        "ATLAS_ARCHIVE_ROOT": str(archive),
    }

    result = subprocess.run(
        [sys.executable, "-m", "atlas", "migrate"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    engine = create_engine(empty_database_url)
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    assert revision == "0074"


def test_versions_recorded_before_0014_are_english(empty_database_url: str) -> None:
    # Before 0014 every Source Version came from SEC EDGAR, whose filings are in English.
    upgrade(empty_database_url, "0012")
    engine = create_engine(empty_database_url)
    sha = "a" * 64
    with engine.begin() as connection:
        document = connection.execute(
            text(
                "INSERT INTO source_document (id, provider, canonical_url, origin_url,"
                " source_type, title, publisher, source_tier, license_class, first_seen_at)"
                " VALUES (gen_random_uuid(), 'sec_edgar', 'https://www.sec.gov/x.htm',"
                " 'https://www.sec.gov/x.htm', 'filing', 'x', 'SEC EDGAR', 'A',"
                " 'public_regulatory', now()) RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO source_version (id, source_document_id, version_number,"
                " raw_sha256, comparison_sha256, comparison_rule, object_uri, byte_size,"
                " media_type, parse_status, available_at, available_at_basis, fetched_at,"
                " fetch_status) VALUES (gen_random_uuid(), :document, 1, :sha, :sha,"
                " 'identity', :uri, 1, 'application/json', 'not_applicable', now(),"
                " 'observed_discovery', now(), 'ok')"
            ),
            {"document": document, "sha": sha, "uri": f"archive://raw/sha256/{sha}"},
        )

    upgrade(empty_database_url)

    with engine.connect() as connection:
        row = connection.execute(text("SELECT language, page_anchors FROM source_version")).one()
        default = connection.execute(
            text(
                "SELECT column_default FROM information_schema.columns"
                " WHERE table_name = 'source_version' AND column_name = 'language'"
            )
        ).scalar_one()
    engine.dispose()
    assert (row.language, row.page_anchors) == ("en", None)
    assert default is None  # later versions get their language from the ledger only


def test_a_company_on_lse_rns_moves_to_the_fca_nsm(empty_database_url: str) -> None:
    # 0025: LSE RNS is not allowed (docs/decisions.md); IQE comes from the FCA NSM.
    upgrade(empty_database_url, "0023")
    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO company (id, slug, legal_name, display_name, country, source_path)"
                " VALUES (gen_random_uuid(), 'iqe', 'IQE plc', 'IQE', 'GB', 'exchange:lse-rns')"
            )
        )

    upgrade(empty_database_url)

    with engine.connect() as connection:
        path = connection.execute(text("SELECT source_path FROM company")).scalar_one()
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE company SET source_path = 'exchange:lse-rns'"))
    except DBAPIError as error:
        refused = "company_source_path_check" in str(error)
    else:
        refused = False
    engine.dispose()
    assert path == "exchange:fca-nsm"
    assert refused


def test_a_company_on_euronext_moves_to_the_amf_api(empty_database_url: str) -> None:
    # 0029: Euronext's terms forbid robots (docs/decisions.md); Soitec comes from the AMF API.
    upgrade(empty_database_url, "0028")
    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO company (id, slug, legal_name, display_name, country, source_path)"
                " VALUES (gen_random_uuid(), 'soitec', 'Soitec SA', 'Soitec', 'FR',"
                " 'exchange:euronext')"
            )
        )

    upgrade(empty_database_url)

    with engine.connect() as connection:
        path = connection.execute(text("SELECT source_path FROM company")).scalar_one()
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE company SET source_path = 'exchange:euronext'"))
    except DBAPIError as error:
        refused = "company_source_path_check" in str(error)
    else:
        refused = False
    engine.dispose()
    assert path == "exchange:amf"
    assert refused


def test_assertions_recorded_before_0046_quote_their_versions_recorded_parse(
    empty_database_url: str,
) -> None:
    # 0046: an Assertion records the parse its span is in; earlier ones are all in the parse
    # their Source Version was recorded with.
    upgrade(empty_database_url, "0045")
    engine = create_engine(empty_database_url)
    sha = "b" * 64
    with engine.begin() as connection:
        company = connection.execute(
            text(
                "INSERT INTO company (id, slug, legal_name, display_name, country, source_path,"
                " cik) VALUES (gen_random_uuid(), 'x', 'X Inc.', 'X', 'US', 'sec', '0000000001')"
                " RETURNING id"
            )
        ).scalar_one()
        document = connection.execute(
            text(
                "INSERT INTO source_document (id, provider, canonical_url, origin_url,"
                " source_type, title, publisher, source_tier, license_class, first_seen_at)"
                " VALUES (gen_random_uuid(), 'sec_edgar', 'https://www.sec.gov/y.htm',"
                " 'https://www.sec.gov/y.htm', 'filing', 'y', 'SEC EDGAR', 'A',"
                " 'public_regulatory', now()) RETURNING id"
            )
        ).scalar_one()
        version = connection.execute(
            text(
                "INSERT INTO source_version (id, source_document_id, version_number,"
                " raw_sha256, comparison_sha256, comparison_rule, object_uri, byte_size,"
                " media_type, content_sha256, parsed_object_uri, parser_version, parse_status,"
                " language, available_at, available_at_basis, fetched_at, fetch_status)"
                " VALUES (gen_random_uuid(), :document, 1, :sha, :sha, 'identity', :uri, 1,"
                " 'text/html', :sha, :parsed, 'text-v2', 'parsed', 'en', now(),"
                " 'sec_acceptance', now(), 'ok') RETURNING id"
            ),
            {
                "document": document,
                "sha": sha,
                "uri": f"archive://raw/sha256/{sha}",
                "parsed": f"archive://parsed/sha256/{sha}",
            },
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO assertion (id, subject_company_id, predicate, source_version_id,"
                " quote, span_start, span_end, epistemic_type, extractor_version, created_by)"
                " VALUES (gen_random_uuid(), :company, 'manufactures', :version, 'lasers', 0, 6,"
                " 'company_claim', 'manual', 'x')"
            ),
            {"company": company, "version": version},
        )

    upgrade(empty_database_url)

    with engine.connect() as connection:
        parser_version = connection.execute(
            text("SELECT parser_version FROM assertion")
        ).scalar_one()
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE assertion SET parser_version = 'text-v3'"))
    except DBAPIError as error:
        refused = "immutable" in str(error)
    else:
        refused = False
    engine.dispose()
    assert parser_version == "text-v2"
    assert refused


def test_counterevidence_recorded_before_0053_is_a_contradiction_only_when_it_names_a_claim(
    empty_database_url: str,
) -> None:
    upgrade(empty_database_url, "0050")
    engine = create_engine(empty_database_url)
    insert = text(
        "INSERT INTO counterevidence (id, search_id, investigation_id, run_id, role_call_id,"
        " batch, ordinal, proposed, checklist_item, passage_id, statement, quote,"
        " epistemic_type, contradicts_claim_ids, outcome, reason_code, assertion_id,"
        " evidence_family, independent, independence_detail) VALUES (gen_random_uuid(),"
        " :parent, :parent, :parent, :parent, 0, :ordinal, '{}', 'inventory_cycle', 's1',"
        " :statement, 'a quote', 'company_claim', CAST(:claims AS uuid[]), :outcome, :reason,"
        " :assertion, :family, :independent, :detail)"
    )
    parent = "00000000-0000-0000-0000-000000000001"
    claim = "00000000-0000-0000-0000-0000000000c1"
    accepted: dict[str, Any] = {
        "outcome": "accepted",
        "reason": None,
        "family": "version:x",
        "independent": True,
        "detail": "its Evidence Family is none of the supporting Claims'",
    }
    rows: list[dict[str, Any]] = [
        accepted | {"statement": "names a Claim", "claims": [claim], "assertion": parent},
        accepted | {"statement": "names no Claim", "claims": [], "assertion": claim},
        {
            "statement": "rejected",
            "claims": [],
            "outcome": "rejected",
            "reason": "quote_mismatch",
            "assertion": None,
            "family": None,
            "independent": None,
            "detail": None,
        },
    ]
    with engine.begin() as connection:
        # The rows' parents (a search, an investigation, a run, a role call, Assertions) are
        # not what is migrated: foreign keys are off for these inserts.
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        for ordinal, row in enumerate(rows):
            connection.execute(insert, row | {"parent": parent, "ordinal": ordinal})

    upgrade(empty_database_url)

    with engine.connect() as connection:
        migrated = {
            row.statement: (row.kind, row.how, row.kind_reason, row.independent)
            for row in connection.execute(
                text("SELECT statement, kind, how, kind_reason, independent FROM counterevidence")
            )
        }
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE counterevidence SET kind = 'contradiction'"))
    except DBAPIError as error:
        still_insert_only = "insert-only" in str(error)
    else:
        still_insert_only = False
    engine.dispose()
    # What was recorded stays as it was; only the kind is new.
    assert migrated == {
        "names a Claim": ("contradiction", None, None, True),
        "names no Claim": ("bear_context", None, None, True),
        "rejected": ("bear_context", None, None, None),
    }
    assert still_insert_only


def test_edges_that_differ_only_by_layer_before_0055_are_kept_and_no_new_one_can_be_made(
    empty_database_url: str,
) -> None:
    # 0055: the layer leaves the edge's identity. Edges recorded before it keep their layer;
    # of a group that differs only by layer, all but the oldest are marked, never merged.
    upgrade(empty_database_url, "0052")
    engine = create_engine(empty_database_url)
    insert = (
        "INSERT INTO relationship (id, subject_company_id, predicate, object_text, object_key,"
        " layer, review_state, created_at) VALUES (gen_random_uuid(), :company,"
        " 'expands_capacity_for', :object, :key, :layer, 'machine_reviewed',"
        " now() - make_interval(days => :age))"
    )
    with engine.begin() as connection:
        company = connection.execute(
            text(
                "INSERT INTO company (id, slug, legal_name, display_name, country, source_path,"
                " cik) VALUES (gen_random_uuid(), 'x', 'X Inc.', 'X', 'US', 'sec', '0000000001')"
                " RETURNING id"
            )
        ).scalar_one()
        # One fact in three layers (pilot investigation 1), and an edge of its own.
        for age, layer in [(3, "epi"), (2, "substrate"), (1, "chip-laser")]:
            connection.execute(
                text(insert),
                {
                    "company": company,
                    "object": "indium phosphide capacity",
                    "key": "indium phosphide capacity",
                    "layer": layer,
                    "age": age,
                },
            )
        connection.execute(
            text(insert),
            {
                "company": company,
                "object": "EML lasers",
                "key": "eml lasers",
                "layer": "chip-laser",
                "age": 1,
            },
        )

    upgrade(empty_database_url)

    with engine.connect() as connection:
        edges = connection.execute(
            text(
                "SELECT object_key, layer, legacy_layer_duplicate FROM relationship"
                " ORDER BY object_key, created_at"
            )
        ).all()
    assert [tuple(edge) for edge in edges] == [
        ("eml lasers", "chip-laser", False),
        ("indium phosphide capacity", "epi", False),
        ("indium phosphide capacity", "substrate", True),
        ("indium phosphide capacity", "chip-laser", True),
    ]
    new = (
        "INSERT INTO relationship (id, subject_company_id, predicate, object_text, object_key,"
        " layer, review_state) VALUES (gen_random_uuid(), :company, 'expands_capacity_for',"
        " :object, :key, :layer, 'machine_reviewed')"
    )
    refused: list[str] = []
    # No further edge for either identity, with another layer or with none.
    for key, layer in [("indium phosphide capacity", "module"), ("eml lasers", None)]:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(new), {"company": company, "object": key, "key": key, "layer": layer}
                )
        except DBAPIError as error:
            if "uq_relationship_identity" in str(error):
                refused.append(key)
    # A new identity may have no layer, and takes one once.
    with engine.begin() as connection:
        connection.execute(
            text(new),
            {"company": company, "object": "a new fab", "key": "a new fab", "layer": None},
        )
        connection.execute(
            text("UPDATE relationship SET layer = 'chip-laser' WHERE object_key = 'a new fab'")
        )
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE relationship SET layer = 'module' WHERE object_key = 'a new fab'")
            )
    except DBAPIError as error:
        fixed = "set once" in str(error)
    else:
        fixed = False
    engine.dispose()
    assert refused == ["indium phosphide capacity", "eml lasers"]
    assert fixed


def test_from_0057_an_edge_may_have_no_object_one_per_company_and_only_a_constraint(
    empty_database_url: str,
) -> None:
    # 0057: a company-level `capacity_constrained` edge has neither an object company nor an
    # object text; its key is the reserved empty string. Edges recorded before it are untouched.
    upgrade(empty_database_url, "0055")
    engine = create_engine(empty_database_url)
    insert = (
        "INSERT INTO relationship (id, subject_company_id, predicate, object_text, object_key,"
        " layer, review_state) VALUES (gen_random_uuid(), :company, :predicate, :object, :key,"
        " :layer, 'machine_reviewed')"
    )
    with engine.begin() as connection:
        company = connection.execute(
            text(
                "INSERT INTO company (id, slug, legal_name, display_name, country, source_path,"
                " cik) VALUES (gen_random_uuid(), 'x', 'X Inc.', 'X', 'US', 'sec', '0000000001')"
                " RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(insert),
            {
                "company": company,
                "predicate": "capacity_constrained",
                "object": "EML lasers",
                "key": "eml lasers",
                "layer": "chip-laser",
            },
        )
    # Before 0057 an edge needs an object.
    assert _refusal(engine, insert, company, "capacity_constrained", None, "", None) is not None

    upgrade(empty_database_url)

    with engine.connect() as connection:
        before = connection.execute(
            text("SELECT object_text, object_key, layer FROM relationship")
        ).all()
    assert [tuple(edge) for edge in before] == [("EML lasers", "eml lasers", "chip-laser")]
    # The company's own edge: no object, the empty key, no layer.
    assert _refusal(engine, insert, company, "capacity_constrained", None, "", None) is None
    refusals = {
        "a second one": _refusal(engine, insert, company, "capacity_constrained", None, "", None),
        "with a layer": _refusal(
            engine, insert, company, "capacity_constrained", None, "", "module"
        ),
        "another predicate": _refusal(engine, insert, company, "sole_sources", None, "", None),
        "a text with the empty key": _refusal(
            engine, insert, company, "capacity_constrained", "EML lasers", "", None
        ),
        "no text with a key": _refusal(
            engine, insert, company, "capacity_constrained", None, "our products", None
        ),
    }
    with engine.connect() as connection:
        edges = connection.execute(
            text("SELECT predicate, object_text, object_key FROM relationship ORDER BY object_key")
        ).all()
        claim_default = connection.execute(
            text(
                "SELECT column_default, is_nullable FROM information_schema.columns"
                " WHERE table_name = 'claim' AND column_name = 'company_level'"
            )
        ).one()
    engine.dispose()
    assert {what: _constraint(refusal) for what, refusal in refusals.items()} == {
        "a second one": "uq_relationship_identity",
        "with a layer": "relationship_company_level_check",
        "another predicate": "relationship_company_level_check",
        "a text with the empty key": "relationship_object_key_check",
        "no text with a key": "relationship_object_key_check",
    }
    assert [tuple(edge) for edge in edges] == [
        ("capacity_constrained", None, ""),
        ("capacity_constrained", "EML lasers", "eml lasers"),
    ]
    assert tuple(claim_default) == ("false", "NO")


def _refusal(
    engine: Engine,
    insert: str,
    company: object,
    predicate: str,
    object_text: str | None,
    key: str,
    layer: str | None,
) -> str | None:
    """Why the database refuses the edge (None: it was inserted)."""
    try:
        with engine.begin() as connection:
            connection.execute(
                text(insert),
                {
                    "company": company,
                    "predicate": predicate,
                    "object": object_text,
                    "key": key,
                    "layer": layer,
                },
            )
    except DBAPIError as error:
        return str(error)
    return None


def _constraint(refusal: str | None) -> str | None:
    """The constraint or index a refusal names, of those 0057 is about."""
    names = (
        "uq_relationship_identity",
        "relationship_company_level_check",
        "relationship_object_key_check",
        "relationship_object_check",
    )
    return next((name for name in names if refusal is not None and name in refusal), None)


def test_investigations_recorded_before_0058_take_the_default_company_budget(
    empty_database_url: str,
) -> None:
    # 0058: the company budget (Investigators a round, the seeds counted). An investigation
    # recorded before it takes the default, 6; a new one states its own, within 1 to 25.
    upgrade(empty_database_url, "0055")
    engine = create_engine(empty_database_url)

    def insert(question: str, column: str = "", value: str = "") -> str:
        return (
            "INSERT INTO investigation (id, theme, question, seed_company_ids, as_of, bank_id,"
            f" max_rounds, max_leads, max_documents, token_budget, created_by{column})"
            f" VALUES (gen_random_uuid(), 'photonics', '{question}', ARRAY[gen_random_uuid()],"
            f" now(), 'atlas', 2, 10, 25, 200000, 'local-researcher'{value})"
        )

    with engine.begin() as connection:
        connection.execute(text(insert("before")))

    upgrade(empty_database_url)

    with engine.connect() as connection:
        before = connection.execute(text("SELECT max_companies FROM investigation")).scalar_one()
    refused: list[str] = []
    for value in ("", ", 0", ", 26"):
        try:
            with engine.begin() as connection:
                column = ", max_companies" if value else ""
                connection.execute(text(insert(f"after{value}", column, value)))
        except DBAPIError:
            refused.append(value)
    with engine.begin() as connection:
        connection.execute(text(insert("stated", ", max_companies", ", 3")))
        stated = connection.execute(
            text("SELECT max_companies FROM investigation WHERE question = 'stated'")
        ).scalar_one()
    engine.dispose()
    assert before == 6
    assert refused == ["", ", 0", ", 26"]  # no default; and the bounds
    assert stated == 3


def test_reading_pointers_recorded_before_0059_are_the_scout_s(empty_database_url: str) -> None:
    # 0059: a pointer says what its query was. The rows recorded before it are the Scout's;
    # a Skeptic's bear-checklist pointer names its checklist item and company.
    upgrade(empty_database_url, "0055")
    engine = create_engine(empty_database_url)
    parent = "00000000-0000-0000-0000-000000000001"
    before = (
        "INSERT INTO reading_pointer (id, investigation_id, round, task_id, query_index, query,"
        " rank, memory_id, memory_type, memory_text, source_version_id, section_anchor,"
        " section_char_start, section_char_end, available_at, citation_state"
    )
    values = (
        " VALUES (gen_random_uuid(), :parent, 1, :parent, :index, 'a query', :rank, 'm1',"
        " 'world', 'a fact', :parent, 'part-i-item-1', 0, 10, now(), 'resolved'"
    )
    with engine.begin() as connection:
        # The row's parents (an investigation, a task, a Source Version, a company) are not
        # what is migrated: foreign keys are off for these inserts.
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(text(f"{before}){values})"), {"parent": parent, "index": 2, "rank": 1})

    upgrade(empty_database_url)

    new = text(
        f"{before}, query_kind, checklist_item, query_company_id){values}, :kind, :item, :company)"
    )
    refused: list[str] = []
    with engine.connect() as connection:
        recorded = connection.execute(
            text("SELECT query_kind, checklist_item, query_company_id FROM reading_pointer")
        ).one()
    attempts: list[dict[str, Any]] = [
        # A bear-checklist pointer without its item or its company, and a Scout's with one.
        {"kind": "bear_checklist", "item": None, "company": parent, "index": 1, "rank": 2},
        {"kind": "bear_checklist", "item": "inventory_cycle", "company": None, "index": 1}
        | {"rank": 3},
        {"kind": "scout", "item": "inventory_cycle", "company": parent, "index": 1, "rank": 4},
        {"kind": "bear_checklist", "item": "inventory_cycle", "company": parent, "index": 3}
        | {"rank": 5},
    ]
    for attempt in attempts:
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(new, attempt | {"parent": parent})
        except DBAPIError as error:
            assert "reading_pointer_bear_checklist_query" in str(error)
            refused.append(str(attempt["rank"]))
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE reading_pointer SET query_kind = 'scout'"))
    except DBAPIError as error:
        still_insert_only = "insert-only" in str(error)
    else:
        still_insert_only = False
    with engine.connect() as connection:
        kinds = [
            tuple(row)
            for row in connection.execute(
                text("SELECT query_kind, checklist_item FROM reading_pointer ORDER BY rank")
            )
        ]
    engine.dispose()
    assert tuple(recorded) == ("scout", None, None)
    assert refused == ["2", "3", "4"]
    assert kinds == [("scout", None), ("bear_checklist", "inventory_cycle")]
    assert still_insert_only


def test_an_entity_pointer_names_the_company_it_was_found_for_and_its_entity(
    empty_database_url: str,
) -> None:
    # 0064: the entity hop's pointers (memory-quality ticket 09) are a third kind, `entity`,
    # with the company the hop was made for and the entity its facts were listed by; only an
    # entity pointer has an entity, and it never collides with a recall pointer.
    upgrade(empty_database_url)
    engine = create_engine(empty_database_url)
    parent = "00000000-0000-0000-0000-000000000001"
    insert = text(
        "INSERT INTO reading_pointer (id, investigation_id, round, task_id, query_index, query,"
        " rank, memory_id, memory_type, memory_text, source_version_id, section_anchor,"
        " section_char_start, section_char_end, available_at, citation_state, query_kind,"
        " query_company_id, entity_id) VALUES (gen_random_uuid(), :parent, 1, :parent, 1,"
        " 'Coherent Corp.', 1, 'm1', 'world', 'a fact', :parent, 'chunk-001', 0, 10, now(),"
        " 'resolved', :kind, :company, :entity)"
    )
    attempts: list[dict[str, Any]] = [
        {"kind": "entity", "company": parent, "entity": "e-1"},  # stored
        {"kind": "scout", "company": None, "entity": None},  # a recall pointer beside it
        {"kind": "entity", "company": None, "entity": "e-1"},  # no company it was found for
        {"kind": "entity", "company": parent, "entity": None},  # no entity
        {"kind": "scout", "company": None, "entity": "e-1"},  # a recall pointer's entity
    ]
    outcomes: list[str] = []
    for attempt in attempts:
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(insert, attempt | {"parent": parent})
            outcomes.append("stored")
        except DBAPIError as error:
            assert "reading_pointer_bear_checklist_query" in str(error)
            outcomes.append("refused")
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE reading_pointer SET entity_id = 'e-2'"))
    except DBAPIError as error:
        still_insert_only = "insert-only" in str(error)
    else:
        still_insert_only = False
    engine.dispose()
    assert outcomes == ["stored", "stored", "refused", "refused", "refused"]
    assert still_insert_only


def test_sections_failed_by_a_cancellation_before_0068_are_cancelled(
    empty_database_url: str,
) -> None:
    # 0068: an owner's cancellation is not a failure. The sections recorded `failed` with
    # exactly the cancellation's error move to `cancelled`; the other failed sections take the
    # class their error shows; nothing else changes.
    upgrade(empty_database_url, "0061")
    engine = create_engine(empty_database_url)
    cancelled = "Hindsight reported the operation cancelled with no error message"
    missing = "document srcv:x:cover not found in Hindsight after its operation completed"
    rows = [
        ("a", "failed", cancelled, None),
        ("b", "failed", "Hindsight reported the operation failed with no error message", None),
        ("c", "failed", missing, None),
        ("d", "failed", f"{cancelled} (and more)", None),
        ("e", "completed", None, 3),
    ]
    insert = text(
        "INSERT INTO memory_document (id, source_version_id, section_anchor, char_start,"
        " char_end, sectioner_version, hindsight_document_id, bank_id, retain_state,"
        " fact_count, template_version, error) VALUES (gen_random_uuid(), :version, :anchor,"
        " 0, 10, 'sec-items-v1', :document, 'atlas', :state, :facts, '1.1.0', :error)"
    )
    operation = text(
        "INSERT INTO hindsight_operation (id, bank_id, kind, status, source_version_id,"
        " document_ids, error_class) VALUES (:id, 'atlas', 'retain', :status, :version,"
        " '[]'::jsonb, :class)"
    )
    version = "00000000-0000-0000-0000-000000000001"
    with engine.begin() as connection:
        # The rows' Source Version is not what is migrated: foreign keys are off here.
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        for anchor, state, error, facts in rows:
            connection.execute(
                insert,
                {
                    "version": version,
                    "anchor": anchor,
                    "document": f"srcv:{version}:{anchor}",
                    "state": state,
                    "facts": facts,
                    "error": error,
                },
            )
        connection.execute(
            operation,
            {"id": "op-cancelled", "status": "cancelled", "version": version}
            | {"class": "permanent"},
        )
        connection.execute(
            operation,
            {"id": "op-failed", "status": "failed", "version": version} | {"class": "permanent"},
        )

    upgrade(empty_database_url, "0068")  # its rows have no parent: 0062 updates them

    with engine.connect() as connection:
        sections = {
            row.section_anchor: (row.retain_state, row.error_class, row.error)
            for row in connection.execute(
                text("SELECT section_anchor, retain_state, error_class, error FROM memory_document")
            )
        }
        operations = dict(
            connection.execute(text("SELECT id, error_class FROM hindsight_operation")).all()
        )
    refused: list[str] = []
    for state, error_class, error in (
        ("cancelled", None, cancelled),  # a cancelled section has its class
        ("cancelled", "cancelled", None),  # and keeps an error
        ("failed", None, "an error"),  # a failed one has a class
        ("completed", "permanent", None),  # nothing else has one
    ):
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(
                    text(
                        "INSERT INTO memory_document (id, source_version_id, section_anchor,"
                        " char_start, char_end, sectioner_version, hindsight_document_id,"
                        " bank_id, retain_state, fact_count, template_version, error,"
                        " error_class) VALUES (gen_random_uuid(), :version, 'z', 0, 10,"
                        " 'sec-items-v1', :document, 'atlas', :state, 1, '1.1.0', :error,"
                        " :class)"
                    ),
                    {
                        "version": version,
                        "document": f"srcv:{version}:z-{len(refused)}-{state}",
                        "state": state,
                        "error": error,
                        "class": error_class,
                    },
                )
        except DBAPIError:
            refused.append(state)
    engine.dispose()
    assert sections == {
        "a": ("cancelled", "cancelled", cancelled),
        "b": ("failed", "permanent", rows[1][2]),
        "c": ("failed", "missing", missing),
        "d": ("failed", "permanent", rows[3][2]),
        "e": ("completed", None, None),
    }
    assert operations == {"op-cancelled": "cancelled", "op-failed": "permanent"}
    assert refused == ["cancelled", "cancelled", "failed", "completed"]


def test_sections_retained_before_0062_read_as_the_first_retain_profile(
    empty_database_url: str,
) -> None:
    # 0062: a memory document records the retain profile it was submitted under. Every
    # section retained before it is `retain-v1`, with no context or entities recorded; a
    # linked section was never submitted and has none.
    upgrade(empty_database_url, "0068")
    engine = create_engine(empty_database_url)
    version = "00000000-0000-0000-0000-000000000001"
    twin = "00000000-0000-0000-0000-000000000002"
    insert = text(
        "INSERT INTO memory_document (id, source_version_id, section_anchor, char_start,"
        " char_end, sectioner_version, hindsight_document_id, bank_id, retain_state,"
        " fact_count, template_version, linked_to_source_version_id) VALUES"
        " (gen_random_uuid(), :version, :anchor, 0, 10, 'sec-items-v1', :document, 'b',"
        " :state, :facts, 't1', :linked)"
    )
    rows: list[dict[str, Any]] = [
        {"version": version, "anchor": "cover", "state": "completed", "facts": 2, "linked": None},
        {"version": version, "anchor": "item-1", "state": "pending", "facts": None, "linked": None},
        {"version": twin, "anchor": "cover", "state": "linked", "facts": None, "linked": version},
    ]
    with engine.begin() as connection:
        # The rows' parents (the Source Versions) are not what is migrated.
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        for row in rows:
            document = None if row["linked"] else f"srcv:{row['version']}:{row['anchor']}"
            connection.execute(insert, row | {"document": document})

    upgrade(empty_database_url)

    with engine.connect() as connection:
        recorded = [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT retain_state, retain_profile, retain_context, retain_entities"
                    " FROM memory_document ORDER BY retain_state"
                )
            )
        ]
    engine.dispose()
    assert recorded == [
        ("completed", "retain-v1", None, None),
        ("linked", None, None, None),
        ("pending", "retain-v1", None, None),
    ]


def test_chat_completions_recorded_before_0072_ignored_no_field(empty_database_url: str) -> None:
    # 0072: an answer's unknown fields are dropped and recorded on its attempt. An attempt
    # recorded before ignored none (such a field was a validation error, which it still says).
    upgrade(empty_database_url, "0064")  # the revision before 0072
    engine = create_engine(empty_database_url)
    errors = '[{"type": "extra_forbidden", "loc": ["claims", 0, "claim_id"], "msg": "Extra"}]'
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "INSERT INTO llm_call (id, role_call_id, run_id, attempt, response_model,"
                " tokens_in, tokens_out, content, validation_errors) VALUES"
                " (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), 1, 'MiniMax-M3',"
                " 10, 2, '{}', CAST(:errors AS jsonb))"
            ),
            {"errors": errors},
        )

    upgrade(empty_database_url)

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT ignored_fields, validation_errors FROM llm_call")
        ).one()
    engine.dispose()
    assert row.ignored_fields == []
    assert row.validation_errors[0]["type"] == "extra_forbidden"
