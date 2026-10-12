"""Memory holds what was found (beliefs ticket 06).

`belief_memory`: the Hindsight document `belief:<id>` of a judged Belief in the research bank:
the judgement and status it was retained with, its operation and extractor, the facts and
memory IDs Hindsight stored and the state of the retain. One row per Belief and bank.

`belief_memory_replacement`: one row each time a Belief's document was deleted to retain it
again (a re-judgement, a supersession) or to take it out (judged `unproven` again), with the
memories the deleted document held, so a pointer or citation to an old memory reads as
*replaced*, not broken (`atlas.research.provenance`). Insert-only.

Revision ID: 0106
Revises: 0104 (the lead re-chains at integration)
"""

from alembic import op

revision = "0106"
down_revision = "0105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE belief_memory (
            id uuid PRIMARY KEY,
            belief_id uuid NOT NULL REFERENCES belief (id),
            bank_id text NOT NULL CHECK (btrim(bank_id) <> ''),
            hindsight_document_id text NOT NULL CHECK (btrim(hindsight_document_id) <> ''),
            state text NOT NULL
                CHECK (state IN ('pending', 'completed', 'zero_fact', 'failed', 'removed')),
            judgement_id uuid REFERENCES belief_judgement (id),
            belief_status text,
            operation_id text,
            extractor text,
            fact_count integer,
            memory_ids jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(memory_ids) = 'array'),
            error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (belief_id, bank_id),
            UNIQUE (bank_id, hindsight_document_id)
        )
    """)
    op.execute("""
        CREATE TABLE belief_memory_replacement (
            id uuid PRIMARY KEY,
            belief_id uuid NOT NULL REFERENCES belief (id),
            bank_id text NOT NULL CHECK (btrim(bank_id) <> ''),
            hindsight_document_id text NOT NULL CHECK (btrim(hindsight_document_id) <> ''),
            reason text NOT NULL CHECK (reason IN ('rejudged', 'superseded', 'unproven')),
            from_judgement_id uuid REFERENCES belief_judgement (id),
            replaced_memory_ids jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(replaced_memory_ids) = 'array'),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX belief_memory_replacement_belief ON belief_memory_replacement (belief_id)"
    )
    op.execute(
        "CREATE INDEX belief_memory_replacement_memories ON belief_memory_replacement"
        " USING gin (replaced_memory_ids jsonb_path_ops)"
    )
    op.execute("""
        CREATE FUNCTION belief_memory_replacement_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'belief_memory_replacement rows are insert-only (% is not allowed)',
                TG_OP;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER belief_memory_replacement_guard
        BEFORE UPDATE OR DELETE ON belief_memory_replacement
        FOR EACH ROW EXECUTE FUNCTION belief_memory_replacement_guard()
    """)
    op.execute("""
        CREATE TRIGGER belief_memory_replacement_no_truncate
        BEFORE TRUNCATE ON belief_memory_replacement
        FOR EACH STATEMENT EXECUTE FUNCTION belief_memory_replacement_guard()
    """)
    for trigger in ("belief_memory_replacement_guard", "belief_memory_replacement_no_truncate"):
        op.execute(f"ALTER TABLE belief_memory_replacement ENABLE ALWAYS TRIGGER {trigger}")
    op.execute("REVOKE ALL ON belief_memory, belief_memory_replacement FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON belief_memory TO atlas_app;
                GRANT SELECT, INSERT ON belief_memory_replacement TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE belief_memory_replacement")
    op.execute("DROP FUNCTION belief_memory_replacement_guard()")
    op.execute("DROP TABLE belief_memory")
