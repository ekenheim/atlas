"""EDGAR dissemination time: a new basis, and recorded corrections for existing versions.

- `source_version.available_at_basis` gains `sec_dissemination`: an EDGAR filing accepted
  outside the dissemination window is available from 06:00 ET on the next business day, not
  from acceptance (docs/decisions.md, "EDGAR dissemination time").
- `source_version_availability_correction`: append-only. A Source Version is immutable, so a
  version recorded before this rule (basis `sec_acceptance`, accepted after hours) gets its
  corrected availability here instead, at most one per version, and only ever later than
  the recorded one. `atlas ledger correct-availability` writes them.
- `source_version_availability`: the availability every reader uses, the correction if any,
  else the version's own, alongside what the version recorded.

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_BASES = "'sec_acceptance', 'publisher_timestamp', 'observed_discovery', 'observed_revision'"


def upgrade() -> None:
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_available_at_basis_check")
    op.execute(f"""
        ALTER TABLE source_version ADD CONSTRAINT source_version_available_at_basis_check
            CHECK (available_at_basis IN ({_BASES}, 'sec_dissemination'))
    """)
    op.execute("""
        CREATE TABLE source_version_availability_correction (
            id uuid PRIMARY KEY,
            source_version_id uuid NOT NULL UNIQUE REFERENCES source_version (id),
            available_at timestamptz NOT NULL,
            available_at_basis text NOT NULL CHECK (available_at_basis IN ('sec_dissemination')),
            reason text NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE FUNCTION source_version_availability_correction_later() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT FROM source_version
                WHERE id = NEW.source_version_id AND available_at < NEW.available_at
            ) THEN
                RAISE EXCEPTION 'an availability correction must be later than the version''s';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    table = "source_version_availability_correction"
    op.execute(f"""
        CREATE TRIGGER {table}_later BEFORE INSERT ON {table}
        FOR EACH ROW EXECUTE FUNCTION source_version_availability_correction_later()
    """)
    op.execute(f"""
        CREATE TRIGGER {table}_no_change BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION ledger_reject_change()
    """)
    op.execute(f"""
        CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
        FOR EACH STATEMENT EXECUTE FUNCTION ledger_reject_change()
    """)
    for trigger in ("later", "no_change", "no_truncate"):
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_{trigger}")
    op.execute("""
        CREATE VIEW source_version_availability AS
        SELECT v.id AS source_version_id,
               coalesce(c.available_at, v.available_at) AS available_at,
               coalesce(c.available_at_basis, v.available_at_basis) AS available_at_basis,
               v.available_at AS recorded_available_at,
               v.available_at_basis AS recorded_available_at_basis,
               c.id AS correction_id
        FROM source_version v
        LEFT JOIN source_version_availability_correction c ON c.source_version_id = v.id
    """)
    op.execute(f"REVOKE ALL ON {table}, source_version_availability FROM PUBLIC")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON {table} TO atlas_app;
                GRANT SELECT ON source_version_availability TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP VIEW source_version_availability")
    op.execute("DROP TABLE source_version_availability_correction")
    op.execute("DROP FUNCTION source_version_availability_correction_later()")
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_available_at_basis_check")
    op.execute(f"""
        ALTER TABLE source_version ADD CONSTRAINT source_version_available_at_basis_check
            CHECK (available_at_basis IN ({_BASES}))
    """)
