"""Evaluation runs and their per-case results (ticket 25; build plan §5.8 `evaluation`).

- `evaluation_run`: one `atlas evaluate` invocation: its mode (`fake`: scripted model answers,
  scoring the pipeline's deterministic parts; `live`: the real model), the model asked, the
  code version, the cases requested and the pass count once finished.
- `evaluation`: **insert-only**: one row per case in a run: the case ID and the SHA-256 of
  the exact case file scored, its category, the temporal convention used, pass/fail, the
  score per metric, each gold check with what was observed, the predicted output (Claims,
  Relationships, families, figures, the investigation) and any error.

Revision ID: 0033
Revises: 0032 (the lead re-chains it after 0032 at merge)
"""

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE evaluation_run (
            id uuid PRIMARY KEY,
            mode text NOT NULL CHECK (mode IN ('fake', 'live')),
            status text NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'completed', 'failed')),
            model text NOT NULL,
            code_version text NOT NULL,
            gold_manifest_sha256 text NOT NULL,
            case_ids text[] NOT NULL,
            cases_total integer NOT NULL DEFAULT 0 CHECK (cases_total >= 0),
            cases_passed integer NOT NULL DEFAULT 0
                CHECK (cases_passed BETWEEN 0 AND cases_total),
            actor text NOT NULL,
            error text,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            CHECK ((status = 'running') = (finished_at IS NULL))
        )
    """)
    op.execute("""
        CREATE TABLE evaluation (
            id uuid PRIMARY KEY,
            evaluation_run_id uuid NOT NULL REFERENCES evaluation_run (id),
            case_id text NOT NULL CHECK (case_id ~ '^EV-[A-Z]{3}-[0-9]{3}$'),
            case_sha256 text NOT NULL CHECK (case_sha256 ~ '^[0-9a-f]{64}$'),
            category text NOT NULL,
            title text NOT NULL,
            temporal_convention text
                CHECK (temporal_convention IN ('available_at', 'available_and_ingested')),
            passed boolean NOT NULL,
            scores jsonb NOT NULL CHECK (jsonb_typeof(scores) = 'object'),
            checks jsonb NOT NULL CHECK (jsonb_typeof(checks) = 'array'),
            predicted jsonb NOT NULL CHECK (jsonb_typeof(predicted) = 'object'),
            error text,
            duration_ms integer NOT NULL CHECK (duration_ms >= 0),
            evaluated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (evaluation_run_id, case_id)
        )
    """)
    op.execute("CREATE INDEX evaluation_case_idx ON evaluation (case_id, evaluated_at)")
    op.execute("""
        CREATE FUNCTION evaluation_insert_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'evaluation rows are insert-only';
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER evaluation_insert_only BEFORE UPDATE OR DELETE ON evaluation
        FOR EACH ROW EXECUTE FUNCTION evaluation_insert_only()
    """)


def downgrade() -> None:
    op.execute("DROP TABLE evaluation")
    op.execute("DROP FUNCTION evaluation_insert_only()")
    op.execute("DROP TABLE evaluation_run")
