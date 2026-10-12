"""The conclusions bank (beliefs ticket 12).

A Belief's document moved from the research bank to the conclusions bank is deleted from the
first and recorded as a replacement with the reason `moved_bank`.

Revision ID: 0107
Revises: 0106 (the lead re-chains at integration)
"""

from alembic import op

revision = "0107"
down_revision = "0106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE belief_memory_replacement"
        " DROP CONSTRAINT belief_memory_replacement_reason_check"
    )
    op.execute(
        "ALTER TABLE belief_memory_replacement"
        " ADD CONSTRAINT belief_memory_replacement_reason_check"
        " CHECK (reason IN ('rejudged', 'superseded', 'unproven', 'moved_bank'))"
    )


def downgrade() -> None:
    # Fails while a `moved_bank` row exists: the table is insert-only, so none is rewritten.
    op.execute(
        "ALTER TABLE belief_memory_replacement"
        " DROP CONSTRAINT belief_memory_replacement_reason_check"
    )
    op.execute(
        "ALTER TABLE belief_memory_replacement"
        " ADD CONSTRAINT belief_memory_replacement_reason_check"
        " CHECK (reason IN ('rejudged', 'superseded', 'unproven'))"
    )
