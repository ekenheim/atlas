"""EDGAR full-text search as a discovery channel (pilot fix 12).

- `discovery_query.filing_phrase`: the exact phrase the Scout (or the Skeptic) asked to search
  in filings, as written (None: none).
- `edgar_search`: a query's search of SEC EDGAR full-text search, one per query that has a
  phrase while the channel is on: the `q` sent (each phrase in double quotes), the forms and
  the date range, and its outcome (as a SearXNG search's: status, hits, new leads, error).
- `lead.origin` gains `edgar_fts`: a filing document an EDGAR full-text search returned. Like
  a `searxng` lead it keeps the query that first found it.
- `lead_sighting.channel`: which channel returned the sighting (`searxng` or `edgar_fts`),
  so ranking scores an EDGAR hit against the phrase searched, not the web query.
- `edgar_filing`: an `edgar_fts` lead's filing metadata (filer, CIK, form, dates, accession,
  document), the universe company that filed it, its archived Source Version when Atlas has
  one, and `ingestable` (a universe company's filing Atlas hasn't archived).
- `lead_examination` may be made without a role call (`method` `filer_cik`): a filing lead's
  company is its filer's CIK, resolved without the mention extractor.

The downgrade refuses while any `edgar_fts` lead or `filer_cik` examination exists: leads,
examinations and Candidates are never deleted.

Revision ID: 0050
Revises: 0046
"""

from alembic import op
from sqlalchemy import text

revision = "0050"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE discovery_query ADD COLUMN filing_phrase text")
    op.execute("""
        CREATE TABLE edgar_search (
            discovery_query_id uuid PRIMARY KEY REFERENCES discovery_query (id),
            query text NOT NULL CHECK (btrim(query) <> ''),
            forms text[] NOT NULL CHECK (cardinality(forms) >= 1),
            start_date date NOT NULL,
            end_date date NOT NULL,
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'searched', 'failed')),
            total_hits integer CHECK (total_hits >= 0),
            result_count integer CHECK (result_count >= 0),
            new_leads integer CHECK (new_leads >= 0),
            error text,
            searched_at timestamptz,
            CHECK (start_date <= end_date),
            CHECK ((status = 'pending') = (searched_at IS NULL))
        )
    """)
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
    op.execute("""
        ALTER TABLE lead_sighting ADD COLUMN channel text NOT NULL DEFAULT 'searxng'
            CHECK (channel IN ('searxng', 'edgar_fts'))
    """)
    op.execute("""
        CREATE TABLE edgar_filing (
            lead_id uuid PRIMARY KEY REFERENCES lead (id),
            cik text NOT NULL CHECK (cik ~ '^[0-9]{10}$'),
            filer text NOT NULL CHECK (btrim(filer) <> ''),
            ticker text,
            form text NOT NULL CHECK (btrim(form) <> ''),
            file_type text,
            file_date date NOT NULL,
            period_ending date,
            accession text NOT NULL CHECK (accession ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
            document text NOT NULL CHECK (btrim(document) <> ''),
            company_id uuid REFERENCES company (id),
            source_version_id uuid REFERENCES source_version (id),
            ingestable boolean NOT NULL,
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (NOT ingestable OR (company_id IS NOT NULL AND source_version_id IS NULL))
        )
    """)
    op.execute("CREATE INDEX ix_edgar_filing_cik ON edgar_filing (cik)")
    op.execute("ALTER TABLE lead_examination ALTER COLUMN role_call_id DROP NOT NULL")
    op.execute("""
        ALTER TABLE lead_examination ADD COLUMN method text NOT NULL
            DEFAULT 'mention_extractor' CHECK (method IN ('mention_extractor', 'filer_cik'))
    """)
    op.execute("""
        ALTER TABLE lead_examination ADD CONSTRAINT lead_examination_method_role_call
            CHECK ((method = 'mention_extractor') = (role_call_id IS NOT NULL))
    """)
    op.execute("REVOKE ALL ON edgar_search, edgar_filing FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON edgar_search, edgar_filing TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    connection = op.get_bind()
    leads = connection.execute(
        text("SELECT count(*) FROM lead WHERE origin = 'edgar_fts'")
    ).scalar_one()
    examined = connection.execute(
        text("SELECT count(*) FROM lead_examination WHERE method = 'filer_cik'")
    ).scalar_one()
    if leads or examined:
        raise RuntimeError(
            f"refusing to downgrade: {leads} EDGAR full-text leads and {examined} filer"
            " examinations exist, and leads and examinations are never deleted"
        )
    op.execute("ALTER TABLE lead_examination DROP CONSTRAINT lead_examination_method_role_call")
    op.execute("ALTER TABLE lead_examination DROP COLUMN method")
    op.execute("ALTER TABLE lead_examination ALTER COLUMN role_call_id SET NOT NULL")
    op.execute("DROP TABLE edgar_filing")
    op.execute("ALTER TABLE lead_sighting DROP COLUMN channel")
    op.execute("ALTER TABLE lead DROP CONSTRAINT lead_origin_query")
    op.execute("ALTER TABLE lead DROP CONSTRAINT lead_origin_check")
    op.execute("""
        ALTER TABLE lead ADD CONSTRAINT lead_origin_check
            CHECK (origin IN ('searxng', 'tradingview_news'))
    """)
    op.execute("""
        ALTER TABLE lead ADD CONSTRAINT lead_origin_query
            CHECK ((origin = 'searxng') = (first_query_id IS NOT NULL))
    """)
    op.execute("DROP TABLE edgar_search")
    op.execute("ALTER TABLE discovery_query DROP COLUMN filing_phrase")
