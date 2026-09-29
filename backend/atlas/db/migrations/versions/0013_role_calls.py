"""Role calls: each research role's LLM call within a run, and each attempt's usage.

- `role_call`: one per call of a role (Scout, Investigator, ...) in a run: the prompt's name,
  version and SHA-256, the model asked for, the request and the quoted retrieved data sent,
  and how it ended (`accepted` with its validated output; `quarantined`, whose outputs stay
  visible in its attempts but are never used; `failed`; `budget_exhausted`).
- `llm_call`: one per chat completion LiteLLM answered (at most two per role call: the call
  and one repair): the routed model (the response's `model` and the `x-litellm-model-id`
  deployment), tokens, the raw content and its validation errors. A run's usage is the sum
  of its `llm_call` rows, which is what the per-run token budget counts.

Revision ID: 0013
Revises: 0012 (re-chained at merge)
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE role_call (
            id uuid PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES run (id),
            role text NOT NULL CHECK (role <> ''),
            prompt_name text NOT NULL,
            prompt_version integer NOT NULL CHECK (prompt_version > 0),
            prompt_sha256 text NOT NULL CHECK (prompt_sha256 ~ '^[0-9a-f]{64}$'),
            model text NOT NULL,
            request jsonb NOT NULL,
            retrieved jsonb NOT NULL CHECK (jsonb_typeof(retrieved) = 'array'),
            status text NOT NULL DEFAULT 'running' CHECK (status IN
                ('running', 'accepted', 'quarantined', 'failed', 'budget_exhausted')),
            output jsonb,
            error text,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            CHECK ((status = 'accepted') = (output IS NOT NULL)),
            CHECK ((status = 'running') = (finished_at IS NULL))
        )
    """)
    op.execute("CREATE INDEX ix_role_call_run ON role_call (run_id, started_at)")
    op.execute("""
        CREATE TABLE llm_call (
            id uuid PRIMARY KEY,
            role_call_id uuid NOT NULL REFERENCES role_call (id),
            run_id uuid NOT NULL REFERENCES run (id),
            attempt smallint NOT NULL CHECK (attempt BETWEEN 1 AND 2),
            response_model text NOT NULL,
            model_id text,
            tokens_in bigint NOT NULL CHECK (tokens_in >= 0),
            tokens_out bigint NOT NULL CHECK (tokens_out >= 0),
            content text NOT NULL,
            validation_errors jsonb,
            called_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (role_call_id, attempt)
        )
    """)
    op.execute("CREATE INDEX ix_llm_call_run ON llm_call (run_id)")
    op.execute("REVOKE ALL ON role_call, llm_call FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON role_call TO atlas_app;
                GRANT SELECT, INSERT ON llm_call TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE llm_call")
    op.execute("DROP TABLE role_call")
