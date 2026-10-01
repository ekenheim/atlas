"""Reading pointers: what Memory returned to an investigation's recalls, kept as an index.

Memory-directed reading ticket 01 (docs/decisions.md, "Memory as the reading index"):

- `reading_pointer`: one row per recalled memory and Source Version section it resolved to,
  for one query of one investigation task (the Scout's: the round's question, `query_index`
  0, and each of its queries, `query_index` = the query's position, with its
  `discovery_query_id`). It records the recall's rank, the memory's ID, type and text as
  Hindsight returned them, the Source Version, the section's anchor, heading and offsets, the
  company, the version's `available_at` the as-of check read, and the citation state (only
  `resolved` citations make pointers). **Insert-only**: triggers refuse UPDATE, DELETE and
  TRUNCATE.

A pointer is Memory used as an index: never Evidence, never quoted.

Revision ID: 0051
Revises: 0050
"""

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE reading_pointer (
            id uuid PRIMARY KEY,
            investigation_id uuid NOT NULL REFERENCES investigation (id),
            round smallint NOT NULL CHECK (round >= 1),
            task_id uuid NOT NULL REFERENCES investigation_task (id),
            -- 0: the round's question; n: the task's nth query (the Scout's, by position).
            query_index smallint NOT NULL CHECK (query_index >= 0),
            query text NOT NULL CHECK (btrim(query) <> ''),
            discovery_query_id uuid REFERENCES discovery_query (id),
            -- The memory's place in the recall's results, from 1.
            rank integer NOT NULL CHECK (rank >= 1),
            memory_id text NOT NULL CHECK (btrim(memory_id) <> ''),
            memory_type text NOT NULL CHECK (btrim(memory_type) <> ''),
            memory_text text NOT NULL,
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            section_anchor text NOT NULL CHECK (btrim(section_anchor) <> ''),
            section_heading text,
            -- Character offsets into the Source Version's parsed text: [start, end).
            section_char_start integer NOT NULL CHECK (section_char_start >= 0),
            section_char_end integer NOT NULL,
            company_id uuid REFERENCES company (id),
            available_at timestamptz NOT NULL,
            citation_state text NOT NULL CHECK (citation_state = 'resolved'),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (task_id, query_index, rank, source_version_id, section_anchor),
            CHECK (section_char_end > section_char_start)
        )
    """)
    op.execute("""
        CREATE INDEX ix_reading_pointer_investigation
            ON reading_pointer (investigation_id, round, query_index, rank)
    """)
    op.execute("""
        CREATE FUNCTION reading_pointer_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'reading pointers are insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    triggers = {
        "reading_pointer_no_change": "BEFORE UPDATE OR DELETE ON reading_pointer FOR EACH ROW"
        " EXECUTE FUNCTION reading_pointer_reject_change()",
        "reading_pointer_no_truncate": "BEFORE TRUNCATE ON reading_pointer FOR EACH STATEMENT"
        " EXECUTE FUNCTION reading_pointer_reject_change()",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE reading_pointer ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON reading_pointer FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON reading_pointer TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE reading_pointer")
    op.execute("DROP FUNCTION reading_pointer_reject_change()")
