"""Isolated research sessions (atlas-beliefs ticket 29a, the early-call scorecard).

`research_session.isolated`: a session opened `isolated` starts from nothing and leaves nothing
behind for others to find, so a replay of an old as-of date cannot be handed what later sessions
chose with hindsight. Atlas enforces it, not the prompt: `prior_work` returns nothing to it, a
Fact it records is never matched with a standing one (no reuse), `recall` of the conclusions
bank, `list_beliefs` and `get_belief` are refused, and a Belief it proposed cannot be judged
(`isolated_session_belief`), so it makes no call and never reaches the conclusions bank
(`docs/decisions.md`, "Isolated sessions for the scorecard"). Default false: every earlier
session, and every session opened without the flag, behaves as before.

Revision ID: 0116
Revises: 0115
"""

from alembic import op

revision = "0116"
down_revision = "0115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE research_session ADD COLUMN isolated boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE research_session DROP COLUMN isolated")
