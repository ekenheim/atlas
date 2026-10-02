"""Reflect and the mental models: grounded, and counted (memory-quality ticket 10;
`docs/decisions.md`, "Reflect and the models: grounded and counted").

- `research_answer.budget` and `.exclude_mental_models`: how deep the reflect was asked to
  search and whether it was kept from reading mental models. A row recorded before this
  revision was sent neither, so it ran at Hindsight's defaults: `low`, models read (the
  column defaults say so).
- `reflect_submission`: one row each time Atlas submits a research answer's reflect to
  Hindsight (a retried job submits again). Insert-only. Each is one unit of the `codex`
  budget (`atlas.jobs.budget`).
- `mental_model_refresh.refreshed_by`: who made the refresh the row records: `atlas` for a
  refresh Atlas's job completed; for a skip, who made the refresh it found (`atlas` when it
  is one Atlas's job completed, `hindsight` when Hindsight refreshed the model without
  Atlas: its own trigger, its API or UI). Null for a row recorded before this revision, a
  submitted or failed one, and a skip of a model never refreshed.
- `provider_usage`: the `codex` budget gains three sources, one unit each: a
  `reflect_submission`, a `mental_model_refresh` row that submitted a refresh (it has an
  operation), and a replay's `replay_answer` (its reflect). Rows that existed before this
  revision are counted at their own time, so history isn't counted as spent now.

The downgrade drops the columns and the table; the usage rows stay (they count what was
spent, which the older code also reads).

Revision ID: 0066
Revises: 0063 (re-chained at merge)
"""

from alembic import op

revision = "0066"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE research_answer
            ADD COLUMN budget text NOT NULL DEFAULT 'low' CHECK (budget IN ('low', 'mid', 'high')),
            ADD COLUMN exclude_mental_models boolean NOT NULL DEFAULT false
    """)
    op.execute("""
        CREATE TABLE reflect_submission (
            id uuid PRIMARY KEY,
            research_answer_id uuid NOT NULL REFERENCES research_answer (id),
            job_id uuid NOT NULL,
            attempt integer NOT NULL CHECK (attempt >= 1),
            submitted_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_reflect_submission_answer ON reflect_submission (research_answer_id)"
    )
    op.execute("""
        CREATE FUNCTION reflect_submission_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'reflect_submission rows are insert-only (% is not allowed)', TG_OP;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER reflect_submission_guard BEFORE UPDATE OR DELETE ON reflect_submission
        FOR EACH ROW EXECUTE FUNCTION reflect_submission_guard()
    """)
    op.execute("""
        CREATE TRIGGER reflect_submission_no_truncate BEFORE TRUNCATE ON reflect_submission
        FOR EACH STATEMENT EXECUTE FUNCTION reflect_submission_guard()
    """)
    for trigger in ("reflect_submission_guard", "reflect_submission_no_truncate"):
        op.execute(f"ALTER TABLE reflect_submission ENABLE ALWAYS TRIGGER {trigger}")
    op.execute(
        "ALTER TABLE mental_model_refresh ADD COLUMN refreshed_by text"
        " CHECK (refreshed_by IN ('atlas', 'hindsight'))"
    )
    # History at its own time: the window never counts it as spent now.
    op.execute("""
        INSERT INTO provider_usage (provider, source_id, units, recorded_at)
        SELECT 'codex', 'mental_model_refresh:' || id::text, 1, requested_at
        FROM mental_model_refresh WHERE operation_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO provider_usage (provider, source_id, units, recorded_at)
        SELECT 'codex', 'replay_answer:' || replay_job_id::text || ':' || position::text, 1,
            answered_at
        FROM replay_answer
        ON CONFLICT DO NOTHING
    """)
    op.execute("REVOKE ALL ON reflect_submission FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON reflect_submission TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE mental_model_refresh DROP COLUMN refreshed_by")
    op.execute("DROP TABLE reflect_submission")
    op.execute("DROP FUNCTION reflect_submission_guard()")
    op.execute("ALTER TABLE research_answer DROP COLUMN exclude_mental_models")
    op.execute("ALTER TABLE research_answer DROP COLUMN budget")
