"""The job table: the Postgres-backed work queue (spec §5.8).

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    now = sa.text("now()")
    op.create_table(
        "job",
        # uuid5 of (kind, idempotency key): re-enqueuing the same work is a no-op.
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("idempotency_key", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("lease_owner", sa.Text),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        # One entry per failed attempt: {attempt, error, worker, at}.
        sa.Column("failures", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("artifacts", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("kind", "idempotency_key", name="uq_job_kind_idempotency_key"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_job_status"
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1 AND attempts <= max_attempts",
            name="ck_job_attempts",
        ),
        sa.CheckConstraint(
            "(status = 'running') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_job_lease_iff_running",
        ),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_job_payload_object"),
        sa.CheckConstraint("jsonb_typeof(failures) = 'array'", name="ck_job_failures_array"),
        sa.CheckConstraint("jsonb_typeof(artifacts) = 'object'", name="ck_job_artifacts_object"),
    )
    # The claim query scans only unfinished jobs, oldest first.
    op.create_index(
        "ix_job_claimable",
        "job",
        ["created_at", "id"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_table("job")
