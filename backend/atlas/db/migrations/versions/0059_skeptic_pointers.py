"""The Skeptic's reading pointers: which bear-checklist item and company a query was.

Memory-directed reading ticket 07 (docs/decisions.md, "The Skeptic reads where Memory points").
The Skeptic's task asks Memory one query per bear-checklist item for each company the accepted
Claims name, and what resolves is stored in `reading_pointer` like the Scout's. Three columns
say which query a pointer's was:

- `query_kind`: `scout` (the round's question, `query_index` 0, or the Scout's nth query) or
  `bear_checklist` (a Skeptic task's query). Rows recorded before this are the Scout's.
- `checklist_item`, `query_company_id`: a bear-checklist query's item and the company it asks
  about (not the company the pointer leads to, which stays `company_id`); both null for a
  Scout's query. A bear-checklist query's `query_index` is its position among its task's
  queries, from 1 (companies in order, each in checklist order).

The table stays insert-only; adding the columns touches no row (the default is a constant).
The downgrade refuses while a bear-checklist pointer exists: pointers are never deleted.

Revision ID: 0059
Revises: 0058 (re-chained at merge)
"""

from alembic import op
from sqlalchemy import text

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE reading_pointer
            ADD COLUMN query_kind text NOT NULL DEFAULT 'scout'
                CONSTRAINT reading_pointer_query_kind_check
                CHECK (query_kind IN ('scout', 'bear_checklist')),
            ADD COLUMN checklist_item text,
            ADD COLUMN query_company_id uuid REFERENCES company (id),
            ADD CONSTRAINT reading_pointer_bear_checklist_query CHECK (
                (query_kind = 'bear_checklist') = (checklist_item IS NOT NULL)
                AND (query_kind = 'bear_checklist') = (query_company_id IS NOT NULL)
                AND (query_kind <> 'bear_checklist' OR query_index >= 1)
            )
    """)


def downgrade() -> None:
    recorded = (
        op.get_bind()
        .execute(text("SELECT count(*) FROM reading_pointer WHERE query_kind = 'bear_checklist'"))
        .scalar_one()
    )
    if recorded:
        raise RuntimeError(
            f"{recorded} reading pointers of a Skeptic's bear-checklist queries exist: they"
            " are insert-only and would lose what their query was; the downgrade is refused"
        )
    op.execute("""
        ALTER TABLE reading_pointer
            DROP CONSTRAINT reading_pointer_bear_checklist_query,
            DROP COLUMN query_company_id,
            DROP COLUMN checklist_item,
            DROP COLUMN query_kind
    """)
