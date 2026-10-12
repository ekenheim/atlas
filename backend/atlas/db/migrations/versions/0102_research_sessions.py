"""Research sessions (beliefs ticket 08).

`research_session`: one run of a researcher on a question as of a time, a Claude session
(`claude`, opened and closed through the API) or the pipeline's argument plan (`pipeline`,
recorded in the transaction that stores its research card, `investigation_id`). It holds the
question, theme, seed companies, `as_of`, the model, the actor, when it started and finished,
its usage (JSON) and its card (the argument plan's card shape, JSON) with the card's markdown.
`fact.session_id`: the session a Fact was recorded in (`investigation_id` stays for the
pipeline).

Revision ID: 0102
Revises: 0101
"""

from alembic import op

revision = "0102"
down_revision = "0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE research_session (
            id uuid PRIMARY KEY,
            question text NOT NULL CHECK (btrim(question) <> ''),
            theme text NOT NULL CHECK (btrim(theme) <> ''),
            seed_company_ids uuid[] NOT NULL DEFAULT '{}',
            as_of timestamptz NOT NULL,
            kind text NOT NULL CHECK (kind IN ('claude', 'pipeline')),
            model text,
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            investigation_id uuid UNIQUE REFERENCES investigation (id),
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            usage jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(usage) = 'object'),
            card jsonb CHECK (jsonb_typeof(card) = 'object'),
            card_markdown text,
            CHECK ((kind = 'pipeline') = (investigation_id IS NOT NULL))
        )
    """)
    op.execute(
        "CREATE INDEX ix_research_session_theme ON research_session (theme, started_at DESC)"
    )
    op.execute("ALTER TABLE fact ADD COLUMN session_id uuid REFERENCES research_session (id)")
    op.execute(
        "CREATE INDEX ix_fact_session ON fact (session_id, created_at, assertion_id)"
        " WHERE session_id IS NOT NULL"
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON research_session TO atlas_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP INDEX ix_fact_session")
    op.execute("ALTER TABLE fact DROP COLUMN session_id")
    op.execute("DROP TABLE research_session")
