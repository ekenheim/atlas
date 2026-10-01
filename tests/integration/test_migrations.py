import os
import subprocess
import sys
from pathlib import Path

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
    assert revision == "0051"


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
