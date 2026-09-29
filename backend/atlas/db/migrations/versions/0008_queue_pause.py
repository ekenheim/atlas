"""Queue pause and pacing (spec Part B "Job queue extensions"; docs/data-model.md §2.7, §3.5).

- `job.job_class`: `interactive` (the default) or `backfill`. A backfill-class job is claimed
  only inside the configured nightly window.
- `hindsight_operation.error_class`: how a failed operation's error was classified:
  `quota` (429, rate limit, insufficient quota) and `unavailable` (503, connection failures)
  pause the queue and are resubmitted; `permanent` fails the operation's sections.
- `queue_pause`: the single row holding the queue-level pause. `level` counts the pauses
  since the last success (0: clear), the backoff doubles per level up to 1 h, and the listed
  job kinds aren't claimed until `resume_after`.
- `queue_pause_event`: one row per pause entered, kept for the pause history and metrics.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_FAILURE_CLASSES = "'quota', 'unavailable'"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE job ADD COLUMN job_class text NOT NULL DEFAULT 'interactive'
            CONSTRAINT ck_job_class CHECK (job_class IN ('interactive', 'backfill'))
    """)
    op.execute("""
        ALTER TABLE hindsight_operation ADD COLUMN error_class text
            CONSTRAINT ck_hindsight_operation_error_class
            CHECK (error_class IN ('quota', 'unavailable', 'permanent'))
    """)
    op.execute(f"""
        CREATE TABLE queue_pause (
            id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            -- Pauses since the last success of a pausable job; 0 means the queue is clear.
            level integer NOT NULL DEFAULT 0 CHECK (level >= 0),
            error_class text CHECK (error_class IN ({_FAILURE_CLASSES})),
            reason text,
            -- The job kinds the pause holds back (those that depend on Hindsight or LiteLLM).
            kinds text[] NOT NULL DEFAULT '{{}}',
            backoff_seconds double precision
                CHECK (backoff_seconds > 0 AND backoff_seconds <= 3600),
            paused_at timestamptz,
            resume_after timestamptz,
            -- When the current run of pauses began; null once a success clears it.
            episode_started_at timestamptz,
            job_id uuid REFERENCES job (id),
            cleared_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_queue_pause_level CHECK (
                level = 0 OR (error_class IS NOT NULL AND reason IS NOT NULL
                    AND backoff_seconds IS NOT NULL AND paused_at IS NOT NULL
                    AND resume_after IS NOT NULL AND episode_started_at IS NOT NULL)
            ),
            CONSTRAINT ck_queue_pause_episode CHECK ((level = 0) = (episode_started_at IS NULL))
        )
    """)
    op.execute("INSERT INTO queue_pause (id) VALUES (1)")
    op.execute(f"""
        CREATE TABLE queue_pause_event (
            id uuid PRIMARY KEY,
            level integer NOT NULL CHECK (level >= 1),
            error_class text NOT NULL CHECK (error_class IN ({_FAILURE_CLASSES})),
            reason text NOT NULL,
            kinds text[] NOT NULL,
            backoff_seconds double precision NOT NULL
                CHECK (backoff_seconds > 0 AND backoff_seconds <= 3600),
            paused_at timestamptz NOT NULL,
            resume_after timestamptz NOT NULL,
            job_id uuid REFERENCES job (id),
            job_kind text NOT NULL
        )
    """)

    for table in ("queue_pause", "queue_pause_event"):
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, UPDATE ON queue_pause TO atlas_app;
                GRANT SELECT, INSERT ON queue_pause_event TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE queue_pause_event, queue_pause")
    op.execute("ALTER TABLE hindsight_operation DROP COLUMN error_class")
    op.execute("ALTER TABLE job DROP COLUMN job_class")
