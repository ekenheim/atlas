"""Bank template applications and the minimal run record (spec Part B, stories 30-33).

- `bank_template_application`: one row per template applied to a Hindsight bank (dry run,
  then import), with the template version and the manifest's SHA-256. A run takes its
  template version from the bank's latest application.
- `run`: the minimal run record: code version, Hindsight version, template version, the
  LiteLLM deployments behind each alias Atlas uses, and token totals. Phase 4 extends it.

Both are append-and-finish tables; `atlas_app` gets only what the services need.

Revision ID: 0005
Revises: 0003 (re-chained at merge)
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    now = sa.text("now()")
    op.create_table(
        "bank_template_application",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("bank_id", sa.Text, nullable=False),
        sa.Column("template_version", sa.Text, nullable=False),
        sa.Column("manifest_sha256", sa.Text, nullable=False),
        # The dry run's and the import's results, as Hindsight returned them.
        sa.Column("dry_run_result", JSONB, nullable=False),
        sa.Column("import_result", JSONB, nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$'", name="ck_bank_template_application_sha256"
        ),
        sa.CheckConstraint("template_version <> ''", name="ck_bank_template_application_version"),
    )
    op.create_index(
        "ix_bank_template_application_latest",
        "bank_template_application",
        ["bank_id", sa.text("applied_at DESC")],
    )
    op.create_table(
        "run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("code_version", sa.Text, nullable=False),
        sa.Column("hindsight_version", sa.Text, nullable=False),
        sa.Column("template_version", sa.Text, nullable=False),
        # {alias: [{"model": <litellm_params.model>, "model_id": <model_info.id>}, ...]}
        sa.Column("routed_models", JSONB, nullable=False),
        sa.Column("tokens_in", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("jsonb_typeof(routed_models) = 'object'", name="ck_run_routed_models"),
        sa.CheckConstraint("tokens_in >= 0 AND tokens_out >= 0", name="ck_run_tokens"),
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON bank_template_application TO atlas_app;
                GRANT SELECT, INSERT, UPDATE ON run TO atlas_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_table("run")
    op.drop_table("bank_template_application")
