"""A reading pointer says which rule placed it, and where its fact's chunk lies.

Memory-quality ticket 08 (docs/decisions.md, "Chunk-exact pointers"). Four columns of
`reading_pointer`, set when the pointer is recorded:

- `placed_by`: `chunk` when the chunk its memory's fact was extracted from occurs verbatim in
  the pointed section, so the pointer's window is the one that span starts in; `match` when
  it does not (or the fact has no chunk), so the window is the one whose words match the
  memory's best, as every pointer was placed before. Existing rows take `match`, which is how
  they were placed.
- `chunk_id`: the Hindsight chunk of the fact (`<bank>_<document>_<index>`); null when the fact
  named none, and for pointers recorded before this. An identifier: the chunk's text is never
  stored.
- `chunk_char_start`, `chunk_char_end`: the chunk's span in the Source Version's parsed text
  (code points, [start, end)), within the pointed section; set exactly when `placed_by` is
  `chunk`.

The table stays insert-only; adding the columns updates no row by Atlas's hand (the default
fills `placed_by`). The downgrade refuses while a pointer was placed by its chunk.

Revision ID: 0065
Revises: 0066 (re-chained at merge)
"""

from alembic import op
from sqlalchemy import text

revision = "0065"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE reading_pointer
            ADD COLUMN placed_by text NOT NULL DEFAULT 'match'
                CONSTRAINT reading_pointer_placed_by_check
                CHECK (placed_by IN ('chunk', 'match')),
            ADD COLUMN chunk_id text,
            ADD COLUMN chunk_char_start integer,
            ADD COLUMN chunk_char_end integer,
            ADD CONSTRAINT reading_pointer_chunk_span_check CHECK (
                CASE WHEN placed_by = 'chunk'
                    THEN chunk_id IS NOT NULL AND chunk_char_start IS NOT NULL
                        AND chunk_char_end IS NOT NULL AND chunk_char_start >= 0
                        AND chunk_char_end > chunk_char_start
                    ELSE chunk_char_start IS NULL AND chunk_char_end IS NULL
                END
            )
    """)


def downgrade() -> None:
    placed = (
        op.get_bind()
        .execute(text("SELECT count(*) FROM reading_pointer WHERE placed_by = 'chunk'"))
        .scalar_one()
    )
    if placed:
        raise RuntimeError(
            f"{placed} reading pointers were placed by their fact's chunk: they are"
            " insert-only and would lose it; the downgrade is refused"
        )
    op.execute("""
        ALTER TABLE reading_pointer
            DROP CONSTRAINT reading_pointer_chunk_span_check,
            DROP COLUMN chunk_char_end,
            DROP COLUMN chunk_char_start,
            DROP COLUMN chunk_id,
            DROP COLUMN placed_by
    """)
