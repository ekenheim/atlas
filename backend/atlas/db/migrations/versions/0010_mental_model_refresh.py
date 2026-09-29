"""Mental model refreshes: one row per decision of a `refresh_mental_model` job (spec Part B
stories 26-29).

- `mental_model_refresh`: a refresh the job **skipped** (inside the model's minimum refresh
  interval, or nothing new in its scope), or one it **submitted** to Hindsight and then saw
  **completed** or **failed**. It keeps the model and bank, the job and the day it was
  scheduled for, the template version and minimum interval that applied, Hindsight's
  `last_refreshed_at` before and after, the operation and its outcome (a failure's error and
  class), and the model's content and raw citations as Hindsight returned them afterwards
  (for a skip: as the job found them). Requested and completed times are the application
  clock's, so the minimum interval is measured on one clock.

Invariants the database enforces:
- A `skipped` row has its reason and no operation; every other row has its operation. A
  `completed` row has its completion time and content, a `failed` one its error.
- Only a `submitted` row changes, and only its outcome columns: the model, bank, job,
  schedule, interval and request time never change, `skipped`/`completed`/`failed` rows are
  final, and rows are never deleted.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE mental_model_refresh (
            id uuid PRIMARY KEY,
            bank_id text NOT NULL CHECK (btrim(bank_id) <> ''),
            mental_model_id text NOT NULL CHECK (btrim(mental_model_id) <> ''),
            job_id uuid NOT NULL REFERENCES job (id),
            scheduled_for date,
            template_version text CHECK (btrim(template_version) <> ''),
            min_refresh_interval_seconds integer NOT NULL
                CHECK (min_refresh_interval_seconds > 0),
            status text NOT NULL
                CHECK (status IN ('skipped', 'submitted', 'completed', 'failed')),
            skip_reason text CHECK (skip_reason IN ('min_interval', 'not_stale')),
            operation_id text CHECK (btrim(operation_id) <> ''),
            operation_status text,
            error text,
            error_class text CHECK (error_class IN ('quota', 'unavailable', 'permanent')),
            previous_refreshed_at timestamptz,
            refreshed_at timestamptz,
            content text,
            content_sha256 text CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            raw_citations jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(raw_citations) = 'array'),
            result_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(result_metadata) = 'object'),
            requested_at timestamptz NOT NULL,
            completed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((status = 'skipped') = (skip_reason IS NOT NULL)),
            CHECK ((status = 'skipped') = (operation_id IS NULL)),
            CHECK ((status = 'failed') = (error IS NOT NULL)),
            CHECK (status <> 'completed' OR (completed_at IS NOT NULL AND content IS NOT NULL)),
            CHECK (status <> 'submitted' OR completed_at IS NULL),
            CHECK ((content IS NULL) = (content_sha256 IS NULL))
        )
    """)
    op.execute(
        "CREATE INDEX mental_model_refresh_model"
        " ON mental_model_refresh (bank_id, mental_model_id, requested_at)"
    )
    op.execute("CREATE INDEX mental_model_refresh_job ON mental_model_refresh (job_id)")

    op.execute("""
        CREATE FUNCTION mental_model_refresh_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'mental_model_refresh rows are never removed (% is not allowed)',
                    TG_OP;
            END IF;
            IF OLD.status <> 'submitted' THEN
                RAISE EXCEPTION 'a % mental model refresh is final', OLD.status;
            END IF;
            IF (NEW.id, NEW.bank_id, NEW.mental_model_id, NEW.job_id, NEW.scheduled_for,
                NEW.template_version, NEW.min_refresh_interval_seconds, NEW.operation_id,
                NEW.previous_refreshed_at, NEW.requested_at)
               IS DISTINCT FROM
               (OLD.id, OLD.bank_id, OLD.mental_model_id, OLD.job_id, OLD.scheduled_for,
                OLD.template_version, OLD.min_refresh_interval_seconds, OLD.operation_id,
                OLD.previous_refreshed_at, OLD.requested_at)
            THEN
                RAISE EXCEPTION 'a mental model refresh''s model, job and operation are immutable';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER mental_model_refresh_guard BEFORE UPDATE OR DELETE ON mental_model_refresh
        FOR EACH ROW EXECUTE FUNCTION mental_model_refresh_guard()
    """)
    op.execute("""
        CREATE TRIGGER mental_model_refresh_no_truncate BEFORE TRUNCATE ON mental_model_refresh
        FOR EACH STATEMENT EXECUTE FUNCTION mental_model_refresh_guard()
    """)
    for trigger in ("mental_model_refresh_guard", "mental_model_refresh_no_truncate"):
        op.execute(f"ALTER TABLE mental_model_refresh ENABLE ALWAYS TRIGGER {trigger}")

    op.execute("REVOKE ALL ON mental_model_refresh FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON mental_model_refresh TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE mental_model_refresh")
    op.execute("DROP FUNCTION mental_model_refresh_guard()")
