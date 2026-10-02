"""Atlas decides when Memory consolidates (memory-quality ticket 19).

- `memory_consolidation`: one row per decision of a `consolidate` job about the research bank:
  `skipped` (nothing retained since the last completed consolidation, or a retain of the bank
  queued or running), or a request Atlas submitted (`submitted` while its operation runs,
  then `completed` or `failed`). A submitted row holds Hindsight's operation ID, whether
  Hindsight reused a pending task for it (`deduplicated`), its last reported status and, once
  terminal, its error and result metadata. `sections_retained` is how many sections had been
  retained since the last completed consolidation when the job decided.

Invariants the database enforces:
- At most one `submitted` row per bank, so Atlas never has two consolidation requests of the
  bank running at once.
- A skip has a reason and no operation; a request has an operation and no reason.
- Rows are never deleted.

Each submitted row is one unit of the `codex` budget (`atlas.jobs.budget`).

Revision ID: 0069
Revises: 0066 (re-chained at merge)
"""

from alembic import op

revision = "0069"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE memory_consolidation (
            id uuid PRIMARY KEY,
            bank_id text NOT NULL CHECK (btrim(bank_id) <> ''),
            job_id uuid REFERENCES job (id),
            scheduled_for date,
            status text NOT NULL
                CHECK (status IN ('skipped', 'submitted', 'completed', 'failed')),
            skip_reason text CHECK (skip_reason IN ('nothing_retained', 'retains_pending')),
            operation_id text CHECK (btrim(operation_id) <> ''),
            deduplicated boolean NOT NULL DEFAULT false,
            operation_status text,
            error text,
            error_class text CHECK (error_class IN ('quota', 'unavailable', 'permanent')),
            result_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(result_metadata) = 'object'),
            sections_retained integer NOT NULL CHECK (sections_retained >= 0),
            requested_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((status = 'skipped') = (skip_reason IS NOT NULL)),
            CHECK ((status = 'skipped') = (operation_id IS NULL)),
            CHECK ((status IN ('skipped', 'completed', 'failed')) = (completed_at IS NOT NULL))
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX memory_consolidation_one_running ON memory_consolidation (bank_id)"
        " WHERE status = 'submitted'"
    )
    op.execute(
        "CREATE INDEX memory_consolidation_bank ON memory_consolidation (bank_id, requested_at)"
    )
    op.execute("CREATE INDEX memory_consolidation_job ON memory_consolidation (job_id)")
    op.execute("""
        CREATE FUNCTION memory_consolidation_no_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'memory_consolidation rows are never removed (% is not allowed)', TG_OP;
        END
        $$
    """)
    triggers = {
        "memory_consolidation_no_delete": "BEFORE DELETE ON memory_consolidation FOR EACH ROW"
        " EXECUTE FUNCTION memory_consolidation_no_delete()",
        "memory_consolidation_no_truncate": "BEFORE TRUNCATE ON memory_consolidation"
        " FOR EACH STATEMENT EXECUTE FUNCTION memory_consolidation_no_delete()",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE memory_consolidation ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON memory_consolidation FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON memory_consolidation TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DELETE FROM provider_usage WHERE source_id LIKE 'consolidation:%'")
    op.execute("DROP TABLE memory_consolidation")
    op.execute("DROP FUNCTION memory_consolidation_no_delete()")
