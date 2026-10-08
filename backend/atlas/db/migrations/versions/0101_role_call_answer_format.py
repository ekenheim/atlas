"""A role call records the answer-format version it was sent (`docs/decisions.md`, "Roles: the
answer schema is in the prompt").

`role_call.answer_format_version`: 1 when the system message carried the role's response
schema in an "Answer format" section; 0 for every call recorded before (the schema went in
`response_format` only).

Revision ID: 0101
Revises: 0100
"""

from alembic import op

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE role_call ADD COLUMN answer_format_version smallint NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE role_call DROP COLUMN answer_format_version")
