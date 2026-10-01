import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
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
    assert revision == "0055"


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
