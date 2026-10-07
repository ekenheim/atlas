"""The reading agent (bottleneck-argument ticket 03).

`reader_session`: one row per Reader (or argument Skeptic) working one argument step of one
question: its run, the job or investigation task it runs in (`key`: `task:<id>` or
`job:<id>`, so a retried, paused or budget-resumed one continues where it stopped), and its
progress (`state`: the calls made, what was searched, recalled, read, recorded and refused,
and the last results). Updated after every action; the Facts it records are insert-only in
`fact`.

`investigation.plan` (ticket 05): `default` (Scout, Investigators, Skeptic and Financial
Analyst, Editor) or `argument` (Scout, one Reader per argument step, Skeptic and Financial
Analyst, the Editor writing the argument); `investigation_task.role` gains `reader`.

Revision ID: 0100
Revises: 0099
"""

from alembic import op

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None

_ROLES = "'scout', 'investigator', 'skeptic', 'financial_analyst', 'editor'"
_STEPS = "'constraint', 'demand_vs_supply', 'relief', 'control', 'capture', 'invalidation'"


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE reader_session (
            id uuid PRIMARY KEY,
            key text NOT NULL UNIQUE,
            run_id uuid NOT NULL REFERENCES run (id),
            job_id uuid REFERENCES job (id),
            task_id uuid REFERENCES investigation_task (id),
            investigation_id uuid REFERENCES investigation (id),
            role text NOT NULL CHECK (role IN ('reader', 'skeptic')),
            step text NOT NULL CHECK (step IN ({_STEPS})),
            question text NOT NULL,
            as_of timestamptz NOT NULL,
            status text NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'done', 'bounded', 'budget_exhausted')),
            stop_reason text,
            state jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((task_id IS NULL) = (investigation_id IS NULL))
        )
    """)
    op.execute(
        "CREATE INDEX ix_reader_session_investigation ON reader_session (investigation_id)"
        " WHERE investigation_id IS NOT NULL"
    )
    # The argument plan (ticket 05): chosen when the investigation is created; its Readers are
    # tasks of their own role.
    op.execute(
        "ALTER TABLE investigation ADD COLUMN plan text NOT NULL DEFAULT 'default'"
        " CONSTRAINT investigation_plan_check CHECK (plan IN ('default', 'argument'))"
    )
    op.execute(
        "ALTER TABLE investigation_task DROP CONSTRAINT investigation_task_role_check,"
        f" ADD CONSTRAINT investigation_task_role_check CHECK (role IN ({_ROLES}, 'reader'))"
    )
    op.execute("REVOKE ALL ON reader_session FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON reader_session TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE reader_session")
    op.execute("DELETE FROM investigation_task WHERE role = 'reader'")
    op.execute(
        "ALTER TABLE investigation_task DROP CONSTRAINT investigation_task_role_check,"
        f" ADD CONSTRAINT investigation_task_role_check CHECK (role IN ({_ROLES}))"
    )
    op.execute("ALTER TABLE investigation DROP COLUMN plan")
