"""Quota-window pacing: provider usage per rolling window, and ingest plans (ticket 27).

- `provider_usage`: one row per unit of subscription quota Atlas has seen spent, keyed by
  the row that records it: a Hindsight operation Atlas submitted (`codex`, 1 unit: one
  retain or reprocess batch) or an LLM call a role made (`minimax`, its tokens in + out).
  `recorded_at` is the pacing clock's time when the queue first counted it; the rolling
  window budgets (`atlas.jobs.budget`) sum the rows inside the window. Rows that existed
  before this revision are recorded at their own submission/call time, so history isn't
  counted as spent now.
- `ingest_plan`: what a first backfill ingest of a company was about to fetch (the
  discovered documents after the lookback and 8-K selection), with the count and an
  estimate of the retain operations it will submit, and its retain cap. Recorded before
  anything is fetched or retained; one per ingest job. Append-only.

Revision ID: 0028
Revises: 0027 (re-chained at merge)
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE provider_usage (
            provider text NOT NULL CHECK (provider IN ('codex', 'minimax')),
            source_id text NOT NULL CHECK (btrim(source_id) <> ''),
            units bigint NOT NULL CHECK (units >= 0),
            recorded_at timestamptz NOT NULL,
            PRIMARY KEY (provider, source_id)
        )
    """)
    op.execute("CREATE INDEX ix_provider_usage_window ON provider_usage (provider, recorded_at)")
    op.execute("""
        INSERT INTO provider_usage (provider, source_id, units, recorded_at)
        SELECT 'codex', id, 1, submitted_at FROM hindsight_operation
    """)
    op.execute("""
        INSERT INTO provider_usage (provider, source_id, units, recorded_at)
        SELECT 'minimax', id::text, tokens_in + tokens_out, called_at FROM llm_call
    """)
    op.execute("""
        CREATE TABLE ingest_plan (
            id uuid PRIMARY KEY,
            job_id uuid NOT NULL UNIQUE REFERENCES job (id),
            company_id uuid NOT NULL REFERENCES company (id),
            since timestamptz,
            forms jsonb CHECK (forms IS NULL OR jsonb_typeof(forms) = 'array'),
            documents jsonb NOT NULL CHECK (jsonb_typeof(documents) = 'array'),
            document_count integer NOT NULL CHECK (document_count >= 0),
            estimated_retain_operations integer NOT NULL
                CHECK (estimated_retain_operations BETWEEN 0 AND document_count),
            max_retains integer CHECK (max_retains >= 1),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_ingest_plan_company ON ingest_plan (company_id, created_at)")
    op.execute("REVOKE ALL ON provider_usage, ingest_plan FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON provider_usage, ingest_plan TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ingest_plan")
    op.execute("DROP TABLE provider_usage")
