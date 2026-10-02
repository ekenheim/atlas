"""A role call cut off at its output cap is `truncated` (memory-quality ticket 16;
`docs/decisions.md`, "A cut-off answer is not a schema failure; the card never goes missing").

`role_call.status` accepts `truncated`: the model stopped at the output cap (the completion's
finish reason `length`, or the tokens it used reaching the cap) before its answer was valid,
so no repair was asked for. No existing row changes. The downgrade records every truncated
call as `quarantined` (its output was never used either) and restores the old constraint.

Revision ID: 0061
Revises: 0060 (re-chained at merge)
"""

from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

_STATUS_CHECK = """
    ALTER TABLE role_call ADD CONSTRAINT role_call_status_check
        CHECK (status IN ({statuses}))
"""
_STATUSES = "'running', 'accepted', 'quarantined', 'failed', 'budget_exhausted'"


def upgrade() -> None:
    op.execute("ALTER TABLE role_call DROP CONSTRAINT role_call_status_check")
    op.execute(_STATUS_CHECK.format(statuses=f"{_STATUSES}, 'truncated'"))


def downgrade() -> None:
    op.execute("ALTER TABLE role_call DROP CONSTRAINT role_call_status_check")
    op.execute("UPDATE role_call SET status = 'quarantined' WHERE status = 'truncated'")
    op.execute(_STATUS_CHECK.format(statuses=_STATUSES))
