"""The rewrite check's findings (atlas-record ticket 02; ADR 0004).

`ledger_rewrite`: one difference between an edition and the same theme's previous parsed
edition, found when the edition was stored (`edition_id`, `previous_edition_id`), insert-only.
`kind` is what changed (`prediction_changed`, `prediction_removed`, `prediction_unsettled`,
`chokepoint_vanished`, `id_reused`, `date_moved_later`, `edition_not_increasing`), `subject_id`
the prediction, chokepoint, board item or contradiction it is about (the theme's slug for an
edition number), `field` the field that differs when one does, and `before` and `after` the
values (JSONB; `after` is NULL when the thing is gone). One finding per edition, kind, subject
and field. Updates, deletes and truncation are refused by trigger, as for `ledger_edition`.

Revision ID: 0123
Revises: 0122
"""

from alembic import op

revision = "0123"
down_revision = "0122"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ledger_rewrite (
            id uuid PRIMARY KEY,
            seq bigint GENERATED ALWAYS AS IDENTITY,
            edition_id uuid NOT NULL REFERENCES ledger_edition (id),
            previous_edition_id uuid NOT NULL REFERENCES ledger_edition (id),
            kind text NOT NULL CHECK (kind IN (
                'prediction_changed', 'prediction_removed', 'prediction_unsettled',
                'chokepoint_vanished', 'id_reused', 'date_moved_later',
                'edition_not_increasing')),
            subject_id text NOT NULL CHECK (btrim(subject_id) <> ''),
            field text CHECK (field IS NULL OR btrim(field) <> ''),
            before jsonb,
            after jsonb,
            found_at timestamptz NOT NULL,
            CONSTRAINT ledger_rewrite_not_itself CHECK (edition_id <> previous_edition_id)
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX ux_ledger_rewrite_finding ON ledger_rewrite"
        " (edition_id, kind, subject_id, coalesce(field, ''))"
    )
    op.execute("CREATE INDEX ix_ledger_rewrite_found ON ledger_rewrite (found_at, seq)")
    op.execute(
        "CREATE TRIGGER ledger_rewrite_no_update BEFORE UPDATE ON ledger_rewrite"
        " FOR EACH ROW EXECUTE FUNCTION belief_reject_change()"
    )
    op.execute("ALTER TABLE ledger_rewrite ENABLE ALWAYS TRIGGER ledger_rewrite_no_update")
    op.execute(
        "CREATE TRIGGER ledger_rewrite_no_delete BEFORE DELETE ON ledger_rewrite"
        " FOR EACH ROW EXECUTE FUNCTION belief_reject_change()"
    )
    op.execute("ALTER TABLE ledger_rewrite ENABLE ALWAYS TRIGGER ledger_rewrite_no_delete")
    op.execute(
        "CREATE TRIGGER ledger_rewrite_no_truncate BEFORE TRUNCATE ON ledger_rewrite"
        " FOR EACH STATEMENT EXECUTE FUNCTION belief_reject_change()"
    )
    op.execute("ALTER TABLE ledger_rewrite ENABLE ALWAYS TRIGGER ledger_rewrite_no_truncate")
    op.execute("REVOKE ALL ON ledger_rewrite FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON ledger_rewrite TO atlas_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ledger_rewrite")
