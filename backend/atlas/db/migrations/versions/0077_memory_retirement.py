"""Memory holds the intake window (pilot-review ticket 23; `docs/decisions.md`, "Memory holds the
intake window").

- `memory_document.retain_state` gains `retired`: the section's Hindsight document was deleted
  because its Source Version was available before the intake window; the Source Version stays in
  the ledger and the archive, citable. Nothing takes a retired section back.
- `memory_retirement`: one insert-only row per section retired: the memories the deleted
  document held (`retired_memory_ids`, so a citation of one reads `memory_retired`, not broken),
  the state and profile the section had, the run, the date bound (`before`), the job, whether
  Hindsight still had the document (`document_deleted`) and the `memory_units_deleted` it
  answered with.

Rows are never updated or removed.

Revision ID: 0077
Revises: 0076
"""

from alembic import op

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None

_STATES = "'pending', 'completed', 'failed', 'zero_fact', 'linked', 'cancelled'"


def upgrade() -> None:
    op.execute("ALTER TABLE memory_document DROP CONSTRAINT memory_document_retain_state_check")
    op.execute(f"""
        ALTER TABLE memory_document ADD CONSTRAINT memory_document_retain_state_check
            CHECK (retain_state IN ({_STATES}, 'retired'))
    """)
    op.execute("""
        CREATE TABLE memory_retirement (
            id uuid PRIMARY KEY,
            memory_document_id uuid NOT NULL REFERENCES memory_document (id),
            bank_id text NOT NULL CHECK (btrim(bank_id) <> ''),
            hindsight_document_id text NOT NULL CHECK (btrim(hindsight_document_id) <> ''),
            run_key text NOT NULL CHECK (btrim(run_key) <> ''),
            before_date timestamptz NOT NULL,
            job_id uuid REFERENCES job (id),
            from_state text NOT NULL,
            from_profile text,
            retired_memory_ids jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(retired_memory_ids) = 'array'),
            document_deleted boolean NOT NULL,
            memory_units_deleted integer CHECK (memory_units_deleted >= 0),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX memory_retirement_document ON memory_retirement (memory_document_id)")
    op.execute("CREATE INDEX memory_retirement_run ON memory_retirement (run_key)")
    op.execute(
        "CREATE INDEX memory_retirement_memories ON memory_retirement"
        " USING gin (retired_memory_ids jsonb_path_ops)"
    )
    op.execute("""
        CREATE FUNCTION memory_retirement_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'memory_retirement rows are insert-only (% is not allowed)', TG_OP;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER memory_retirement_guard BEFORE UPDATE OR DELETE ON memory_retirement
        FOR EACH ROW EXECUTE FUNCTION memory_retirement_guard()
    """)
    op.execute("""
        CREATE TRIGGER memory_retirement_no_truncate BEFORE TRUNCATE ON memory_retirement
        FOR EACH STATEMENT EXECUTE FUNCTION memory_retirement_guard()
    """)
    for trigger in ("memory_retirement_guard", "memory_retirement_no_truncate"):
        op.execute(f"ALTER TABLE memory_retirement ENABLE ALWAYS TRIGGER {trigger}")
    op.execute("REVOKE ALL ON memory_retirement FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON memory_retirement TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE memory_retirement")
    op.execute("DROP FUNCTION memory_retirement_guard()")
    op.execute("ALTER TABLE memory_document DROP CONSTRAINT memory_document_retain_state_check")
    op.execute(f"""
        ALTER TABLE memory_document ADD CONSTRAINT memory_document_retain_state_check
            CHECK (retain_state IN ({_STATES}))
    """)
