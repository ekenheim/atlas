"""A skipped EDGAR full-text search (memory-directed reading, ticket 04).

A query's filing phrase is searched in EDGAR only when it is specific: at least two words, or
a product or layer term of the lead-ranking config (atlas.discovery.edgar_fts). Otherwise the
query's `edgar_search` row is recorded with status `skipped` and `skip_reason` (why), and no
request is made. A skipped search was never searched, so it has no `searched_at`.

The downgrade refuses while a skipped search exists: its reason would be lost.

Revision ID: 0054
Revises: 0050 (re-chained at merge)
"""

from alembic import op
from sqlalchemy import text

revision = "0054"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0050's unnamed checks: the status values, and `(status = 'pending') = (searched_at IS
    # NULL)` (the second table-level check, so `edgar_search_check1`).
    op.execute("ALTER TABLE edgar_search DROP CONSTRAINT edgar_search_status_check")
    op.execute("ALTER TABLE edgar_search DROP CONSTRAINT edgar_search_check1")
    op.execute("ALTER TABLE edgar_search ADD COLUMN skip_reason text")
    op.execute("""
        ALTER TABLE edgar_search
            ADD CONSTRAINT edgar_search_status_check
                CHECK (status IN ('pending', 'searched', 'failed', 'skipped')),
            ADD CONSTRAINT edgar_search_searched_at
                CHECK ((status IN ('pending', 'skipped')) = (searched_at IS NULL)),
            ADD CONSTRAINT edgar_search_skip_reason
                CHECK ((status = 'skipped') = (skip_reason IS NOT NULL)
                    AND btrim(skip_reason) <> '')
    """)


def downgrade() -> None:
    skipped = (
        op.get_bind()
        .execute(text("SELECT count(*) FROM edgar_search WHERE status = 'skipped'"))
        .scalar_one()
    )
    if skipped:
        raise RuntimeError(
            f"refusing to downgrade: {skipped} skipped EDGAR searches exist, and their reasons"
            " would be lost"
        )
    op.execute("""
        ALTER TABLE edgar_search
            DROP CONSTRAINT edgar_search_skip_reason,
            DROP CONSTRAINT edgar_search_searched_at,
            DROP CONSTRAINT edgar_search_status_check
    """)
    op.execute("ALTER TABLE edgar_search DROP COLUMN skip_reason")
    op.execute("""
        ALTER TABLE edgar_search
            ADD CONSTRAINT edgar_search_status_check
                CHECK (status IN ('pending', 'searched', 'failed')),
            ADD CONSTRAINT edgar_search_check1
                CHECK ((status = 'pending') = (searched_at IS NULL))
    """)
