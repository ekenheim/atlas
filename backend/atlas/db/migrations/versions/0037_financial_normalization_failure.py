"""Failed XBRL normalizations (docs/decisions.md, "XBRL normalization": a failure is recorded).

- `financial_normalization_failure`: **insert-only**, one row per failed attempt to normalize
  a companyfacts Source Version: which version, company and normalizer version, the error's
  class and message, and the ingest job that tried. Nothing it attempted was stored (the
  normalization's transaction rolled back), so the version stays unnormalized and the next
  ingest tries again; a later success is a `financial_normalization` row as usual. Like
  `financial_normalization`, triggers refuse every UPDATE, DELETE and TRUNCATE.

Revision ID: 0037
Revises: 0036 (re-chained at merge)
"""

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE financial_normalization_failure (
            id uuid PRIMARY KEY,
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            company_id uuid NOT NULL REFERENCES company (id),
            normalizer_version text NOT NULL CHECK (btrim(normalizer_version) <> ''),
            error_class text NOT NULL CHECK (btrim(error_class) <> ''),
            error text NOT NULL,
            job_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
    """)
    op.execute(
        "CREATE INDEX financial_normalization_failure_version ON"
        " financial_normalization_failure (source_version_id, created_at)"
    )
    table = "financial_normalization_failure"
    op.execute(f"""
        CREATE TRIGGER {table}_no_change BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION ledger_reject_change()
    """)
    op.execute(f"""
        CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
        FOR EACH STATEMENT EXECUTE FUNCTION ledger_reject_change()
    """)
    op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_no_change")
    op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_no_truncate")
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON {table} TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE financial_normalization_failure")
