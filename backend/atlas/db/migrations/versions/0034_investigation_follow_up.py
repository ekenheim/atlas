"""An investigation's follow-up round: the researcher's one bounded push on an open question.

- `investigation_follow_up`: one per follow-up round (round 2; an investigation allows at most
  `max_rounds` rounds): the open question it pursues (one of the research card's), who asked
  and when, and the research card as it stood when the round began, so the round's own card
  never hides what the earlier one said. **Insert-only.**

Revision ID: 0034
Revises: 0033 (re-chained at merge)
"""

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE investigation_follow_up (
            investigation_id uuid NOT NULL REFERENCES investigation (id),
            round smallint NOT NULL CHECK (round >= 2),
            question text NOT NULL CHECK (btrim(question) <> ''),
            requested_by text NOT NULL CHECK (btrim(requested_by) <> ''),
            requested_at timestamptz NOT NULL DEFAULT now(),
            card_before jsonb NOT NULL CHECK (jsonb_typeof(card_before) = 'object'),
            PRIMARY KEY (investigation_id, round)
        )
    """)
    op.execute("""
        CREATE FUNCTION investigation_follow_up_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'investigation follow-ups are insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    triggers = {
        "investigation_follow_up_no_update": "BEFORE UPDATE ON investigation_follow_up"
        " FOR EACH ROW EXECUTE FUNCTION investigation_follow_up_reject_change()",
        "investigation_follow_up_no_delete": "BEFORE DELETE ON investigation_follow_up"
        " FOR EACH ROW EXECUTE FUNCTION investigation_follow_up_reject_change()",
        "investigation_follow_up_no_truncate": "BEFORE TRUNCATE ON investigation_follow_up"
        " FOR EACH STATEMENT EXECUTE FUNCTION investigation_follow_up_reject_change()",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE investigation_follow_up ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON investigation_follow_up FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON investigation_follow_up TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE investigation_follow_up")
    op.execute("DROP FUNCTION investigation_follow_up_reject_change()")
