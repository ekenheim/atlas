"""Primary sources beyond filings (Chokepoint Watch, W3 phase 1).

- `source_version.available_at_basis` gains `page_published_date`: a web page's `available_at`
  is the publication date its own HTML carries (`article:published_time`, JSON-LD
  `datePublished`, a `<time datetime>`). A date the fetch was told is `publisher_timestamp` (as
  for a manual import) and a page with no date is `observed_discovery` (the fetch time), both
  already allowed.
- `discovery_query` may belong to no discovery: `GET /web-search` and `GET /filing-search` (and
  the MCP tools `web_search`, `filing_search`) store their results as `searxng` and `edgar_fts`
  leads, which need the query that found them (`lead_origin_query`), without a Scout's
  discovery. Such a query has `discovery_id` NULL and instead its `theme` (so
  `GET /leads?theme=` still finds the leads; the session's, else the caller's, else none) and,
  when a research session ran it, its `session_id`. A filing search keeps its `edgar_search`
  row (forms, window, outcome) as a discovery's does. A discovery's reads all go by
  `discovery_id`, so these never appear there.

The downgrade refuses while any such query or page-dated version exists.

Revision ID: 0118
Revises: 0117 (re-chained at integration)
"""

from alembic import op
from sqlalchemy import text

revision = "0118"
down_revision = "0117"
branch_labels = None
depends_on = None

_OLD = (
    "'sec_acceptance', 'publisher_timestamp', 'observed_discovery', 'observed_revision', "
    "'sec_dissemination'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_available_at_basis_check")
    op.execute(f"""
        ALTER TABLE source_version ADD CONSTRAINT source_version_available_at_basis_check
            CHECK (available_at_basis IN ({_OLD}, 'page_published_date'))
    """)
    op.execute("ALTER TABLE discovery_query ALTER COLUMN discovery_id DROP NOT NULL")
    op.execute("ALTER TABLE discovery_query ADD COLUMN theme text")
    op.execute(
        "ALTER TABLE discovery_query ADD COLUMN session_id uuid REFERENCES research_session (id)"
    )
    op.execute(
        "CREATE INDEX ix_discovery_query_session ON discovery_query (session_id)"
        " WHERE session_id IS NOT NULL"
    )


def downgrade() -> None:
    connection = op.get_bind()
    queries = connection.execute(
        text("SELECT count(*) FROM discovery_query WHERE discovery_id IS NULL")
    ).scalar_one()
    versions = connection.execute(
        text("SELECT count(*) FROM source_version WHERE available_at_basis = 'page_published_date'")
    ).scalar_one()
    if queries or versions:
        raise RuntimeError(
            f"refusing to downgrade: {queries} ad hoc searches and {versions} page-dated"
            " Source Versions exist; leads and Source Versions are never deleted"
        )
    op.execute("DROP INDEX ix_discovery_query_session")
    op.execute("ALTER TABLE discovery_query DROP COLUMN session_id")
    op.execute("ALTER TABLE discovery_query DROP COLUMN theme")
    op.execute("ALTER TABLE discovery_query ALTER COLUMN discovery_id SET NOT NULL")
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_available_at_basis_check")
    op.execute(f"""
        ALTER TABLE source_version ADD CONSTRAINT source_version_available_at_basis_check
            CHECK (available_at_basis IN ({_OLD}))
    """)
