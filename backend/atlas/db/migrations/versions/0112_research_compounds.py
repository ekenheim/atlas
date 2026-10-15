"""Research that compounds (atlas-beliefs ticket 26).

A session starts from what Atlas already holds, so three things are recorded that a restart
would lose:

- `belief.last_examined_at` / `last_examined_as_of` / `last_examined_outcome`: when a Skeptic or
  Researcher session last tested the Belief, the as-of time of that session (the Belief has been
  tested against everything public by then: the next test reads what came after) and what it
  found. They are the latest `belief_examination` row, kept on the Belief so a list can sort by
  staleness. `belief_examination` is insert-only: one row per examination.
- `belief_notice`: a notice beside a Belief's flags, `belief_confirmed` (a document newer than
  the Belief's as-of time supports its load-bearing Fact). Not a flag: it is no doubt, so it
  never blocks a publish or proposes an update. Like a flag it is insert-only but for being
  cleared once, by a judgement.
- `fact.same_span_as`: a Fact recorded on a span an earlier Fact of the same step already covers
  but with a materially different statement (the earlier Fact; not a duplicate, so a new row).
- `session_fact_reuse`: the record, on the session, of a Fact recorded again for a span an
  earlier Fact covered: the existing Fact was returned and no row was made. Insert-only.

Revision ID: 0112
Revises: 0111
"""

from alembic import op

revision = "0112"
down_revision = "0111"
branch_labels = None
depends_on = None

_OUTCOMES = "'confirmed', 'qualified', 'contradicted', 'nothing_new'"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE belief ADD COLUMN last_examined_at timestamptz,"
        " ADD COLUMN last_examined_as_of timestamptz,"
        f" ADD COLUMN last_examined_outcome text CHECK (last_examined_outcome IN ({_OUTCOMES})),"
        " ADD CONSTRAINT belief_examined_together CHECK ((last_examined_at IS NULL) ="
        " (last_examined_as_of IS NULL) AND (last_examined_at IS NULL) ="
        " (last_examined_outcome IS NULL))"
    )
    op.execute(f"""
        CREATE TABLE belief_examination (
            id uuid PRIMARY KEY,
            belief_id uuid NOT NULL REFERENCES belief (id),
            session_id uuid NOT NULL REFERENCES research_session (id),
            outcome text NOT NULL CHECK (outcome IN ({_OUTCOMES})),
            as_of timestamptz NOT NULL,
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            note text,
            at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_belief_examination_belief ON belief_examination (belief_id, at)")
    op.execute("""
        CREATE TABLE belief_notice (
            id uuid PRIMARY KEY,
            belief_id uuid NOT NULL REFERENCES belief (id),
            kind text NOT NULL CHECK (kind IN ('belief_confirmed')),
            ref_id uuid NOT NULL,
            detail text NOT NULL,
            raised_at timestamptz NOT NULL DEFAULT now(),
            cleared_by uuid REFERENCES belief_judgement (id)
        )
    """)
    op.execute("CREATE INDEX ix_belief_notice_belief ON belief_notice (belief_id, raised_at)")
    op.execute(
        "CREATE UNIQUE INDEX ux_belief_notice_open ON belief_notice (belief_id, kind, ref_id)"
        " WHERE cleared_by IS NULL"
    )
    op.execute("""
        CREATE TABLE session_fact_reuse (
            id uuid PRIMARY KEY,
            session_id uuid NOT NULL REFERENCES research_session (id),
            fact_id uuid NOT NULL REFERENCES fact (assertion_id),
            step text NOT NULL,
            statement text NOT NULL,
            span_start integer NOT NULL,
            span_end integer NOT NULL,
            at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_session_fact_reuse_session ON session_fact_reuse (session_id, at)")
    op.execute("ALTER TABLE fact ADD COLUMN same_span_as uuid REFERENCES fact (assertion_id)")
    for table in ("belief_examination", "belief_notice", "session_fact_reuse"):
        for kind, event in (("update", "UPDATE"), ("delete", "DELETE")):
            if table == "belief_notice" and kind == "update":
                continue
            name = f"{table}_no_{kind}"
            op.execute(
                f"CREATE TRIGGER {name} BEFORE {event} ON {table} FOR EACH ROW"
                " EXECUTE FUNCTION belief_reject_change()"
            )
            op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {name}")
    op.execute(
        "CREATE TRIGGER belief_notice_only_clears BEFORE UPDATE ON belief_notice FOR EACH ROW"
        " EXECUTE FUNCTION belief_flag_only_clears()"
    )
    op.execute("ALTER TABLE belief_notice ENABLE ALWAYS TRIGGER belief_notice_only_clears")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON belief_notice TO atlas_app;
                GRANT SELECT, INSERT ON belief_examination, session_fact_reuse TO atlas_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE fact DROP COLUMN same_span_as")
    op.execute("DROP TABLE session_fact_reuse")
    op.execute("DROP TABLE belief_notice")
    op.execute("DROP TABLE belief_examination")
    op.execute(
        "ALTER TABLE belief DROP CONSTRAINT belief_examined_together,"
        " DROP COLUMN last_examined_outcome, DROP COLUMN last_examined_as_of,"
        " DROP COLUMN last_examined_at"
    )
