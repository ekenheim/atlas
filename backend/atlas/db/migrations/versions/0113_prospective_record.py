"""The prospective record (atlas-beliefs ticket 19): dated calls, their checkpoints, and a
published Hypothesis's predictions with their settlements.

**Calls.** A call is what Atlas said, on a date, about companies and a claim, kept so it can be
read later against what followed. It is made when a Belief is judged `proven` (`origin`
`belief`, the Belief's ID), when a Hypothesis version is published (`hypothesis`, the version's
ID) and when a Scout session escalates an archive signal to a `question` Issue (`signal`, the
Issue's ID; `lead_id` the signal lead; `issue.lead_id` is the same link from the Issue's side).
`made_at` is the time of the judgement, publication or escalation, never earlier.

- `call_record`: one row per call (`origin`, `origin_id` unique), the theme, the claim as it was
  written, a direction where the origin carries one, the date.
- `call_company`: the companies a call names, each with the TradingView symbol the theme config
  gave it when the call was made (null: none).
- `call_checkpoint`: one row per call and horizon (1, 3 and 6 months), appended by the daily
  `settle_calls` job: what each company's close did from the call date, what the theme's
  equal-weighted universe did over the same days, and the difference. Closes and members are
  kept in the row (`companies`, `benchmark`), so a checkpoint reads without the price tables.
- `call_unpriced`: the note, once per call, that a checkpoint came due and could not be priced
  (`reason`: `no_symbol`, `tradingview_disabled`). Not terminal: a later pass that can price
  the call still appends its checkpoints.

**Predictions.** `prediction`: a published Hypothesis version's measurable prediction as a row
(measure, expected range, deadline and the source that settles it: a Fact, an XBRL observation
or a TradingView close). `prediction_settlement`: its one settlement, appended. A prediction's
state (`open`, `settled`, `lapsed`) is read from the deadline and the settlement, never stored.

Every table is insert-only (update, delete and truncate refused, enabled always), as the repo's
other insert-only tables are.

Revision ID: 0113
Revises: 0112
"""

from alembic import op

revision = "0113"
down_revision = "0112"
branch_labels = None
depends_on = None

_TABLES = (
    "call_record",
    "call_company",
    "call_checkpoint",
    "call_unpriced",
    "prediction",
    "prediction_settlement",
)


def upgrade() -> None:
    op.execute("ALTER TABLE issue ADD COLUMN lead_id uuid REFERENCES lead (id)")
    op.execute("""
        CREATE TABLE call_record (
            id uuid PRIMARY KEY,
            origin text NOT NULL CHECK (origin IN ('belief', 'hypothesis', 'signal')),
            origin_id uuid NOT NULL,
            lead_id uuid REFERENCES lead (id),
            theme text NOT NULL CHECK (btrim(theme) <> ''),
            claim text NOT NULL CHECK (btrim(claim) <> ''),
            direction text CHECK (direction IN ('tightening', 'easing')),
            made_at timestamptz NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (origin, origin_id),
            CHECK ((origin = 'signal') = (lead_id IS NOT NULL))
        )
    """)
    op.execute("CREATE UNIQUE INDEX ux_call_record_lead ON call_record (lead_id)")
    op.execute("CREATE INDEX ix_call_record_theme ON call_record (theme, made_at DESC)")
    op.execute("""
        CREATE TABLE call_company (
            call_id uuid NOT NULL REFERENCES call_record (id),
            company_id uuid NOT NULL REFERENCES company (id),
            symbol text CHECK (symbol IS NULL OR btrim(symbol) <> ''),
            PRIMARY KEY (call_id, company_id)
        )
    """)
    op.execute("""
        CREATE TABLE call_checkpoint (
            id uuid PRIMARY KEY,
            call_id uuid NOT NULL REFERENCES call_record (id),
            horizon_months smallint NOT NULL CHECK (horizon_months IN (1, 3, 6)),
            due_on date NOT NULL,
            change numeric NOT NULL,
            benchmark_change numeric,
            relative_change numeric,
            benchmark_members integer NOT NULL CHECK (benchmark_members >= 0),
            companies jsonb NOT NULL CHECK (jsonb_typeof(companies) = 'array'),
            benchmark jsonb NOT NULL CHECK (jsonb_typeof(benchmark) = 'array'),
            owner_override text NOT NULL CHECK (btrim(owner_override) <> ''),
            job_id uuid REFERENCES job (id),
            settled_at timestamptz NOT NULL,
            UNIQUE (call_id, horizon_months),
            CHECK ((benchmark_change IS NULL) = (relative_change IS NULL))
        )
    """)
    op.execute("""
        CREATE TABLE call_unpriced (
            call_id uuid PRIMARY KEY REFERENCES call_record (id),
            reason text NOT NULL CHECK (reason IN ('no_symbol', 'tradingview_disabled')),
            job_id uuid REFERENCES job (id),
            recorded_at timestamptz NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE prediction (
            id uuid PRIMARY KEY,
            hypothesis_id uuid NOT NULL REFERENCES hypothesis (id),
            version_id uuid NOT NULL REFERENCES hypothesis_version (id),
            prediction_index integer CHECK (prediction_index >= 0),
            measure text NOT NULL CHECK (btrim(measure) <> ''),
            unit text,
            expected_low numeric,
            expected_high numeric,
            deadline date NOT NULL,
            source_kind text NOT NULL
                CHECK (source_kind IN ('fact', 'financial_observation', 'price')),
            company_id uuid REFERENCES company (id),
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            recorded_at timestamptz NOT NULL DEFAULT now(),
            CHECK (expected_low IS NOT NULL OR expected_high IS NOT NULL),
            CHECK (expected_low IS NULL OR expected_high IS NULL OR expected_low <= expected_high),
            CHECK (source_kind <> 'price' OR company_id IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX ix_prediction_hypothesis ON prediction (hypothesis_id, deadline)")
    op.execute("""
        CREATE TABLE prediction_settlement (
            id uuid PRIMARY KEY,
            prediction_id uuid NOT NULL UNIQUE REFERENCES prediction (id),
            outcome text NOT NULL CHECK (outcome IN ('met', 'missed')),
            value numeric NOT NULL,
            source_kind text NOT NULL
                CHECK (source_kind IN ('fact', 'financial_observation', 'price')),
            fact_id uuid REFERENCES fact (assertion_id),
            observation_id uuid REFERENCES financial_observation (id),
            price_day date,
            price_symbol text,
            late boolean NOT NULL,
            note text,
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            settled_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((fact_id IS NOT NULL)::int + (observation_id IS NOT NULL)::int
                   + (price_day IS NOT NULL)::int = 1)
        )
    """)
    op.execute("""
        CREATE FUNCTION prospective_record_insert_only_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is insert-only: % is not allowed', TG_TABLE_NAME, TG_OP;
        END
        $$
    """)
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION prospective_record_insert_only_guard()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}"
            " FOR EACH STATEMENT EXECUTE FUNCTION prospective_record_insert_only_guard()"
        )
        for trigger in (f"{table}_guard", f"{table}_no_truncate"):
            op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger}")
    tables = ", ".join(_TABLES)
    op.execute(f"REVOKE ALL ON {tables} FROM PUBLIC")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON {tables} TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION prospective_record_insert_only_guard()")
    op.execute("ALTER TABLE issue DROP COLUMN lead_id")
