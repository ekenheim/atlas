"""The company budget of an investigation (memory-directed reading ticket 06).

An investigation reads the companies its reading pointers name beside its seeds, while its
company budget has room: `investigation.max_companies` Investigators a round, the seeds
counted (atlas.investigations.companies). It is a per-run budget like `max_leads` and
`max_documents`: the request may lower the configured default
(`ATLAS_INVESTIGATION_MAX_COMPANIES`, 6), and the Scout's task reads it later, in a worker,
so it is stored with the investigation.

Investigations recorded before this take the default, 6. Their rounds are over or under way
and their plans are not changed by it: the plan grows only at the moment a round's Scout
succeeds.

No change to `investigation_task`: an added Investigator is a task row like a seed's (its
position after the seeds', the later tasks moved down), and `investigation_premise` already
allows a company premise for any company.

Revision ID: 0058
Revises: 0055 (re-chained at merge)
"""

from alembic import op

revision = "0058"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE investigation
            ADD COLUMN max_companies smallint NOT NULL DEFAULT 6
                CHECK (max_companies BETWEEN 1 AND 25)
    """)
    # Like the other budgets, every new investigation states its own.
    op.execute("ALTER TABLE investigation ALTER COLUMN max_companies DROP DEFAULT")


def downgrade() -> None:
    op.execute("ALTER TABLE investigation DROP COLUMN max_companies")
