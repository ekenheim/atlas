"""Investigation lead scores (pilot fix 02): why each lead was kept.

An investigation now keeps a discovery's top-ranked leads (atlas.discovery.ranking), not the
first ones found. Each `investigation_lead` row records its relevance `score`, the `reasons`
for it (a JSON array of strings), the `query` whose result scored best, and the version of
the ranking config that ranked it. Rows kept before ranking have NULLs (and `[]` reasons).

Revision ID: 0042
Revises: 0040
"""

from alembic import op

revision = "0042"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE investigation_lead
            ADD COLUMN score double precision,
            ADD COLUMN reasons jsonb NOT NULL DEFAULT '[]'
                CHECK (jsonb_typeof(reasons) = 'array'),
            ADD COLUMN query text,
            ADD COLUMN ranking_version integer
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE investigation_lead
            DROP COLUMN ranking_version,
            DROP COLUMN query,
            DROP COLUMN reasons,
            DROP COLUMN score
    """)
