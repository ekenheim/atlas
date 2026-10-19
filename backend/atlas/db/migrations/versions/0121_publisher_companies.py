"""Publisher companies (Chokepoint Watch W9, the Watch's reach).

- `company.role` gains `publisher`: the publisher of a page that is no company's (a government
  or regulator notice), named from the site register's `publisher` for the site, so a
  `fetch_page` with no company can archive it and a session can quote it as a Fact. Like a
  counterparty it is never ingested, never a seed and in no theme; unlike one it has no
  registry resolution (`counterparty_resolution` stays NULL) and no source path.

The downgrade refuses while a publisher company exists (its Source Documents and Facts
reference it and are never deleted).

Revision ID: 0121
Revises: 0120
"""

from alembic import op
from sqlalchemy import text

revision = "0121"
down_revision = "0120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE company
            DROP CONSTRAINT company_role_check,
            ADD CONSTRAINT company_role_check
                CHECK (role IN ('researched', 'counterparty', 'publisher')),
            ADD CONSTRAINT company_publisher_has_no_source_path
                CHECK (role <> 'publisher' OR source_path IS NULL)
    """)


def downgrade() -> None:
    publishers = (
        op.get_bind()
        .execute(text("SELECT count(*) FROM company WHERE role = 'publisher'"))
        .scalar_one()
    )
    if publishers:
        raise RuntimeError(
            f"{publishers} publisher companies exist; their Source Documents and Facts"
            " reference them and are never deleted"
        )
    op.execute("""
        ALTER TABLE company
            DROP CONSTRAINT company_publisher_has_no_source_path,
            DROP CONSTRAINT company_role_check,
            ADD CONSTRAINT company_role_check CHECK (role IN ('researched', 'counterparty'))
    """)
