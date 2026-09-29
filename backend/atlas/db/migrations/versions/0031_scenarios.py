"""Scenarios (spec §5.7 "scenario", Phase 5; ticket 19): deterministic low/base/high exposure
scenarios attached to a Hypothesis version.

- `scenario`: **insert-only**. One computed scenario: the Hypothesis version it belongs to,
  the company, the as-of cutoff its sources were checked at, the model code version, the
  assumption table (JSON, and the SHA-256 of its canonical form), the outputs **as their
  canonical JSON text** (so the stored bytes are the hashed bytes) and their SHA-256, and
  where the table came from: the Financial Analyst's proposal (its investigation task and
  role call) or the researcher's own table (an analyst override). A new table is a new row.

Revision ID: 0031
Revises: 0028 (re-chained at merge)
"""

from alembic import op

revision = "0031"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE scenario (
            id uuid PRIMARY KEY,
            hypothesis_id uuid NOT NULL REFERENCES hypothesis (id),
            hypothesis_version_id uuid NOT NULL REFERENCES hypothesis_version (id),
            company_id uuid NOT NULL REFERENCES company (id),
            as_of timestamptz NOT NULL,
            model_version text NOT NULL CHECK (btrim(model_version) <> ''),
            assumptions jsonb NOT NULL CHECK (jsonb_typeof(assumptions) = 'object'),
            assumptions_sha256 text NOT NULL CHECK (assumptions_sha256 ~ '^[0-9a-f]{64}$'),
            outputs text NOT NULL CHECK (outputs <> ''),
            outputs_sha256 text NOT NULL CHECK (outputs_sha256 ~ '^[0-9a-f]{64}$'),
            origin text NOT NULL CHECK (origin IN ('financial_analyst', 'researcher')),
            investigation_task_id uuid REFERENCES investigation_task (id),
            role_call_id uuid REFERENCES role_call (id),
            note text,
            created_by text NOT NULL CHECK (btrim(created_by) <> ''),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((origin = 'financial_analyst') = (investigation_task_id IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ix_scenario_hypothesis ON scenario (hypothesis_id, created_at, id)")
    op.execute("""
        CREATE FUNCTION scenario_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'scenarios are insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    triggers = {
        "scenario_no_update": "BEFORE UPDATE ON scenario FOR EACH ROW",
        "scenario_no_delete": "BEFORE DELETE ON scenario FOR EACH ROW",
        "scenario_no_truncate": "BEFORE TRUNCATE ON scenario FOR EACH STATEMENT",
    }
    for name, when in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {when} EXECUTE FUNCTION scenario_reject_change()")
        op.execute(f"ALTER TABLE scenario ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON scenario FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON scenario TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE scenario")
    op.execute("DROP FUNCTION scenario_reject_change()")
