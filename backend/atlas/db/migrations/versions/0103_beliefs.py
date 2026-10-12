"""Beliefs (beliefs ticket 02).

`belief`: one falsifiable proposition about a bottleneck step, in Atlas's words (theme, step,
`as_of`, the session that produced it, `status`); `belief_company` its companies;
`belief_judgement` insert-only (the current judgement is the latest row); `belief_citation` a
Fact or an Assertion with a signed valence and a weight class (insert-only);
`belief_supersession` many-to-many, lossless; `belief_flag` raised by code, cleared by a
judgement (the only change a flag allows).

Revision ID: 0103
Revises: 0102
"""

from alembic import op

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None

_STEPS = ", ".join(
    f"'{step}'"
    for step in (
        "constraint",
        "demand_vs_supply",
        "relief",
        "control",
        "capture",
        "invalidation",
    )
)
_INSERT_ONLY = ("belief_judgement", "belief_citation", "belief_supersession")


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE belief (
            id uuid PRIMARY KEY,
            statement text NOT NULL CHECK (btrim(statement) <> ''),
            theme text NOT NULL CHECK (btrim(theme) <> ''),
            step text NOT NULL CHECK (step IN ({_STEPS})),
            as_of timestamptz NOT NULL,
            produced_by uuid REFERENCES research_session (id),
            status text NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'superseded', 'withdrawn')),
            created_by text NOT NULL CHECK (btrim(created_by) <> ''),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_belief_theme ON belief (theme, step, created_at)")
    op.execute("""
        CREATE TABLE belief_company (
            belief_id uuid NOT NULL REFERENCES belief (id),
            company_id uuid NOT NULL REFERENCES company (id),
            PRIMARY KEY (belief_id, company_id)
        )
    """)
    op.execute("CREATE INDEX ix_belief_company_company ON belief_company (company_id)")
    op.execute("""
        CREATE TABLE belief_judgement (
            id uuid PRIMARY KEY,
            belief_id uuid NOT NULL REFERENCES belief (id),
            judgement text NOT NULL
                CHECK (judgement IN ('proven', 'disproven', 'unproven', 'undecidable')),
            confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            reason text NOT NULL CHECK (btrim(reason) <> ''),
            at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_belief_judgement_belief ON belief_judgement (belief_id, at)")
    op.execute("""
        CREATE TABLE belief_citation (
            id uuid PRIMARY KEY,
            belief_id uuid NOT NULL REFERENCES belief (id),
            kind text NOT NULL CHECK (kind IN ('fact', 'assertion')),
            ref_id uuid NOT NULL REFERENCES assertion (id),
            valence double precision NOT NULL CHECK (valence BETWEEN -1 AND 1),
            weight text NOT NULL CHECK (weight IN ('load_bearing', 'context')),
            note text,
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (belief_id, ref_id)
        )
    """)
    op.execute("CREATE INDEX ix_belief_citation_ref ON belief_citation (ref_id)")
    op.execute("""
        CREATE TABLE belief_supersession (
            superseded_id uuid NOT NULL REFERENCES belief (id),
            by_id uuid NOT NULL REFERENCES belief (id),
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            reason text NOT NULL CHECK (btrim(reason) <> ''),
            at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (superseded_id, by_id),
            CHECK (superseded_id <> by_id)
        )
    """)
    op.execute("""
        CREATE TABLE belief_flag (
            id uuid PRIMARY KEY,
            belief_id uuid NOT NULL REFERENCES belief (id),
            kind text NOT NULL CHECK (kind IN (
                'counterevidence_stands', 'source_revised', 'assertion_reviewed',
                'fact_superseded')),
            ref_id uuid NOT NULL,
            detail text NOT NULL,
            raised_at timestamptz NOT NULL DEFAULT now(),
            cleared_by uuid REFERENCES belief_judgement (id)
        )
    """)
    op.execute("CREATE INDEX ix_belief_flag_belief ON belief_flag (belief_id, raised_at)")
    op.execute(
        "CREATE UNIQUE INDEX ux_belief_flag_open ON belief_flag (belief_id, kind, ref_id)"
        " WHERE cleared_by IS NULL"
    )
    op.execute("""
        CREATE FUNCTION belief_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is insert-only: % is not allowed', TG_TABLE_NAME, TG_OP;
        END
        $$
    """)
    for table in (*_INSERT_ONLY, "belief_flag"):
        for kind, event in (("update", "UPDATE"), ("delete", "DELETE")):
            if table == "belief_flag" and kind == "update":
                continue
            name = f"{table}_no_{kind}"
            op.execute(
                f"CREATE TRIGGER {name} BEFORE {event} ON {table} FOR EACH ROW"
                " EXECUTE FUNCTION belief_reject_change()"
            )
            op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {name}")
    op.execute("""
        CREATE FUNCTION belief_flag_only_clears() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.cleared_by IS NOT NULL
               OR (to_jsonb(OLD) - 'cleared_by') <> (to_jsonb(NEW) - 'cleared_by') THEN
                RAISE EXCEPTION 'belief_flag allows only being cleared once';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute(
        "CREATE TRIGGER belief_flag_only_clears BEFORE UPDATE ON belief_flag FOR EACH ROW"
        " EXECUTE FUNCTION belief_flag_only_clears()"
    )
    op.execute("ALTER TABLE belief_flag ENABLE ALWAYS TRIGGER belief_flag_only_clears")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON belief, belief_flag TO atlas_app;
                GRANT SELECT, INSERT ON belief_company, belief_judgement, belief_citation,
                    belief_supersession TO atlas_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    for table in (
        "belief_flag",
        "belief_supersession",
        "belief_citation",
        "belief_judgement",
        "belief_company",
        "belief",
    ):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION belief_flag_only_clears()")
    op.execute("DROP FUNCTION belief_reject_change()")
