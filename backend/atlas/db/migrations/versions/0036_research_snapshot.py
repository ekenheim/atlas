"""Research Snapshots (spec §5.7 "research_snapshot"; ticket 20): what a published Hypothesis
version was built from, frozen when it is published.

- `research_snapshot`: **insert-only**, one per published Hypothesis version: the SHA-256 of
  the snapshot's canonical JSON and its archive URI (`archive://snapshots/sha256/<hex>`, the
  same hash), its size, the investigation's as-of cutoff, and who published it. The JSON
  itself lives in the archive, so it survives without the database; every read re-hashes it
  against this row. Triggers refuse every UPDATE, DELETE and TRUNCATE, and an insert for a
  version that isn't published.

Revision ID: 0036
Revises: 0035 (re-chained at merge)
"""

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE research_snapshot (
            id uuid PRIMARY KEY,
            hypothesis_id uuid NOT NULL REFERENCES hypothesis (id),
            hypothesis_version_id uuid NOT NULL UNIQUE REFERENCES hypothesis_version (id),
            sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            object_uri text NOT NULL CHECK (object_uri = 'archive://snapshots/sha256/' || sha256),
            byte_size bigint NOT NULL CHECK (byte_size > 0),
            as_of timestamptz NOT NULL,
            created_by text NOT NULL CHECK (btrim(created_by) <> ''),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_research_snapshot_hypothesis ON research_snapshot"
        " (hypothesis_id, created_at, id)"
    )
    op.execute("""
        CREATE FUNCTION research_snapshot_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'research snapshots are insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    op.execute("""
        CREATE FUNCTION research_snapshot_check_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT FROM hypothesis_version
                WHERE id = NEW.hypothesis_version_id AND hypothesis_id = NEW.hypothesis_id
                  AND published_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'a research snapshot is of a published version of its hypothesis';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    triggers = {
        "research_snapshot_published": (
            "BEFORE INSERT ON research_snapshot FOR EACH ROW",
            "research_snapshot_check_insert",
        ),
        "research_snapshot_no_update": (
            "BEFORE UPDATE ON research_snapshot FOR EACH ROW",
            "research_snapshot_reject_change",
        ),
        "research_snapshot_no_delete": (
            "BEFORE DELETE ON research_snapshot FOR EACH ROW",
            "research_snapshot_reject_change",
        ),
        "research_snapshot_no_truncate": (
            "BEFORE TRUNCATE ON research_snapshot FOR EACH STATEMENT",
            "research_snapshot_reject_change",
        ),
    }
    for name, (when, function) in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {when} EXECUTE FUNCTION {function}()")
        op.execute(f"ALTER TABLE research_snapshot ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON research_snapshot FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON research_snapshot TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE research_snapshot")
    op.execute("DROP FUNCTION research_snapshot_reject_change()")
    op.execute("DROP FUNCTION research_snapshot_check_insert()")
