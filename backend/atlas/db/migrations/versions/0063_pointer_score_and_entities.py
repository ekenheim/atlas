"""A reading pointer keeps its recall's score and its memory's entity names.

Memory-quality ticket 07 (docs/decisions.md, "Recall as a reading index"). Two columns of
`reading_pointer`, set when the pointer is recorded:

- `score`: the final score Hindsight gave the memory in the recall that made the pointer
  (`scores.final`; relative to that recall only, and it can exceed 1). Null when Hindsight
  gave none, and for every pointer recorded before this.
- `entity_names`: the canonical names of the entities the memory names, as the recall gave
  them (empty when it named none). Null for pointers recorded before this.

The table stays insert-only; adding nullable columns touches no row. The downgrade refuses
while a pointer carries either: pointers are never changed or deleted.

Revision ID: 0063
Revises: 0061 (re-chained at merge)
"""

from alembic import op
from sqlalchemy import text

revision = "0063"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE reading_pointer
            ADD COLUMN score double precision,
            ADD COLUMN entity_names text[]
    """)


def downgrade() -> None:
    recorded = (
        op.get_bind()
        .execute(
            text(
                "SELECT count(*) FROM reading_pointer"
                " WHERE score IS NOT NULL OR entity_names IS NOT NULL"
            )
        )
        .scalar_one()
    )
    if recorded:
        raise RuntimeError(
            f"{recorded} reading pointers carry a recall score or entity names: they are"
            " insert-only and would lose them; the downgrade is refused"
        )
    op.execute("""
        ALTER TABLE reading_pointer
            DROP COLUMN entity_names,
            DROP COLUMN score
    """)
