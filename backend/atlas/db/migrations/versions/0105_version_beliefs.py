"""The Beliefs a published Hypothesis version rests on (atlas-beliefs ticket 03).

`hypothesis_version_belief`: recorded when a version is published, one row per active Belief
that cites an Assertion the version's findings rest on, with whether any such citation is
load-bearing and the Belief's judgement and confidence at that time. `hypothesis_belief_override`:
the owner's explicit override of the publish gate's Belief check, with the reason and the
Beliefs it let through. Both are written in the publishing transaction and never changed.

Revision ID: 0105
Revises: 0104
"""

from alembic import op

revision = "0105"
down_revision = "0104"
branch_labels = None
depends_on = None

_TABLES = ("hypothesis_version_belief", "hypothesis_belief_override")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE hypothesis_version_belief (
            hypothesis_version_id uuid NOT NULL REFERENCES hypothesis_version (id),
            belief_id uuid NOT NULL REFERENCES belief (id),
            load_bearing boolean NOT NULL,
            judgement text NOT NULL,
            confidence double precision NOT NULL,
            PRIMARY KEY (hypothesis_version_id, belief_id)
        )
    """)
    op.execute(
        "CREATE INDEX ix_hypothesis_version_belief_belief ON hypothesis_version_belief (belief_id)"
    )
    op.execute("""
        CREATE TABLE hypothesis_belief_override (
            hypothesis_version_id uuid PRIMARY KEY REFERENCES hypothesis_version (id),
            reason text NOT NULL CHECK (btrim(reason) <> ''),
            belief_ids uuid[] NOT NULL,
            actor text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE FUNCTION version_belief_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'version Beliefs are insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    for table in _TABLES:
        guards = {
            f"{table}_no_update": f"BEFORE UPDATE ON {table} FOR EACH ROW",
            f"{table}_no_delete": f"BEFORE DELETE ON {table} FOR EACH ROW",
            f"{table}_no_truncate": f"BEFORE TRUNCATE ON {table} FOR EACH STATEMENT",
        }
        for name, when in guards.items():
            op.execute(
                f"CREATE TRIGGER {name} {when} EXECUTE FUNCTION version_belief_reject_change()"
            )
            op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {name}")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION version_belief_reject_change()")
