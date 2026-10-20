"""The edition store (atlas-record ticket 01; ADR 0004).

`ledger_edition`: one page a scheduled task published, as Atlas read it, insert-only. The raw
page is in the archive (content-addressed; `page_uri`), and `page_sha256` is unique, so
importing the same bytes again adds no row. `ledger` is the parsed JSON object as the page wrote
it, or NULL with a `parse_error` (and then no `as_of` or `edition`: nothing readable). A later
edition of the same theme and `as_of` with different bytes is kept and marked
`same_as_of_differs`: the task rewrote its edition the same day. `source` is `drop_box` (with
the commit the page came from) or `manual`. A theme is a slug; the council's is `council`.

Updates, deletes and truncation are refused by trigger, as for the Belief and board tables.

Revision ID: 0122
Revises: 0121
"""

from alembic import op

revision = "0122"
down_revision = "0121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ledger_edition (
            id uuid PRIMARY KEY,
            seq bigint GENERATED ALWAYS AS IDENTITY,
            theme text NOT NULL CHECK (theme ~ '^[a-z][a-z0-9-]{1,40}$'),
            as_of date,
            edition integer CHECK (edition >= 0),
            page_sha256 text NOT NULL UNIQUE CHECK (page_sha256 ~ '^[0-9a-f]{64}$'),
            page_uri text NOT NULL CHECK (page_uri LIKE 'archive://%'),
            page_size integer NOT NULL CHECK (page_size > 0),
            ledger jsonb,
            parse_error text CHECK (parse_error IS NULL OR btrim(parse_error) <> ''),
            source text NOT NULL CHECK (source IN ('drop_box', 'manual')),
            commit_sha text CHECK (commit_sha IS NULL OR commit_sha ~ '^[0-9a-f]{7,64}$'),
            same_as_of_differs boolean NOT NULL DEFAULT false,
            read_at timestamptz NOT NULL,
            CONSTRAINT ledger_edition_parsed_or_error
                CHECK ((ledger IS NULL) = (parse_error IS NOT NULL)),
            CONSTRAINT ledger_edition_parsed_has_date_and_number
                CHECK ((ledger IS NULL AND as_of IS NULL AND edition IS NULL)
                    OR (ledger IS NOT NULL AND as_of IS NOT NULL AND edition IS NOT NULL)),
            CONSTRAINT ledger_edition_drop_box_has_commit
                CHECK ((source = 'drop_box') = (commit_sha IS NOT NULL)),
            CONSTRAINT ledger_edition_rewrite_needs_date
                CHECK (NOT same_as_of_differs OR as_of IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX ix_ledger_edition_theme ON ledger_edition (theme, as_of, seq)")
    op.execute(
        "CREATE TRIGGER ledger_edition_no_update BEFORE UPDATE ON ledger_edition"
        " FOR EACH ROW EXECUTE FUNCTION belief_reject_change()"
    )
    op.execute("ALTER TABLE ledger_edition ENABLE ALWAYS TRIGGER ledger_edition_no_update")
    op.execute(
        "CREATE TRIGGER ledger_edition_no_delete BEFORE DELETE ON ledger_edition"
        " FOR EACH ROW EXECUTE FUNCTION belief_reject_change()"
    )
    op.execute("ALTER TABLE ledger_edition ENABLE ALWAYS TRIGGER ledger_edition_no_delete")
    op.execute(
        "CREATE TRIGGER ledger_edition_no_truncate BEFORE TRUNCATE ON ledger_edition"
        " FOR EACH STATEMENT EXECUTE FUNCTION belief_reject_change()"
    )
    op.execute("ALTER TABLE ledger_edition ENABLE ALWAYS TRIGGER ledger_edition_no_truncate")
    op.execute("REVOKE ALL ON ledger_edition FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON ledger_edition TO atlas_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ledger_edition")
