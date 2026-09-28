"""The company universe and the source ledger (spec Part A "Schema"; build plan §5.1, §5.3).

Tables:
- `company`: a legal entity, seeded from `configs/themes/*.yaml`.
- `security`: effective-dated listing identifiers of a company. No two rows may claim the
  same (exchange, ticker) for overlapping dates (an exclusion constraint).
- `source_document`: the stable identity of source material, unique per
  (provider, canonical URL). Immutable once created.
- `source_version`: one immutable, hash-identified copy of a Source Document.
- `fetch_observation`: one row per fetch, including fetches that found nothing new
  (spec: "records the fetch observation without creating a version"). Append-only.

Invariants the database enforces:
- UNIQUE (source_document_id, raw_sha256): the same bytes are never two versions.
- `available_at` and `available_at_basis` are NOT NULL; the basis is an enumeration.
- A version's content columns never change, and no version is ever deleted. The parse
  columns may be written once more, only while the parse is `pending` or `failed`.
- `supersedes_version_id` is the previous version of the same Source Document; the
  chain is linear (a version is superseded at most once).
- Source Documents and fetch observations reject every UPDATE and DELETE.

The protective triggers are ENABLE ALWAYS, like the audit trail's (migration 0002).

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

HASH = "~ '^[0-9a-f]{64}$'"

_TABLES = ("company", "security", "source_document", "source_version", "fetch_observation")


def upgrade() -> None:
    # btree_gist lets the security exclusion constraint compare text with `=`. It is a
    # trusted extension, so the database owner may create it.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.execute("""
        CREATE TABLE company (
            id uuid PRIMARY KEY,
            slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]*$'),
            legal_name text NOT NULL CHECK (btrim(legal_name) <> ''),
            display_name text NOT NULL CHECK (btrim(display_name) <> ''),
            lei text CHECK (lei ~ '^[A-Z0-9]{20}$'),
            cik text UNIQUE CHECK (cik ~ '^[0-9]{10}$'),
            country text NOT NULL CHECK (country ~ '^[A-Z]{2}$'),
            website text,
            parent_company_id uuid REFERENCES company (id),
            review_state text NOT NULL DEFAULT 'unreviewed'
                CHECK (review_state IN ('unreviewed', 'reviewed')),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE security (
            id uuid PRIMARY KEY,
            company_id uuid NOT NULL REFERENCES company (id),
            ticker text NOT NULL CHECK (btrim(ticker) <> ''),
            exchange_mic text NOT NULL CHECK (exchange_mic ~ '^[A-Z0-9]{4}$'),
            isin text CHECK (isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'),
            figi text CHECK (figi ~ '^[A-Z0-9]{12}$'),
            instrument_type text NOT NULL CHECK (btrim(instrument_type) <> ''),
            currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
            valid_from date NOT NULL,
            valid_to date CHECK (valid_to > valid_from),
            UNIQUE (company_id, exchange_mic, ticker, valid_from),
            CONSTRAINT security_no_overlapping_listing EXCLUDE USING gist (
                exchange_mic WITH =,
                ticker WITH =,
                daterange(valid_from, valid_to, '[)') WITH &&
            )
        )
    """)
    op.execute("CREATE INDEX security_company ON security (company_id)")

    op.execute("""
        CREATE TABLE source_document (
            id uuid PRIMARY KEY,
            company_id uuid REFERENCES company (id),
            provider text NOT NULL CHECK (btrim(provider) <> ''),
            canonical_url text NOT NULL CHECK (canonical_url ~ '^https?://'),
            origin_url text NOT NULL CHECK (btrim(origin_url) <> ''),
            accession text CHECK (accession ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
            form_type text,
            document_type text,
            source_type text NOT NULL CHECK (btrim(source_type) <> ''),
            title text NOT NULL,
            publisher text NOT NULL CHECK (btrim(publisher) <> ''),
            source_tier text NOT NULL CHECK (source_tier IN ('A', 'B', 'C')),
            license_class text NOT NULL CHECK (
                license_class IN ('public_regulatory', 'public_issuer', 'lead_metadata',
                                  'manual_lead', 'synthetic_fixture')
                OR license_class ~ '^licensed:[a-z0-9_-]+$'
            ),
            first_seen_at timestamptz NOT NULL,
            UNIQUE (provider, canonical_url)
        )
    """)
    # One accession holds several documents (a primary document and its exhibits).
    op.execute("CREATE INDEX source_document_accession ON source_document (accession)")
    op.execute("CREATE INDEX source_document_company ON source_document (company_id)")

    op.execute(f"""
        CREATE TABLE source_version (
            id uuid PRIMARY KEY,
            source_document_id uuid NOT NULL REFERENCES source_document (id),
            version_number integer NOT NULL CHECK (version_number >= 1),
            raw_sha256 text NOT NULL CHECK (raw_sha256 {HASH}),
            -- The change-detection hash: raw_sha256 of the bytes after `comparison_rule`
            -- removed volatile, non-content bytes (e.g. SEC's edge-injected <script>).
            comparison_sha256 text NOT NULL CHECK (comparison_sha256 {HASH}),
            comparison_rule text NOT NULL CHECK (btrim(comparison_rule) <> ''),
            object_uri text NOT NULL CHECK (object_uri ~ '^archive://raw/sha256/[0-9a-f]{{64}}$'),
            byte_size bigint NOT NULL CHECK (byte_size >= 0),
            media_type text NOT NULL CHECK (btrim(media_type) <> ''),
            content_sha256 text CHECK (content_sha256 {HASH}),
            parsed_object_uri text
                CHECK (parsed_object_uri ~ '^archive://parsed/sha256/[0-9a-f]{{64}}$'),
            parser_version text,
            parse_status text NOT NULL CHECK (
                parse_status IN ('pending', 'parsed', 'incomplete', 'failed', 'not_applicable')
            ),
            parse_error text,
            event_at timestamptz,
            published_at timestamptz,
            available_at timestamptz NOT NULL,
            available_at_basis text NOT NULL CHECK (
                available_at_basis IN ('sec_acceptance', 'publisher_timestamp',
                                       'observed_discovery')
            ),
            fetched_at timestamptz NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT now(),
            supersedes_version_id uuid UNIQUE REFERENCES source_version (id),
            fetch_status text NOT NULL CHECK (fetch_status IN ('ok', 'partial')),
            metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb
                CHECK (jsonb_typeof(metadata) = 'object'),
            UNIQUE (source_document_id, raw_sha256),
            UNIQUE (source_document_id, version_number),
            CHECK ((version_number = 1) = (supersedes_version_id IS NULL)),
            CHECK ((parse_status IN ('parsed', 'incomplete'))
                   = (content_sha256 IS NOT NULL AND parsed_object_uri IS NOT NULL)),
            CHECK (parse_status IN ('pending', 'not_applicable') OR parser_version IS NOT NULL),
            CHECK ((parse_status = 'failed') = (parse_error IS NOT NULL))
        )
    """)

    op.execute(f"""
        CREATE TABLE fetch_observation (
            id uuid PRIMARY KEY,
            source_document_id uuid NOT NULL REFERENCES source_document (id),
            -- The version these bytes are (or match); for a 304, the latest version.
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            job_id uuid REFERENCES job (id),
            outcome text NOT NULL CHECK (outcome IN ('new_version', 'unchanged', 'not_modified')),
            url text NOT NULL,
            fetched_at timestamptz NOT NULL,
            observed_at timestamptz NOT NULL DEFAULT now(),
            raw_sha256 text CHECK (raw_sha256 {HASH}),
            comparison_sha256 text CHECK (comparison_sha256 {HASH}),
            -- Set when this fetch's exact bytes differ from the matched version's, so
            -- they stay archived although they made no new version.
            object_uri text CHECK (object_uri ~ '^archive://raw/sha256/[0-9a-f]{{64}}$'),
            etag text,
            last_modified text,
            attempts integer NOT NULL CHECK (attempts >= 1),
            CHECK ((outcome = 'not_modified') = (raw_sha256 IS NULL)),
            CHECK ((outcome = 'not_modified') = (comparison_sha256 IS NULL))
        )
    """)
    op.execute(
        "CREATE INDEX fetch_observation_document ON fetch_observation"
        " (source_document_id, observed_at DESC)"
    )
    op.execute("CREATE INDEX fetch_observation_version ON fetch_observation (source_version_id)")

    op.execute("""
        CREATE FUNCTION ledger_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is immutable: % is not allowed', TG_TABLE_NAME, TG_OP;
        END
        $$
    """)
    op.execute("""
        CREATE FUNCTION source_version_guard_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.id, NEW.source_document_id, NEW.version_number, NEW.raw_sha256,
                NEW.comparison_sha256, NEW.comparison_rule, NEW.object_uri, NEW.byte_size,
                NEW.media_type, NEW.event_at, NEW.published_at, NEW.available_at,
                NEW.available_at_basis, NEW.fetched_at, NEW.ingested_at,
                NEW.supersedes_version_id, NEW.fetch_status, NEW.metadata)
               IS DISTINCT FROM
               (OLD.id, OLD.source_document_id, OLD.version_number, OLD.raw_sha256,
                OLD.comparison_sha256, OLD.comparison_rule, OLD.object_uri, OLD.byte_size,
                OLD.media_type, OLD.event_at, OLD.published_at, OLD.available_at,
                OLD.available_at_basis, OLD.fetched_at, OLD.ingested_at,
                OLD.supersedes_version_id, OLD.fetch_status, OLD.metadata)
            THEN
                RAISE EXCEPTION 'source_version content columns are immutable';
            END IF;
            IF OLD.parse_status NOT IN ('pending', 'failed') THEN
                RAISE EXCEPTION 'source_version parse is already recorded (%)', OLD.parse_status;
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE FUNCTION source_version_check_supersedes() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.supersedes_version_id IS NOT NULL AND NOT EXISTS (
                SELECT FROM source_version
                WHERE id = NEW.supersedes_version_id
                  AND source_document_id = NEW.source_document_id
                  AND version_number = NEW.version_number - 1
            ) THEN
                RAISE EXCEPTION
                    'supersedes_version_id must be the previous version of the same document';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER source_version_supersedes BEFORE INSERT ON source_version
        FOR EACH ROW EXECUTE FUNCTION source_version_check_supersedes()
    """)
    op.execute("""
        CREATE TRIGGER source_version_immutable BEFORE UPDATE ON source_version
        FOR EACH ROW EXECUTE FUNCTION source_version_guard_update()
    """)
    triggers = [
        ("source_version", "source_version_supersedes"),
        ("source_version", "source_version_immutable"),
    ]
    for table in ("source_document", "source_version", "fetch_observation"):
        # source_version's UPDATEs are vetted by source_version_immutable instead.
        rows = "DELETE" if table == "source_version" else "UPDATE OR DELETE"
        op.execute(f"""
            CREATE TRIGGER {table}_no_change BEFORE {rows} ON {table}
            FOR EACH ROW EXECUTE FUNCTION ledger_reject_change()
        """)
        op.execute(f"""
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION ledger_reject_change()
        """)
        triggers += [(table, f"{table}_no_change"), (table, f"{table}_no_truncate")]
    for table, trigger in triggers:
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger}")

    for table in _TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
    # The runtime role (see migration 0002): the ledger only ever inserts, except that
    # seeding updates companies and securities and a later parse completes a version.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON company, security TO atlas_app;
                GRANT SELECT, INSERT ON source_document, fetch_observation TO atlas_app;
                GRANT SELECT, INSERT, UPDATE ON source_version TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE fetch_observation, source_version, source_document, security, company")
    op.execute("DROP FUNCTION source_version_check_supersedes()")
    op.execute("DROP FUNCTION source_version_guard_update()")
    op.execute("DROP FUNCTION ledger_reject_change()")
