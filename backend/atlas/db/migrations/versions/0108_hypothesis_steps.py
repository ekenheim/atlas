"""A Hypothesis over Beliefs (atlas-beliefs ticket 14).

A Hypothesis is either an investigation's result (as before) or drafted from a theme's proven
Beliefs, a claude session's among them: `hypothesis.investigation_id` becomes nullable, and a
Belief-backed Hypothesis records its own basis instead: `question`, `as_of` (the cutoff its
Research Snapshot carries) and `session_ids` (the sessions whose Beliefs it was drafted from;
empty: the theme's). A CHECK keeps exactly one basis. The steps themselves live in the version's
content (JSON), so no other column changes.

Revision ID: 0108
Revises: 0107
"""

from alembic import op

revision = "0108"
down_revision = "0107"
branch_labels = None
depends_on = None


_TRIGGERS = "'assertion_reviewed', 'relationship_rejected', 'source_revised', 'counterevidence'"


def upgrade() -> None:
    op.execute("ALTER TABLE proposed_update DROP CONSTRAINT proposed_update_trigger_check")
    op.execute(
        "ALTER TABLE proposed_update ADD CONSTRAINT proposed_update_trigger_check"
        f" CHECK (trigger IN ({_TRIGGERS}, 'belief_changed'))"
    )
    op.execute("ALTER TABLE hypothesis ALTER COLUMN investigation_id DROP NOT NULL")
    op.execute("ALTER TABLE hypothesis ADD COLUMN question text")
    op.execute("ALTER TABLE hypothesis ADD COLUMN as_of timestamptz")
    op.execute("ALTER TABLE hypothesis ADD COLUMN session_ids uuid[] NOT NULL DEFAULT '{}'")
    op.execute("""
        ALTER TABLE hypothesis ADD CONSTRAINT hypothesis_one_basis CHECK (
            (investigation_id IS NOT NULL AND question IS NULL AND as_of IS NULL)
            OR (investigation_id IS NULL AND btrim(question) <> '' AND as_of IS NOT NULL)
        )
    """)


def downgrade() -> None:
    op.execute("DELETE FROM proposed_update WHERE trigger = 'belief_changed'")
    op.execute("ALTER TABLE proposed_update DROP CONSTRAINT proposed_update_trigger_check")
    op.execute(
        "ALTER TABLE proposed_update ADD CONSTRAINT proposed_update_trigger_check"
        f" CHECK (trigger IN ({_TRIGGERS}))"
    )
    op.execute("ALTER TABLE hypothesis DROP CONSTRAINT hypothesis_one_basis")
    op.execute("ALTER TABLE hypothesis DROP COLUMN session_ids")
    op.execute("ALTER TABLE hypothesis DROP COLUMN as_of")
    op.execute("ALTER TABLE hypothesis DROP COLUMN question")
    op.execute("ALTER TABLE hypothesis ALTER COLUMN investigation_id SET NOT NULL")
