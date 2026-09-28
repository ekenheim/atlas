"""Retention into memory: tracked Hindsight operations and the ledger-to-memory mapping
(spec Part B "Schema"; ADR-0001; docs/data-model.md §3.2-3.3).

- `hindsight_operation`: one row per asynchronous Hindsight operation Atlas submitted (a
  Source Version's retain batch, or a zero-fact reprocess). Its `status` is what Hindsight
  last reported and is the only basis for an outcome; failures keep their error.
- `memory_document`: one row per section of a Source Version in a bank: its anchor and
  character offsets into the parsed text, the Hindsight `document_id`
  (`srcv:<source_version_uuid>:<section-anchor>`), the operation that last retained it, its
  retain state and fact count, and the bank template version it was retained under. A
  Source Version whose raw bytes are already retained gets `linked` rows instead.

Invariants the database enforces:
- UNIQUE (source_version_id, section_anchor, bank_id) and UNIQUE hindsight_document_id, so a
  Hindsight document ID is never reused (a reused ID would destroy the earlier facts).
- A row is `linked` exactly when it has a linked-to Source Version and no document ID.
- Rows are never deleted, and a row's identity (Source Version, anchor, offsets, document
  ID, bank, link) never changes, so a superseded version's memory stays auditable.

Revision ID: 0007
Revises: 0005 (re-chained at merge)
"""

from alembic import op

revision = "0007"
down_revision = "0005"
branch_labels = None
depends_on = None

_STATES = "'pending', 'completed', 'failed', 'zero_fact', 'linked'"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE hindsight_operation (
            id text PRIMARY KEY CHECK (btrim(id) <> ''),
            bank_id text NOT NULL CHECK (btrim(bank_id) <> ''),
            kind text NOT NULL CHECK (kind IN ('retain', 'reprocess')),
            status text NOT NULL CHECK (btrim(status) <> ''),
            error_message text,
            retry_count integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            -- The Hindsight document IDs submitted in this operation's batch.
            document_ids jsonb NOT NULL CHECK (jsonb_typeof(document_ids) = 'array'),
            -- Hindsight's result metadata once terminal (items, tokens, extraction errors).
            result_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(result_metadata) = 'object'),
            job_id uuid REFERENCES job (id),
            submitted_at timestamptz NOT NULL DEFAULT now(),
            last_polled_at timestamptz,
            completed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX hindsight_operation_source_version"
        " ON hindsight_operation (source_version_id, submitted_at)"
    )

    op.execute(f"""
        CREATE TABLE memory_document (
            id uuid PRIMARY KEY,
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            section_anchor text NOT NULL CHECK (section_anchor ~ '^[a-z0-9][a-z0-9-]*$'),
            section_heading text,
            -- Character offsets into the Source Version's parsed text: [char_start, char_end).
            char_start integer NOT NULL CHECK (char_start >= 0),
            char_end integer NOT NULL CHECK (char_end > char_start),
            sectioner_version text NOT NULL CHECK (btrim(sectioner_version) <> ''),
            hindsight_document_id text UNIQUE CHECK (hindsight_document_id ~ '^srcv:'),
            bank_id text NOT NULL CHECK (btrim(bank_id) <> ''),
            operation_id text REFERENCES hindsight_operation (id),
            retain_state text NOT NULL CHECK (retain_state IN ({_STATES})),
            fact_count integer CHECK (fact_count >= 0),
            reprocess_count integer NOT NULL DEFAULT 0 CHECK (reprocess_count BETWEEN 0 AND 1),
            template_version text NOT NULL CHECK (btrim(template_version) <> ''),
            linked_to_source_version_id uuid REFERENCES source_version (id),
            error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source_version_id, section_anchor, bank_id),
            CHECK ((retain_state = 'linked') = (linked_to_source_version_id IS NOT NULL)),
            CHECK ((retain_state = 'linked') = (hindsight_document_id IS NULL)),
            CHECK (linked_to_source_version_id IS DISTINCT FROM source_version_id),
            CHECK (retain_state NOT IN ('completed', 'zero_fact') OR fact_count IS NOT NULL),
            CHECK (retain_state <> 'zero_fact' OR fact_count = 0),
            CHECK (retain_state <> 'failed' OR error IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX memory_document_operation ON memory_document (operation_id)")
    op.execute(
        "CREATE INDEX memory_document_linked_to ON memory_document (linked_to_source_version_id)"
    )

    op.execute("""
        CREATE FUNCTION memory_document_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'memory_document rows are never removed (% is not allowed)', TG_OP;
            END IF;
            IF (NEW.id, NEW.source_version_id, NEW.section_anchor, NEW.char_start, NEW.char_end,
                NEW.sectioner_version, NEW.hindsight_document_id, NEW.bank_id,
                NEW.linked_to_source_version_id, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.source_version_id, OLD.section_anchor, OLD.char_start, OLD.char_end,
                OLD.sectioner_version, OLD.hindsight_document_id, OLD.bank_id,
                OLD.linked_to_source_version_id, OLD.created_at)
            THEN
                RAISE EXCEPTION 'a memory_document''s identity columns are immutable';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER memory_document_guard BEFORE UPDATE OR DELETE ON memory_document
        FOR EACH ROW EXECUTE FUNCTION memory_document_guard()
    """)
    op.execute("""
        CREATE TRIGGER memory_document_no_truncate BEFORE TRUNCATE ON memory_document
        FOR EACH STATEMENT EXECUTE FUNCTION memory_document_guard()
    """)
    for trigger in ("memory_document_guard", "memory_document_no_truncate"):
        op.execute(f"ALTER TABLE memory_document ENABLE ALWAYS TRIGGER {trigger}")

    for table in ("hindsight_operation", "memory_document"):
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON hindsight_operation, memory_document TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE memory_document, hindsight_operation")
    op.execute("DROP FUNCTION memory_document_guard()")
