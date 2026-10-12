"""Issues (beliefs ticket 04): the research frontier.

`issue`: a research question still to answer (`question`, `step` or `read`), with a theme,
priority, status (`active`, `complete`, `abandoned`, `invalid`), companies and the session that
produced it. `issue_edge`: `narrows` and `requires`, from the child to the parent, acyclic
(the service refuses a cycle). `issue_product`: the Beliefs (a plain uuid until Beliefs
exist) and Facts an Issue produced.

Revision ID: 0104
Revises: 0102
"""

from alembic import op

revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE issue (
            id uuid PRIMARY KEY,
            title text NOT NULL CHECK (btrim(title) <> ''),
            body text NOT NULL DEFAULT '',
            theme text NOT NULL CHECK (btrim(theme) <> ''),
            kind text NOT NULL CHECK (kind IN ('question', 'step', 'read')),
            priority integer NOT NULL DEFAULT 0,
            status text NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'complete', 'abandoned', 'invalid')),
            produced_by uuid REFERENCES research_session (id),
            company_ids uuid[] NOT NULL DEFAULT '{}',
            created_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            closed_at timestamptz
        )
    """)
    op.execute("CREATE INDEX ix_issue_theme ON issue (theme, status, created_at)")
    op.execute("""
        CREATE TABLE issue_edge (
            child_id uuid NOT NULL REFERENCES issue (id),
            parent_id uuid NOT NULL REFERENCES issue (id),
            kind text NOT NULL CHECK (kind IN ('narrows', 'requires')),
            actor text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (child_id, parent_id, kind),
            CHECK (child_id <> parent_id)
        )
    """)
    op.execute("CREATE INDEX ix_issue_edge_parent ON issue_edge (parent_id)")
    op.execute("""
        CREATE TABLE issue_product (
            id uuid PRIMARY KEY,
            issue_id uuid NOT NULL REFERENCES issue (id),
            belief_id uuid,
            fact_id uuid REFERENCES fact (assertion_id),
            actor text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((belief_id IS NULL) <> (fact_id IS NULL))
        )
    """)
    op.execute("CREATE INDEX ix_issue_product_issue ON issue_product (issue_id)")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON issue TO atlas_app;
                GRANT SELECT, INSERT ON issue_edge, issue_product TO atlas_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE issue_product")
    op.execute("DROP TABLE issue_edge")
    op.execute("DROP TABLE issue")
