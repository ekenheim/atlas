"""The corpus already in Memory, brought to the current standard (memory-quality ticket 12;
`docs/decisions.md`, "A backfill replaces a section's document").

`memory_replacement`: one row each time a backfill deleted a section's Hindsight document to
retain it again under the current retain profile. It records the memories the deleted document
held (`replaced_memory_ids`), the state and profile the section had, and the run. Hindsight
gives a document's new facts new IDs (recorded 0.10.2: `recordings/delete_and_retain/`), so
this is how a pointer, a citation or a snapshot that names an old memory reads as *replaced*
rather than broken (`atlas.research.provenance`). A section taken with no memories (a failed or
cancelled one) has an empty list: the row also says the backfill has taken it.

Insert-only: rows are never updated or deleted.

Revision ID: 0067
Revises: 0070 (re-chained at merge)
"""

from alembic import op

revision = "0067"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE memory_replacement (
            id uuid PRIMARY KEY,
            memory_document_id uuid NOT NULL REFERENCES memory_document (id),
            bank_id text NOT NULL CHECK (btrim(bank_id) <> ''),
            hindsight_document_id text NOT NULL CHECK (btrim(hindsight_document_id) <> ''),
            run_key text NOT NULL CHECK (btrim(run_key) <> ''),
            from_state text NOT NULL,
            from_profile text,
            replaced_memory_ids jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(replaced_memory_ids) = 'array'),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX memory_replacement_document ON memory_replacement (memory_document_id)"
    )
    op.execute("CREATE INDEX memory_replacement_run ON memory_replacement (run_key)")
    op.execute(
        "CREATE INDEX memory_replacement_memories ON memory_replacement"
        " USING gin (replaced_memory_ids jsonb_path_ops)"
    )
    op.execute("""
        CREATE FUNCTION memory_replacement_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'memory_replacement rows are insert-only (% is not allowed)', TG_OP;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER memory_replacement_guard BEFORE UPDATE OR DELETE ON memory_replacement
        FOR EACH ROW EXECUTE FUNCTION memory_replacement_guard()
    """)
    op.execute("""
        CREATE TRIGGER memory_replacement_no_truncate BEFORE TRUNCATE ON memory_replacement
        FOR EACH STATEMENT EXECUTE FUNCTION memory_replacement_guard()
    """)
    for trigger in ("memory_replacement_guard", "memory_replacement_no_truncate"):
        op.execute(f"ALTER TABLE memory_replacement ENABLE ALWAYS TRIGGER {trigger}")
    op.execute("REVOKE ALL ON memory_replacement FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON memory_replacement TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE memory_replacement")
    op.execute("DROP FUNCTION memory_replacement_guard()")
