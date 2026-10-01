"""Claim party basis and the folded offset source (memory-directed reading ticket 02).

- `claim.party_basis`: how an accepted Claim's quote identifies its parties: `named` (each by
  name, or the filer in the first person) or `filer` (the filer is the unnamed party of an
  impersonal sentence or slide bullet of its own document; `docs/decisions.md`, "The filer as
  the unnamed party"). Null for rejected Claims and for Claims recorded before 0052.
- `claim.offset_source` gains `folded`: the quote matched the passage only through the
  typographic fold (hyphens, quotation marks, spaces; one character to one character), and the
  Claim's and the Assertion's quote is the archived text at the span.

`claim` stays insert-only; adding the column touches no row. The downgrade refuses while any
Claim is `folded`: Claims are never rewritten or deleted.

Revision ID: 0052
Revises: 0051
"""

from alembic import op
from sqlalchemy import text

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE claim ADD COLUMN party_basis text CHECK (party_basis IN ('named', 'filer'))"
    )
    op.execute("ALTER TABLE claim DROP CONSTRAINT claim_offset_source_check")
    op.execute("""
        ALTER TABLE claim ADD CONSTRAINT claim_offset_source_check
            CHECK (offset_source IN ('model', 'located', 'folded'))
    """)


def downgrade() -> None:
    folded = (
        op.get_bind()
        .execute(text("SELECT count(*) FROM claim WHERE offset_source = 'folded'"))
        .scalar_one()
    )
    if folded:
        raise RuntimeError(
            f"refusing to downgrade: {folded} Claims were placed through the typographic fold,"
            " and Claims are never rewritten or deleted"
        )
    op.execute("ALTER TABLE claim DROP CONSTRAINT claim_offset_source_check")
    op.execute("""
        ALTER TABLE claim ADD CONSTRAINT claim_offset_source_check
            CHECK (offset_source IN ('model', 'located'))
    """)
    op.execute("ALTER TABLE claim DROP COLUMN party_basis")
