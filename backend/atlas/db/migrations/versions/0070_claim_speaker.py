"""The speaker of a transcript Claim (pilot-fixes ticket 22).

- `claim.speaker`: the speaker label of the transcript paragraph an accepted Claim quotes
  ("Alex Example (President and CEO, Example Photonics Inc)"), one of the filer's own people
  (`atlas.claims.speakers`; `docs/decisions.md`, "Claim checks: an analyst's words are not the
  company's"). Null for a rejected Claim, for a Claim on any other document and for Claims
  recorded before 0070.

`claim` stays insert-only; adding the column touches no row. The downgrade refuses while any
Claim has a speaker: Claims are never rewritten or deleted.

Revision ID: 0070
Revises: 0068
"""

from alembic import op
from sqlalchemy import text

revision = "0070"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE claim ADD COLUMN speaker text CHECK (btrim(speaker) <> '')")


def downgrade() -> None:
    spoken = (
        op.get_bind()
        .execute(text("SELECT count(*) FROM claim WHERE speaker IS NOT NULL"))
        .scalar_one()
    )
    if spoken:
        raise RuntimeError(
            f"refusing to downgrade: {spoken} Claims record their speaker, and Claims are never"
            " rewritten or deleted"
        )
    op.execute("ALTER TABLE claim DROP COLUMN speaker")
