"""A consolidation can be switched off (`ATLAS_CONSOLIDATION_ENABLED`): its job is recorded as
skipped with the reason `consolidation_off` and no request is made.

`memory_consolidation.skip_reason` accepts `consolidation_off`. No row changes.

Revision ID: 0074
Revises: 0073
"""

from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None

_REASONS_BEFORE = "'nothing_retained', 'retains_pending'"
_REASONS = f"{_REASONS_BEFORE}, 'consolidation_off'"

# 0069's inline column check, under the name Postgres gives it.
_CONSTRAINT = "memory_consolidation_skip_reason_check"


def _replace(reasons: str) -> None:
    op.execute(f"ALTER TABLE memory_consolidation DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE memory_consolidation ADD CONSTRAINT {_CONSTRAINT}"
        f" CHECK (skip_reason IN ({reasons}))"
    )


def upgrade() -> None:
    _replace(_REASONS)


def downgrade() -> None:
    op.execute(
        "UPDATE memory_consolidation SET skip_reason = 'nothing_retained'"
        " WHERE skip_reason = 'consolidation_off'"
    )
    _replace(_REASONS_BEFORE)
