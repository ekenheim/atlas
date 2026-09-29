"""Fetch gate decisions: whether each exchange request was allowed, and by which gate.

- `fetch_gate_decision`: one per URL an exchange ingest asked the fetch gate about (the
  feed's search and each document; `atlas.sources.gate`). `allowed` records the terms
  decision and the robots.txt it relied on; `blocked` records which gate blocked it
  (`register`, `terms` or `robots`) and why: nothing was requested from a blocked URL.
  Append-only, like the rest of the ledger.
- `fetch_observation.gate_decision_id`: the `allowed` decision a fetch was made under (NULL
  for SEC EDGAR fetches, whose access terms are its fair-access policy). A trigger refuses
  an observation that names a `blocked` decision.

Revision ID: 0021
Revises: 0023 (re-chained at merge)
"""

from alembic import op

revision = "0021"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE fetch_gate_decision (
            id uuid PRIMARY KEY,
            job_id uuid REFERENCES job (id),
            company_id uuid REFERENCES company (id),
            provider text NOT NULL CHECK (btrim(provider) <> ''),
            purpose text NOT NULL CHECK (purpose IN ('discovery', 'document')),
            url text NOT NULL CHECK (url ~ '^https?://'),
            status text NOT NULL CHECK (status IN ('allowed', 'blocked')),
            blocked_by text CHECK (blocked_by IN ('register', 'terms', 'robots')),
            reason text NOT NULL CHECK (btrim(reason) <> ''),
            site text,
            terms jsonb CHECK (terms IS NULL OR jsonb_typeof(terms) = 'object'),
            robots jsonb CHECK (robots IS NULL OR jsonb_typeof(robots) = 'object'),
            user_agent_token text NOT NULL CHECK (btrim(user_agent_token) <> ''),
            decided_at timestamptz NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((status = 'blocked') = (blocked_by IS NOT NULL)),
            -- An allowed request passed the register, the terms and robots.txt.
            CHECK (status = 'blocked' OR (site IS NOT NULL AND terms IS NOT NULL
                                          AND robots IS NOT NULL))
        )
    """)
    op.execute(
        "CREATE INDEX fetch_gate_decision_company ON fetch_gate_decision"
        " (company_id, decided_at DESC)"
    )
    op.execute("CREATE INDEX fetch_gate_decision_job ON fetch_gate_decision (job_id)")
    for trigger, when in (("no_change", "UPDATE OR DELETE"), ("no_truncate", "TRUNCATE")):
        each = "ROW" if trigger == "no_change" else "STATEMENT"
        op.execute(f"""
            CREATE TRIGGER fetch_gate_decision_{trigger} BEFORE {when} ON fetch_gate_decision
            FOR EACH {each} EXECUTE FUNCTION ledger_reject_change()
        """)
        op.execute(
            f"ALTER TABLE fetch_gate_decision ENABLE ALWAYS TRIGGER fetch_gate_decision_{trigger}"
        )

    op.execute(
        "ALTER TABLE fetch_observation"
        " ADD COLUMN gate_decision_id uuid REFERENCES fetch_gate_decision (id)"
    )
    op.execute("""
        CREATE FUNCTION fetch_observation_check_gate() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.gate_decision_id IS NOT NULL AND NOT EXISTS (
                SELECT FROM fetch_gate_decision
                WHERE id = NEW.gate_decision_id AND status = 'allowed'
            ) THEN
                RAISE EXCEPTION 'a fetch observation needs an allowed gate decision';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER fetch_observation_gate BEFORE INSERT ON fetch_observation
        FOR EACH ROW EXECUTE FUNCTION fetch_observation_check_gate()
    """)
    op.execute("ALTER TABLE fetch_observation ENABLE ALWAYS TRIGGER fetch_observation_gate")

    op.execute("REVOKE ALL ON fetch_gate_decision FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON fetch_gate_decision TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER fetch_observation_gate ON fetch_observation")
    op.execute("DROP FUNCTION fetch_observation_check_gate()")
    op.execute("ALTER TABLE fetch_observation DROP COLUMN gate_decision_id")
    op.execute("DROP TABLE fetch_gate_decision")
