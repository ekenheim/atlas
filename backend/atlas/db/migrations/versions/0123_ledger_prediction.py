"""The prediction record (atlas-record ticket 05; ADR 0004).

`ledger_prediction`: a prediction the first time its ID is seen in a stored ledger of a theme (or
of the council, theme `council`), as the ledger wrote it: the chokepoint, the date made, the
deadline, the text and the source type, and the edition it came from. Later editions never change
the row. `deadline_on` is the deadline as a day when it reads as one (`2027-02-28`, or a month,
`2027-03`, taken as its last day), else NULL: such a prediction never lapses. `UNIQUE (theme,
prediction_id)` makes "not seen before" one insert.

`ledger_prediction_settlement`: the first edition that carries a settlement for it (`met` or
`missed` with `settled_on`; the quote and URL as written), one at most. The state a prediction is
in (`open`, `lapsed`, `met`, `missed`) is derived on read from these and the deadline, never
stored.

Updates, deletes and truncation are refused by trigger, as for `ledger_edition`.

Revision ID: 0123
Revises: 0122
"""

from alembic import op

revision = "0123"
down_revision = "0122"
branch_labels = None
depends_on = None

_TABLES = ("ledger_prediction", "ledger_prediction_settlement")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ledger_prediction (
            id uuid PRIMARY KEY,
            theme text NOT NULL CHECK (theme ~ '^[a-z][a-z0-9-]{1,40}$'),
            prediction_id text NOT NULL CHECK (btrim(prediction_id) <> ''),
            chokepoint text,
            made text,
            deadline text,
            deadline_on date,
            text text NOT NULL CHECK (btrim(text) <> ''),
            source_type text,
            edition_id uuid NOT NULL REFERENCES ledger_edition (id),
            recorded_at timestamptz NOT NULL,
            UNIQUE (theme, prediction_id),
            CONSTRAINT ledger_prediction_day_needs_deadline
                CHECK (deadline_on IS NULL OR deadline IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX ix_ledger_prediction_due ON ledger_prediction (deadline_on, theme)")
    op.execute("""
        CREATE TABLE ledger_prediction_settlement (
            id uuid PRIMARY KEY,
            prediction_id uuid NOT NULL UNIQUE REFERENCES ledger_prediction (id),
            edition_id uuid NOT NULL REFERENCES ledger_edition (id),
            state text NOT NULL CHECK (state IN ('met', 'missed')),
            settled_on text NOT NULL CHECK (btrim(settled_on) <> ''),
            quote text,
            url text,
            recorded_at timestamptz NOT NULL
        )
    """)
    for table in _TABLES:
        for event, level, name in (
            ("UPDATE", "ROW", "update"),
            ("DELETE", "ROW", "delete"),
            ("TRUNCATE", "STATEMENT", "truncate"),
        ):
            op.execute(
                f"CREATE TRIGGER {table}_no_{name} BEFORE {event} ON {table}"
                f" FOR EACH {level} EXECUTE FUNCTION belief_reject_change()"
            )
            op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_no_{name}")
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                    GRANT SELECT, INSERT ON {table} TO atlas_app;
                END IF;
            END $$
        """)


def downgrade() -> None:
    op.execute("DROP TABLE ledger_prediction_settlement")
    op.execute("DROP TABLE ledger_prediction")
