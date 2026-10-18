"""The Chokepoint Watch's board and run record (Chokepoint Watch ticket W1).

`chokepoint`: one candidate bottleneck (theme, who made it); its fields never change. A theme
is a slug. `created_by_run` and an event's `run_id` refer to the `run` table (the pipeline's run
record), not to a watch run.
`chokepoint_event`: every change to it (what changed, why, the evidence, the session), insert-only;
the current state is the fold of the events (`atlas.chokepoints.fold`). `watch_run`: one run of the
Watch (the memo, counts, tool calls), insert-only. Nothing is deleted: a killed chokepoint stays
listed (`docs/decisions.md`, "The board is the fold of its events").

Revision ID: 0118
Revises: 0117
"""

from alembic import op

revision = "0118"
down_revision = "0117"
branch_labels = None
depends_on = None

_TABLES = ("chokepoint", "chokepoint_event", "watch_run")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE chokepoint (
            id uuid PRIMARY KEY,
            theme text NOT NULL CHECK (theme ~ '^[a-z][a-z0-9-]{1,40}$'),
            created_at timestamptz NOT NULL,
            created_by_session uuid REFERENCES research_session (id),
            created_by_run uuid REFERENCES run (id)
        )
    """)
    op.execute("CREATE INDEX ix_chokepoint_theme ON chokepoint (theme, created_at)")
    op.execute("""
        CREATE TABLE chokepoint_event (
            id uuid PRIMARY KEY,
            seq bigint GENERATED ALWAYS AS IDENTITY,
            chokepoint_id uuid NOT NULL REFERENCES chokepoint (id),
            at timestamptz NOT NULL,
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            session_id uuid REFERENCES research_session (id),
            run_id uuid REFERENCES run (id),
            kind text NOT NULL
                CHECK (kind IN ('created', 'field_set', 'step_set', 'status_set', 'note')),
            payload jsonb NOT NULL,
            reason text
        )
    """)
    op.execute("CREATE INDEX ix_chokepoint_event ON chokepoint_event (chokepoint_id, seq)")
    op.execute("""
        CREATE TABLE watch_run (
            id uuid PRIMARY KEY,
            theme text NOT NULL CHECK (theme ~ '^[a-z][a-z0-9-]{1,40}$'),
            run_date date NOT NULL,
            mode text NOT NULL CHECK (mode IN ('architect', 'delta')),
            memo text NOT NULL CHECK (btrim(memo) <> ''),
            counts jsonb NOT NULL DEFAULT '{}'::jsonb,
            tool_calls integer NOT NULL DEFAULT 0 CHECK (tool_calls >= 0),
            cost_usd numeric CHECK (cost_usd >= 0),
            tokens bigint CHECK (tokens >= 0),
            session_id uuid REFERENCES research_session (id),
            created_at timestamptz NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_watch_run ON watch_run (theme, run_date, created_at)")
    for table in _TABLES:
        for kind, event in (("update", "UPDATE"), ("delete", "DELETE")):
            name = f"{table}_no_{kind}"
            op.execute(
                f"CREATE TRIGGER {name} BEFORE {event} ON {table}"
                " FOR EACH ROW EXECUTE FUNCTION belief_reject_change()"
            )
            op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {name}")
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}"
            " FOR EACH STATEMENT EXECUTE FUNCTION belief_reject_change()"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_no_truncate")
    op.execute("REVOKE ALL ON chokepoint, chokepoint_event, watch_run FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON chokepoint, chokepoint_event, watch_run TO atlas_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE watch_run")
    op.execute("DROP TABLE chokepoint_event")
    op.execute("DROP TABLE chokepoint")
