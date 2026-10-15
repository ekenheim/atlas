"""TradingView's earnings calendar and daily closes under the owner's override (ticket 16b).

- `lead.origin` gains `tradingview_calendar`: a company's reporting date, a Tier C lead (where
  to look, never Evidence). Like a `tradingview_news` lead it has no query.
- `tradingview_calendar_event`: the lead's static facts (the company, its symbol and themes,
  the fiscal period it is for, the TradingView event key it is deduplicated by, unique per
  company: companies on one fiscal calendar share a fallback key such as `fy2027-Q1`).
- `tradingview_calendar_observation`: what the calendar said about the event's date and
  status, each time it said something new. Insert-only: a date that moves is a new
  observation, so a read as of an earlier time sees the date Atlas knew then.
- `tradingview_price_bar`: a company's daily close, for settling predictions and replays.
  Insert-only: every close TradingView gave for a day is kept with when Atlas fetched it (a
  split- or dividend-adjusted refresh is a new row), and a read takes the latest fetch.
  Never Evidence and never read by an agent.

All three tables are guarded by triggers (update, delete and truncate refused, enabled
always), as the repo's other insert-only tables are.

Every row records the override text (`owner_override`).

Revision ID: 0110
Revises: 0109
"""

from alembic import op

revision = "0110"
down_revision = "0109"
branch_labels = None
depends_on = None

_TABLES = (
    "tradingview_calendar_event",
    "tradingview_calendar_observation",
    "tradingview_price_bar",
)
_OVERRIDE = "owner_override text NOT NULL CHECK (btrim(owner_override) <> '')"


def upgrade() -> None:
    op.execute("ALTER TABLE lead DROP CONSTRAINT lead_origin_query")
    op.execute("ALTER TABLE lead DROP CONSTRAINT lead_origin_check")
    op.execute("""
        ALTER TABLE lead ADD CONSTRAINT lead_origin_check
            CHECK (origin IN ('searxng', 'tradingview_news', 'edgar_fts', 'tradingview_calendar'))
    """)
    op.execute("""
        ALTER TABLE lead ADD CONSTRAINT lead_origin_query
            CHECK ((origin IN ('searxng', 'edgar_fts')) = (first_query_id IS NOT NULL))
    """)
    op.execute(f"""
        CREATE TABLE tradingview_calendar_event (
            lead_id uuid PRIMARY KEY REFERENCES lead (id),
            event_key text NOT NULL CHECK (btrim(event_key) <> ''),
            company_id uuid NOT NULL REFERENCES company (id),
            symbol text NOT NULL CHECK (btrim(symbol) <> ''),
            themes text[] NOT NULL,
            fiscal_period text,
            fiscal_year text,
            {_OVERRIDE},
            job_id uuid REFERENCES job (id),
            first_seen_at timestamptz NOT NULL,
            UNIQUE (company_id, event_key)
        )
    """)
    op.execute(
        "CREATE INDEX ix_tradingview_calendar_company ON tradingview_calendar_event (company_id)"
    )
    op.execute(f"""
        CREATE TABLE tradingview_calendar_observation (
            id uuid PRIMARY KEY,
            lead_id uuid NOT NULL REFERENCES tradingview_calendar_event (lead_id),
            event_at timestamptz NOT NULL,
            status text,
            {_OVERRIDE},
            job_id uuid REFERENCES job (id),
            observed_at timestamptz NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX ix_tradingview_calendar_observed ON tradingview_calendar_observation"
        " (lead_id, observed_at DESC)"
    )
    op.execute(f"""
        CREATE TABLE tradingview_price_bar (
            company_id uuid NOT NULL REFERENCES company (id),
            symbol text NOT NULL CHECK (btrim(symbol) <> ''),
            day date NOT NULL,
            close numeric NOT NULL,
            {_OVERRIDE},
            job_id uuid REFERENCES job (id),
            fetched_at timestamptz NOT NULL,
            PRIMARY KEY (company_id, day, fetched_at)
        )
    """)
    op.execute("""
        CREATE FUNCTION tradingview_insert_only_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is insert-only: % is not allowed', TG_TABLE_NAME, TG_OP;
        END
        $$
    """)
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION tradingview_insert_only_guard()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}"
            " FOR EACH STATEMENT EXECUTE FUNCTION tradingview_insert_only_guard()"
        )
        for trigger in (f"{table}_guard", f"{table}_no_truncate"):
            op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger}")
    op.execute(
        "REVOKE ALL ON tradingview_calendar_event, tradingview_calendar_observation,"
        " tradingview_price_bar FROM PUBLIC"
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON tradingview_calendar_event,
                    tradingview_calendar_observation TO atlas_app;
                GRANT SELECT, INSERT ON tradingview_price_bar TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE tradingview_price_bar")
    op.execute("DROP TABLE tradingview_calendar_observation")
    op.execute("DROP TABLE tradingview_calendar_event")
    op.execute("DROP FUNCTION tradingview_insert_only_guard()")
    op.execute("DELETE FROM lead WHERE origin = 'tradingview_calendar'")
    op.execute("ALTER TABLE lead DROP CONSTRAINT lead_origin_query")
    op.execute("ALTER TABLE lead DROP CONSTRAINT lead_origin_check")
    op.execute("""
        ALTER TABLE lead ADD CONSTRAINT lead_origin_check
            CHECK (origin IN ('searxng', 'tradingview_news', 'edgar_fts'))
    """)
    op.execute("""
        ALTER TABLE lead ADD CONSTRAINT lead_origin_query
            CHECK ((origin IN ('searxng', 'edgar_fts')) = (first_query_id IS NOT NULL))
    """)
