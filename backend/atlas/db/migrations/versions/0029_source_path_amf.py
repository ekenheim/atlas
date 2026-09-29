"""Soitec's source path is the AMF info-financière API, not Euronext.

- `company.source_path`: `exchange:euronext` is replaced by `exchange:amf`. Euronext's terms
  prohibit robots and systematic retrieval, so Atlas never fetches it; Soitec's regulated
  information comes from the AMF's open info-financière API instead (docs/decisions.md,
  "AMF info-financière for Soitec", 2026-09-29).

A company still on `exchange:euronext` (only Soitec, seeded from the theme config) is moved
to `exchange:amf` here; the next `atlas companies seed` finds it already matching. No
Euronext ingest ever ran (no adapter existed), so nothing else refers to the old value. The
downgrade moves them back.

Revision ID: 0029
Revises: 0028 (re-chained at merge)
"""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def _constraint(exchanges: str) -> None:
    op.execute("ALTER TABLE company DROP CONSTRAINT company_source_path_check")
    op.execute(f"""
        ALTER TABLE company ADD CONSTRAINT company_source_path_check
            CHECK (source_path ~ '^(sec|exchange:({exchanges}))$')
    """)


def upgrade() -> None:
    _constraint("hkex|fca-nsm|euronext|amf")
    op.execute(
        "UPDATE company SET source_path = 'exchange:amf' WHERE source_path = 'exchange:euronext'"
    )
    _constraint("hkex|fca-nsm|amf")


def downgrade() -> None:
    _constraint("hkex|fca-nsm|euronext|amf")
    op.execute(
        "UPDATE company SET source_path = 'exchange:euronext' WHERE source_path = 'exchange:amf'"
    )
    _constraint("hkex|fca-nsm|euronext")
