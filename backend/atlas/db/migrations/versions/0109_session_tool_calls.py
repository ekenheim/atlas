"""The Atlas MCP server's record of a session's tool calls (atlas-beliefs ticket 15).

`session_tool_call`: one row per tool call a research session made through the Atlas MCP
server (`atlas.mcp`): the tool, the arguments as received (JSON), the outcome (`ok`, `refused`
by Atlas's rules or the route's, or `error`) and when. Insert-only, so a session's usage is
Atlas's count and not the agent's; the session read (`tool_calls`) counts the rows.

Revision ID: 0109
Revises: 0108
"""

from alembic import op

revision = "0109"
down_revision = "0108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE session_tool_call (
            id uuid PRIMARY KEY,
            session_id uuid NOT NULL REFERENCES research_session (id),
            tool text NOT NULL CHECK (btrim(tool) <> ''),
            arguments jsonb NOT NULL CHECK (jsonb_typeof(arguments) = 'object'),
            outcome text NOT NULL CHECK (outcome IN ('ok', 'refused', 'error')),
            reason text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_session_tool_call_session ON session_tool_call (session_id, created_at)"
    )
    for kind, event in (("update", "UPDATE"), ("delete", "DELETE")):
        name = f"session_tool_call_no_{kind}"
        op.execute(
            f"CREATE TRIGGER {name} BEFORE {event} ON session_tool_call FOR EACH ROW"
            " EXECUTE FUNCTION belief_reject_change()"
        )
        op.execute(f"ALTER TABLE session_tool_call ENABLE ALWAYS TRIGGER {name}")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON session_tool_call TO atlas_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE session_tool_call")
