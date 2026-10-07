"""Facts (bottleneck-argument ticket 02).

`fact`: one insert-only row per Fact, beside its Assertion (predicate `fact`, a validated
`value_json`): the argument step and status (also in the Assertion's `value_json`, indexed
here for reads) and the investigation it was found for, if any. Rows are never updated or
removed; review is the Assertion's.

Revision ID: 0099
Revises: 0077
"""

from alembic import op

revision = "0099"
down_revision = "0077"
branch_labels = None
depends_on = None

_STEPS = (
    "'constraint', 'demand_vs_supply', 'relief', 'control', 'capture', 'invalidation', 'context'"
)
_STATUSES = (
    "'in_effect', 'planned', 'in_development', 'hedged', 'regulatory', 'reported_by_third_party'"
)


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE fact (
            assertion_id uuid PRIMARY KEY REFERENCES assertion (id),
            investigation_id uuid REFERENCES investigation (id),
            step text NOT NULL CHECK (step IN ({_STEPS})),
            status text NOT NULL CHECK (status IN ({_STATUSES})),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_fact_step ON fact (step, created_at, assertion_id)")
    op.execute(
        "CREATE INDEX ix_fact_investigation ON fact (investigation_id, created_at, assertion_id)"
    )
    op.execute("""
        CREATE FUNCTION fact_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'facts are insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    triggers = {
        "fact_no_update": "BEFORE UPDATE ON fact FOR EACH ROW"
        " EXECUTE FUNCTION fact_reject_change()",
        "fact_no_delete": "BEFORE DELETE ON fact FOR EACH ROW"
        " EXECUTE FUNCTION fact_reject_change()",
        "fact_no_truncate": "BEFORE TRUNCATE ON fact FOR EACH STATEMENT"
        " EXECUTE FUNCTION fact_reject_change()",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE fact ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON fact FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON fact TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE fact")
    op.execute("DROP FUNCTION fact_reject_change()")
