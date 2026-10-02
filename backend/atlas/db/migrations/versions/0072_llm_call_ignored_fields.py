"""An answer's unknown fields are ignored and recorded (pilot-fixes ticket 26;
`docs/decisions.md`, "Roles: an unknown field is ignored, a missing one repaired").

`llm_call.ignored_fields`: the fields of the attempt's answer that the role's response model
does not name, each as its path in the answer (`["claims", 0, "subject_name"]`). Code drops
them before validating; they are no validation error and ask for no repair. Every existing
row gets `[]`: before this revision such an answer was a validation error, which its
`validation_errors` still say.

Revision ID: 0072
Revises: 0068 (re-chained at merge)
"""

from alembic import op

revision = "0072"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE llm_call ADD COLUMN ignored_fields jsonb NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE llm_call DROP COLUMN ignored_fields")
