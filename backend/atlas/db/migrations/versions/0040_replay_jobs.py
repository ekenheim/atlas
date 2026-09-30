"""Replay banks (§9.2; ticket 22): the pipeline replayed at a cutoff in an isolated
`atlas-replay-<id>` bank on the local Hindsight, then the bank deleted.

- `replay_job`: one replay: its cutoff and scope, the fixed question set (name, version and
  hash), the stage it has reached (`create_bank` -> `retain` -> `consolidate` -> `questions`
  -> `delete_bank` -> `done`) with a cursor into it, its status, the leakage it counted, and
  when its bank was deleted. A replay that fails or is cancelled goes to `delete_bank` too,
  with its `final_status`, so its bank is always deleted.
- `replay_source_version`: the Source Versions the replay may see (available at the cutoff,
  the latest version of each Source Document then), in retain order, each with its retain's
  outcome.
- `replay_document`: the replay's own section ledger (the replay bank's documents), which its
  provenance resolver reads instead of `memory_document`, so a replay's citations resolve
  only to the Source Versions it retained. The research bank's ledger is never written.
- `replay_operation`: each Hindsight operation a replay submitted (its retain batches and its
  consolidation), counted by the `codex` budget like `hindsight_operation`.
- `replay_answer`: each question's recall and reflect, with resolved citations and the
  leakage found in them.

Revision ID: 0040
Revises: 0038 (re-chained at merge)
"""

from alembic import op

revision = "0040"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE replay_job (
            id uuid PRIMARY KEY,
            bank_id text NOT NULL UNIQUE CHECK (bank_id = 'atlas-replay-' || id::text),
            cutoff timestamptz NOT NULL,
            availability_convention text NOT NULL CHECK (availability_convention = 'available_at'),
            company_ids jsonb NOT NULL,
            scope jsonb NOT NULL,
            question_set text NOT NULL,
            question_set_version text NOT NULL,
            question_set_sha256 text NOT NULL CHECK (question_set_sha256 ~ '^[0-9a-f]{64}$'),
            questions jsonb NOT NULL,
            max_source_versions integer NOT NULL CHECK (max_source_versions >= 1),
            eligible_source_versions integer NOT NULL CHECK (eligible_source_versions >= 0),
            template_version text,
            template_manifest_sha256 text,
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
            stage text NOT NULL DEFAULT 'create_bank'
                CHECK (stage IN ('create_bank', 'retain', 'consolidate', 'questions',
                                 'delete_bank', 'done')),
            cursor integer NOT NULL DEFAULT 0 CHECK (cursor >= 0),
            final_status text CHECK (final_status IN ('completed', 'failed', 'cancelled')),
            consolidation jsonb,
            leakage jsonb,
            error text,
            cancel_requested_at timestamptz,
            job_id uuid NOT NULL,
            requested_by text NOT NULL CHECK (btrim(requested_by) <> ''),
            created_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz,
            finished_at timestamptz,
            bank_deleted_at timestamptz,
            bank_delete_error text,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((stage IN ('delete_bank', 'done')) = (final_status IS NOT NULL)),
            CHECK ((status IN ('completed', 'failed', 'cancelled')) = (stage = 'done'))
        )
    """)
    op.execute("CREATE INDEX ix_replay_job_created ON replay_job (created_at, id)")
    op.execute("""
        CREATE TABLE replay_source_version (
            replay_job_id uuid NOT NULL REFERENCES replay_job (id),
            position integer NOT NULL CHECK (position >= 0),
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            available_at timestamptz NOT NULL,
            available_at_basis text NOT NULL,
            retain_status text NOT NULL DEFAULT 'pending'
                CHECK (retain_status IN ('pending', 'submitted', 'completed', 'failed')),
            operation_id text,
            polls integer NOT NULL DEFAULT 0 CHECK (polls >= 0),
            sections integer,
            facts integer,
            error text,
            PRIMARY KEY (replay_job_id, position),
            UNIQUE (replay_job_id, source_version_id)
        )
    """)
    op.execute("""
        CREATE TABLE replay_document (
            replay_job_id uuid NOT NULL REFERENCES replay_job (id),
            hindsight_document_id text NOT NULL,
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            section_anchor text NOT NULL,
            section_heading text,
            char_start integer NOT NULL CHECK (char_start >= 0),
            char_end integer NOT NULL CHECK (char_end >= char_start),
            fact_count integer,
            PRIMARY KEY (replay_job_id, hindsight_document_id),
            FOREIGN KEY (replay_job_id, source_version_id)
                REFERENCES replay_source_version (replay_job_id, source_version_id)
        )
    """)
    op.execute("""
        CREATE TABLE replay_operation (
            operation_id text PRIMARY KEY,
            replay_job_id uuid NOT NULL REFERENCES replay_job (id),
            kind text NOT NULL CHECK (kind IN ('retain', 'consolidation')),
            source_version_id uuid REFERENCES source_version (id),
            status text NOT NULL,
            error_message text,
            submitted_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            CHECK ((kind = 'retain') = (source_version_id IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ix_replay_operation_job ON replay_operation (replay_job_id)")
    op.execute("""
        CREATE TABLE replay_answer (
            replay_job_id uuid NOT NULL REFERENCES replay_job (id),
            position integer NOT NULL CHECK (position >= 0),
            question_key text NOT NULL,
            question text NOT NULL,
            recall jsonb NOT NULL,
            answer_text text NOT NULL,
            citations jsonb NOT NULL,
            leakage jsonb NOT NULL,
            answered_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (replay_job_id, position)
        )
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON replay_job, replay_source_version,
                    replay_operation TO atlas_app;
                GRANT SELECT, INSERT, UPDATE, DELETE ON replay_document TO atlas_app;
                GRANT SELECT, INSERT ON replay_answer TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE replay_answer")
    op.execute("DROP TABLE replay_operation")
    op.execute("DROP TABLE replay_document")
    op.execute("DROP TABLE replay_source_version")
    op.execute("DROP TABLE replay_job")
