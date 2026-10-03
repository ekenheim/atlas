"""Atlas's records are reconciled with Memory every night (memory-quality ticket 22).

- `memory_reconciliation`: one insert-only row per run of the `reconcile_memory` job: the bank,
  the job, when the run started and ended, its `status` (`clean`: no difference found; `drift`:
  at least one; `failed`: a Hindsight listing or read failed, with the `error`, and no counts:
  a partial result is never reported as clean), the differences by kind (`counts`, `samples`:
  up to 20 IDs each, `details`) and the `usage` table (Hindsight's traced LLM calls of the bank
  in the last 24 h by operation beside what Atlas's budgets counted; report only, never drift).
  Rows are never updated or removed.

Revision ID: 0076
Revises: 0075
"""

from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE memory_reconciliation (
            id uuid PRIMARY KEY,
            bank_id text NOT NULL CHECK (btrim(bank_id) <> ''),
            job_id uuid UNIQUE REFERENCES job (id),
            started_at timestamptz NOT NULL,
            ended_at timestamptz NOT NULL,
            status text NOT NULL CHECK (status IN ('clean', 'drift', 'failed')),
            error text,
            counts jsonb NOT NULL DEFAULT '{}'::jsonb,
            samples jsonb NOT NULL DEFAULT '{}'::jsonb,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            usage jsonb,
            recorded_at timestamptz NOT NULL DEFAULT now(),
            CHECK (ended_at >= started_at),
            CHECK ((status = 'failed') = (error IS NOT NULL))
        )
    """)
    op.execute(
        "CREATE INDEX memory_reconciliation_bank ON memory_reconciliation (bank_id, started_at)"
    )
    op.execute("""
        CREATE FUNCTION memory_reconciliation_insert_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'memory_reconciliation rows are insert-only (% is not allowed)', TG_OP;
        END
        $$
    """)
    triggers = {
        "memory_reconciliation_insert_only": "BEFORE UPDATE OR DELETE ON memory_reconciliation"
        " FOR EACH ROW EXECUTE FUNCTION memory_reconciliation_insert_only()",
        "memory_reconciliation_no_truncate": "BEFORE TRUNCATE ON memory_reconciliation"
        " FOR EACH STATEMENT EXECUTE FUNCTION memory_reconciliation_insert_only()",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE memory_reconciliation ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON memory_reconciliation FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON memory_reconciliation TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE memory_reconciliation")
    op.execute("DROP FUNCTION memory_reconciliation_insert_only()")
