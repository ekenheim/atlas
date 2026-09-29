"""IQE's source path is the FCA National Storage Mechanism, not LSE RNS.

- `company.source_path`: `exchange:lse-rns` is replaced by `exchange:fca-nsm`. LSE RNS's
  robots.txt disallows `/en-gb/` and its disclaimer limits storage to personal use off any
  network, so Atlas never fetches it; IQE's regulated announcements come from the FCA's
  National Storage Mechanism instead (docs/decisions.md, 2026-09-29).

A company still on `exchange:lse-rns` (only IQE, seeded from the theme config) is moved to
`exchange:fca-nsm` here; the next `atlas companies seed` finds it already matching. Revision
0015 (which introduced the value) has not been deployed, so this touches local databases
only. The downgrade moves them back.

Revision ID: 0025
Revises: 0024 (re-chained at merge)
"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def _constraint(exchanges: str) -> None:
    op.execute("ALTER TABLE company DROP CONSTRAINT company_source_path_check")
    op.execute(f"""
        ALTER TABLE company ADD CONSTRAINT company_source_path_check
            CHECK (source_path ~ '^(sec|exchange:({exchanges}))$')
    """)


def upgrade() -> None:
    _constraint("hkex|lse-rns|fca-nsm|euronext")
    op.execute(
        "UPDATE company SET source_path = 'exchange:fca-nsm' WHERE source_path = 'exchange:lse-rns'"
    )
    _constraint("hkex|fca-nsm|euronext")


def downgrade() -> None:
    _constraint("hkex|lse-rns|fca-nsm|euronext")
    op.execute(
        "UPDATE company SET source_path = 'exchange:lse-rns' WHERE source_path = 'exchange:fca-nsm'"
    )
    _constraint("hkex|lse-rns|euronext")
