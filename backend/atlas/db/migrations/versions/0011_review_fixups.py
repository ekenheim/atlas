"""Code review fix-up (spec axis): returned memories, refresh runs, revised-version availability.

- `memory_document.memory_ids`: the IDs of the memories Hindsight extracted from the section's
  document, listed once its operation completed (spec Part B story 10). NULL until then (and
  for a `linked` or failed section); `[]` for a zero-fact one.
- `mental_model_refresh.run_id`: the run record of a submitted refresh (spec Part B stories
  15 and 32), NULL for a skip or when LiteLLM isn't configured. It is set when the row is
  inserted and never changes (added to the row's immutable columns).
- `source_version.available_at_basis` gains `observed_revision`: a Source Version that
  supersedes an earlier one is available from when Atlas observed the change, not from the
  original filing's acceptance time (spec Part A story 31; docs/decisions.md).

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_BASES = "'sec_acceptance', 'publisher_timestamp', 'observed_discovery'"


def _refresh_guard(immutable: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION mental_model_refresh_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'mental_model_refresh rows are never removed (% is not allowed)',
                    TG_OP;
            END IF;
            IF OLD.status <> 'submitted' THEN
                RAISE EXCEPTION 'a % mental model refresh is final', OLD.status;
            END IF;
            IF ({immutable.replace("$", "NEW")}) IS DISTINCT FROM ({immutable.replace("$", "OLD")})
            THEN
                RAISE EXCEPTION 'a mental model refresh''s model, job and operation are immutable';
            END IF;
            RETURN NEW;
        END
        $$
    """


_IMMUTABLE = (
    "$.id, $.bank_id, $.mental_model_id, $.job_id, $.scheduled_for, $.template_version,"
    " $.min_refresh_interval_seconds, $.operation_id, $.previous_refreshed_at, $.requested_at"
)


def upgrade() -> None:
    op.execute("""
        ALTER TABLE memory_document ADD COLUMN memory_ids jsonb
            CONSTRAINT ck_memory_document_memory_ids
            CHECK (memory_ids IS NULL OR jsonb_typeof(memory_ids) = 'array')
    """)
    op.execute("ALTER TABLE mental_model_refresh ADD COLUMN run_id uuid REFERENCES run (id)")
    op.execute(_refresh_guard(_IMMUTABLE + ", $.run_id"))
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_available_at_basis_check")
    op.execute(f"""
        ALTER TABLE source_version ADD CONSTRAINT source_version_available_at_basis_check
            CHECK (available_at_basis IN ({_BASES}, 'observed_revision'))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_available_at_basis_check")
    op.execute(f"""
        ALTER TABLE source_version ADD CONSTRAINT source_version_available_at_basis_check
            CHECK (available_at_basis IN ({_BASES}))
    """)
    op.execute(_refresh_guard(_IMMUTABLE))
    op.execute("ALTER TABLE mental_model_refresh DROP COLUMN run_id")
    op.execute("ALTER TABLE memory_document DROP COLUMN memory_ids")
