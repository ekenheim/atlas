"""Re-parses: a Source Version's parse under a later parser version, as a separate record.

Pilot-fixes ticket 11 (docs/decisions.md, "Page artifacts and parser version `text-v3`",
the re-parse design, and "Re-parsing recorded Source Versions"):

- `source_parse`: one row per (Source Version, parser version) the `reparse` job parsed the
  version's archived raw bytes with. Insert-only (a trigger refuses UPDATE, DELETE and
  TRUNCATE), and never the parser version the version was recorded with: the
  `source_version` parse columns stay the parse the version was recorded with.
- `source_version_parse`: every parse of a version, the recorded one (`recorded`) and its
  re-parses, so a reader asks for a parse by (version, parser version).
- `assertion.parser_version`: the parse an Assertion's span is in. Every Assertion recorded
  before this migration quotes its version's recorded parse, and gets its parser version.
  An insert that leaves it NULL gets the recorded one; one naming another must name a parse
  with text (`parsed` or `incomplete`). It is a statement column: immutable like the others.
- `claim.parser_version`: the parse a Claim's passage was cut from (NULL for Claims recorded
  before this migration, which all read the recorded parse, and for Claims naming no
  passage sent).

The downgrade refuses while any re-parse exists.

Revision ID: 0046
Revises: 0045
"""

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

_STATEMENT = (
    "id, subject_company_id, predicate, object_company_id, value_json, source_version_id,"
    " quote, span_start, span_end, page_or_anchor, event_start, event_end, epistemic_type,"
    " independence_family_id, extracted_at, extractor_version, created_by"
)


def _columns(prefix: str, statement: str) -> str:
    return ", ".join(f"{prefix}.{column.strip()}" for column in statement.split(","))


def _guard_update(statement: str) -> str:
    """Migration 0006's review guard over the given statement columns."""
    return f"""
        CREATE OR REPLACE FUNCTION assertion_guard_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF ({_columns("NEW", statement)}) IS DISTINCT FROM ({_columns("OLD", statement)}) THEN
                RAISE EXCEPTION 'assertion statement columns are immutable';
            END IF;
            IF OLD.verification_status IN ('rejected', 'superseded') THEN
                RAISE EXCEPTION 'assertion review is final (%)', OLD.verification_status;
            END IF;
            IF NEW.verification_status = 'unreviewed'
               OR NEW.verification_status = OLD.verification_status THEN
                RAISE EXCEPTION 'assertion review % -> % is not a transition',
                    OLD.verification_status, NEW.verification_status;
            END IF;
            IF NEW.superseded_by IS NOT NULL AND NOT EXISTS (
                SELECT FROM assertion
                WHERE id = NEW.superseded_by
                  AND verification_status NOT IN ('rejected', 'superseded')
            ) THEN
                RAISE EXCEPTION 'an assertion is superseded only by a live assertion';
            END IF;
            RETURN NEW;
        END
        $$
    """


def upgrade() -> None:
    op.execute("""
        CREATE TABLE source_parse (
            id uuid PRIMARY KEY,
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            parser_version text NOT NULL CHECK (btrim(parser_version) <> ''),
            parse_status text NOT NULL
                CHECK (parse_status IN ('parsed', 'incomplete', 'failed', 'unsupported')),
            parse_error text,
            content_sha256 text,
            parsed_object_uri text,
            language text,
            page_anchors jsonb,
            job_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source_version_id, parser_version),
            CHECK ((parse_status IN ('parsed', 'incomplete'))
                   = (content_sha256 IS NOT NULL AND parsed_object_uri IS NOT NULL)),
            CHECK ((parse_status IN ('failed', 'unsupported')) = (parse_error IS NOT NULL)),
            CHECK (page_anchors IS NULL OR parse_status IN ('parsed', 'incomplete'))
        )
    """)
    op.execute("""
        CREATE FUNCTION source_parse_guard_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT FROM source_version
                WHERE id = NEW.source_version_id AND parser_version = NEW.parser_version
            ) THEN
                RAISE EXCEPTION 'source version % was recorded with parser %: a re-parse is'
                    ' under another parser version', NEW.source_version_id, NEW.parser_version;
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE FUNCTION source_parse_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'source_parse is insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    triggers = {
        "source_parse_new": "BEFORE INSERT ON source_parse FOR EACH ROW"
        " EXECUTE FUNCTION source_parse_guard_insert()",
        "source_parse_no_change": "BEFORE UPDATE OR DELETE ON source_parse FOR EACH ROW"
        " EXECUTE FUNCTION source_parse_reject_change()",
        "source_parse_no_truncate": "BEFORE TRUNCATE ON source_parse FOR EACH STATEMENT"
        " EXECUTE FUNCTION source_parse_reject_change()",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE source_parse ENABLE ALWAYS TRIGGER {name}")

    op.execute("""
        CREATE VIEW source_version_parse AS
            SELECT v.id AS source_version_id, v.parser_version, v.parse_status, v.parse_error,
                   v.content_sha256, v.parsed_object_uri, v.language, v.page_anchors,
                   true AS recorded, NULL::uuid AS source_parse_id, NULL::uuid AS job_id,
                   v.ingested_at AS parsed_at
            FROM source_version v WHERE v.parser_version IS NOT NULL
            UNION ALL
            SELECT p.source_version_id, p.parser_version, p.parse_status, p.parse_error,
                   p.content_sha256, p.parsed_object_uri, p.language, p.page_anchors,
                   false, p.id, p.job_id, p.created_at
            FROM source_parse p
    """)

    # Assertions: the parse the span is in. Existing ones quote the recorded parse; the review
    # guard (ENABLE ALWAYS) would refuse the backfill as a non-transition, so it is off for it.
    op.execute("ALTER TABLE assertion ADD COLUMN parser_version text")
    op.execute("ALTER TABLE assertion DISABLE TRIGGER assertion_review")
    op.execute("""
        UPDATE assertion a SET parser_version = v.parser_version
        FROM source_version v WHERE v.id = a.source_version_id
    """)
    op.execute("ALTER TABLE assertion ENABLE ALWAYS TRIGGER assertion_review")
    op.execute("ALTER TABLE assertion ALTER COLUMN parser_version SET NOT NULL")
    op.execute(_guard_update(f"{_STATEMENT}, parser_version"))
    op.execute("""
        CREATE OR REPLACE FUNCTION assertion_guard_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.verification_status <> 'unreviewed' THEN
                RAISE EXCEPTION 'a new assertion is unreviewed, not %', NEW.verification_status;
            END IF;
            IF NEW.parser_version IS NULL THEN
                NEW.parser_version := (
                    SELECT parser_version FROM source_version WHERE id = NEW.source_version_id
                );
            END IF;
            IF NOT EXISTS (
                SELECT FROM source_version_parse
                WHERE source_version_id = NEW.source_version_id
                  AND parser_version = NEW.parser_version
                  AND parse_status IN ('parsed', 'incomplete')
            ) THEN
                RAISE EXCEPTION 'an assertion must cite a source version with parsed text'
                    ' (parser version %)', NEW.parser_version;
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("ALTER TABLE claim ADD COLUMN parser_version text")

    op.execute("REVOKE ALL ON source_parse FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON source_parse TO atlas_app;
                GRANT SELECT ON source_version_parse TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    # Assertions and Claims may quote a re-parse, and neither is ever deleted.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM source_parse) THEN
                RAISE EXCEPTION 're-parses exist: Assertions may quote them, so 0046 stays';
            END IF;
        END
        $$
    """)
    op.execute("ALTER TABLE claim DROP COLUMN parser_version")
    op.execute("""
        CREATE OR REPLACE FUNCTION assertion_guard_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.verification_status <> 'unreviewed' THEN
                RAISE EXCEPTION 'a new assertion is unreviewed, not %', NEW.verification_status;
            END IF;
            IF NOT EXISTS (
                SELECT FROM source_version
                WHERE id = NEW.source_version_id AND parse_status IN ('parsed', 'incomplete')
            ) THEN
                RAISE EXCEPTION 'an assertion must cite a source version with parsed text';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute(_guard_update(_STATEMENT))
    op.execute("ALTER TABLE assertion DROP COLUMN parser_version")
    op.execute("DROP VIEW source_version_parse")
    op.execute("DROP TABLE source_parse")
    op.execute("DROP FUNCTION source_parse_reject_change()")
    op.execute("DROP FUNCTION source_parse_guard_insert()")
