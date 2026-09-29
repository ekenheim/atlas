"""Claim offset source: where an accepted (or later-checked) Claim's span came from.

- `claim.offset_source`: `model` when the quote was exactly at the Investigator's offsets,
  `located` when Atlas found it as the one exact occurrence in the passage (owner decision
  2026-09-29, "Claim quotes are located, not trusted"); null when the quote was never placed
  (the Claim was rejected before or at the span check) and for Claims recorded before 0024.
  `claim` stays insert-only; adding the column touches no row.

Revision ID: 0024
Revises: 0023
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE claim ADD COLUMN offset_source text"
        " CHECK (offset_source IN ('model', 'located'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE claim DROP COLUMN offset_source")
