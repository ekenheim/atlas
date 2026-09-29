"""TradingView as an owner-override source (ticket 31; off by default).

- `tradingview_request`: one row per MCP tool call Atlas made to TradingView (the tool,
  the job, when, and whether it answered). Counted against the `tradingview` provider's
  rolling-window budget (`atlas.jobs.budget`), so `provider_usage` accepts that provider.
- `tradingview_catalog_entry`: the filing and event catalog, one row per TradingView
  document `get_documents` listed (category, form, fiscal period, reported time, title,
  upstream provider, its views' IDs and types). Metadata only: summaries are never stored.
  A re-listing updates the row and its `last_seen_at`.
- `tradingview_headline`: a `get_news` headline's metadata (original publisher, published
  time, related symbols, the company and its themes) for a Tier C lead. Story text isn't
  stored.
- `lead`: a lead now has an `origin`. A `searxng` lead keeps its first discovery query; a
  `tradingview_news` lead has none (its `tradingview_headline` says where it came from).
- `fetch_observation.owner_override`: the owner's recorded override a fetch was made under.

Every TradingView row records the override text (`owner_override`).

Revision ID: 0035
Revises: 0034 (re-chained at merge)
"""

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

_OVERRIDE = "owner_override text NOT NULL CHECK (btrim(owner_override) <> '')"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tradingview_request (
            id uuid PRIMARY KEY,
            job_id uuid REFERENCES job (id),
            tool text NOT NULL CHECK (btrim(tool) <> ''),
            outcome text NOT NULL CHECK (outcome IN ('ok', 'error')),
            error text,
            called_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((outcome = 'error') = (error IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ix_tradingview_request_called ON tradingview_request (called_at)")
    op.execute("ALTER TABLE provider_usage DROP CONSTRAINT provider_usage_provider_check")
    op.execute("""
        ALTER TABLE provider_usage ADD CONSTRAINT provider_usage_provider_check
            CHECK (provider IN ('codex', 'minimax', 'tradingview'))
    """)
    op.execute(f"""
        CREATE TABLE tradingview_catalog_entry (
            id uuid PRIMARY KEY,
            company_id uuid NOT NULL REFERENCES company (id),
            symbol text NOT NULL CHECK (btrim(symbol) <> ''),
            document_id text NOT NULL UNIQUE CHECK (btrim(document_id) <> ''),
            correlation_id text,
            category_id text,
            category text,
            event text,
            form_id text,
            form text,
            fiscal_period text,
            fiscal_year text,
            reported_at timestamptz,
            status text,
            title text NOT NULL,
            upstream_provider_id text,
            upstream_provider text,
            views jsonb NOT NULL CHECK (jsonb_typeof(views) = 'array'),
            {_OVERRIDE},
            first_job_id uuid REFERENCES job (id),
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_tradingview_catalog_company ON tradingview_catalog_entry"
        " (company_id, reported_at DESC)"
    )
    op.execute("ALTER TABLE lead ALTER COLUMN first_query_id DROP NOT NULL")
    op.execute("""
        ALTER TABLE lead ADD COLUMN origin text NOT NULL DEFAULT 'searxng'
            CHECK (origin IN ('searxng', 'tradingview_news'))
    """)
    op.execute("""
        ALTER TABLE lead ADD CONSTRAINT lead_origin_query
            CHECK ((origin = 'searxng') = (first_query_id IS NOT NULL))
    """)
    op.execute(f"""
        CREATE TABLE tradingview_headline (
            lead_id uuid PRIMARY KEY REFERENCES lead (id),
            headline_id text NOT NULL UNIQUE CHECK (btrim(headline_id) <> ''),
            company_id uuid NOT NULL REFERENCES company (id),
            symbol text NOT NULL CHECK (btrim(symbol) <> ''),
            themes text[] NOT NULL,
            publisher text,
            publisher_url text,
            published_at timestamptz,
            related_symbols text[] NOT NULL,
            urgency integer,
            {_OVERRIDE},
            job_id uuid REFERENCES job (id),
            first_seen_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_tradingview_headline_company ON tradingview_headline (company_id)")
    op.execute("""
        ALTER TABLE fetch_observation ADD COLUMN owner_override text
            CHECK (owner_override IS NULL OR btrim(owner_override) <> '')
    """)
    op.execute(
        "REVOKE ALL ON tradingview_request, tradingview_catalog_entry, tradingview_headline"
        " FROM PUBLIC"
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON tradingview_request, tradingview_headline TO atlas_app;
                GRANT SELECT, INSERT, UPDATE ON tradingview_catalog_entry TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE fetch_observation DROP COLUMN owner_override")
    op.execute("DROP TABLE tradingview_headline")
    op.execute("DELETE FROM lead WHERE origin <> 'searxng'")
    op.execute("ALTER TABLE lead DROP CONSTRAINT lead_origin_query")
    op.execute("ALTER TABLE lead DROP COLUMN origin")
    op.execute("ALTER TABLE lead ALTER COLUMN first_query_id SET NOT NULL")
    op.execute("DROP TABLE tradingview_catalog_entry")
    op.execute("DELETE FROM provider_usage WHERE provider = 'tradingview'")
    op.execute("ALTER TABLE provider_usage DROP CONSTRAINT provider_usage_provider_check")
    op.execute("""
        ALTER TABLE provider_usage ADD CONSTRAINT provider_usage_provider_check
            CHECK (provider IN ('codex', 'minimax'))
    """)
    op.execute("DROP TABLE tradingview_request")
