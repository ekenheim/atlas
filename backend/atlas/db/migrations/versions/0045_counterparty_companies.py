"""Counterparty companies: a company known only so that a Relationship has its other end.

- `company.role`: `researched` (a universe company: from the theme config or a committed
  Candidate) or `counterparty` (created by entity resolution when an accepted Claim's quote
  names a company outside the universe; never ingested, never an investigation seed, in no
  theme). Every existing company is `researched`. A counterparty has no source path. Pilot
  fix 05, an owner-authorized domain-model extension (docs/decisions.md, "Counterparty
  companies", 2026-09-30).
- `company.counterparty_resolution`: how a counterparty was identified (the name as quoted,
  the registry that answered, its URL and time, and the whole resolution); kept when the
  company is later promoted to `researched`.
- `company.country` may be NULL for a counterparty: SEC gives a foreign registrant's country
  only as an EDGAR code, which Atlas doesn't map. A researched company always has one.

The downgrade refuses while any counterparty exists: Assertions and Relationships reference
them, and neither is ever deleted.

Revision ID: 0045
Revises: 0043
"""

from alembic import op
from sqlalchemy import text

revision = "0045"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE company
            ADD COLUMN role text NOT NULL DEFAULT 'researched'
                CONSTRAINT company_role_check CHECK (role IN ('researched', 'counterparty')),
            ADD COLUMN counterparty_resolution jsonb,
            ALTER COLUMN country DROP NOT NULL
    """)
    op.execute("""
        ALTER TABLE company
            ADD CONSTRAINT company_researched_has_country
                CHECK (role <> 'researched' OR country IS NOT NULL),
            ADD CONSTRAINT company_counterparty_has_no_source_path
                CHECK (role <> 'counterparty' OR source_path IS NULL),
            ADD CONSTRAINT company_counterparty_has_resolution
                CHECK (role <> 'counterparty' OR counterparty_resolution IS NOT NULL)
    """)


def downgrade() -> None:
    counterparties = (
        op.get_bind()
        .execute(text("SELECT count(*) FROM company WHERE role = 'counterparty'"))
        .scalar_one()
    )
    if counterparties:
        raise RuntimeError(
            f"{counterparties} counterparty companies exist; Assertions and Relationships"
            " reference them and are never deleted"
        )
    op.execute("""
        ALTER TABLE company
            DROP CONSTRAINT company_counterparty_has_resolution,
            DROP CONSTRAINT company_counterparty_has_no_source_path,
            DROP CONSTRAINT company_researched_has_country,
            ALTER COLUMN country SET NOT NULL,
            DROP COLUMN counterparty_resolution,
            DROP COLUMN role
    """)
