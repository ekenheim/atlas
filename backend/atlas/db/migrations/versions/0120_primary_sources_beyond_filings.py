"""Primary sources beyond filings (Chokepoint Watch, W3 phase 1).

- `source_version.available_at_basis` gains `page_published_date`: a web page's `available_at`
  is the publication date its own HTML carries (`article:published_time`, or JSON-LD
  `datePublished` of an Article, NewsArticle or PressRelease), when that date is within seven
  days before the fetch. A date the fetch was told is `publisher_timestamp` (as for a manual
  import) and any other page is `observed_discovery` (the fetch time), both already allowed.
- `source_document.license_class` gains `third_party`: a page of a site that is not the
  company's own, whose register entry names no class.
- `fetch_observation.session_id`: the research session that asked for the fetch (`fetch_page`,
  or `sources fetch --session-id`). A page is read by a session as of an earlier time only if
  that session fetched it (`docs/decisions.md`, "Pages: ... never public before Atlas had it").
- `discovery_query` may belong to no discovery: `GET /web-search` and `GET /filing-search` (and
  the MCP tools `web_search`, `filing_search`) store their results as `searxng` and `edgar_fts`
  leads, which need the query that found them (`lead_origin_query`), without a Scout's
  discovery. Such a query has `discovery_id` NULL and instead its `theme` (the session's, else
  the caller's, else NULL, which `GET /leads?theme=` does not find) and, when a research session
  ran it, its `session_id`. A filing search keeps its `edgar_search` row (forms, window, outcome)
  as a discovery's does. A discovery's reads all go by `discovery_id`, so these never appear
  there.

The downgrade refuses while any such query, session-bound fetch, third-party document or
page-dated version exists.

Revision ID: 0120
Revises: 0119 (W1 holds 0118 and W6a 0119; the integrator re-chains)
"""

from alembic import op
from sqlalchemy import text

revision = "0120"
down_revision = "0119"
branch_labels = None
depends_on = None

_BASES = (
    "'sec_acceptance', 'publisher_timestamp', 'observed_discovery', 'observed_revision', "
    "'sec_dissemination'"
)
_LICENSES = (
    "'public_regulatory', 'public_issuer', 'lead_metadata', 'manual_lead', 'synthetic_fixture'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_available_at_basis_check")
    op.execute(f"""
        ALTER TABLE source_version ADD CONSTRAINT source_version_available_at_basis_check
            CHECK (available_at_basis IN ({_BASES}, 'page_published_date'))
    """)
    op.execute("ALTER TABLE source_document DROP CONSTRAINT source_document_license_class_check")
    op.execute(f"""
        ALTER TABLE source_document ADD CONSTRAINT source_document_license_class_check
            CHECK (license_class IN ({_LICENSES}, 'third_party')
                   OR license_class ~ '^licensed:[a-z0-9_-]+$')
    """)
    op.execute(
        "ALTER TABLE fetch_observation ADD COLUMN session_id uuid REFERENCES research_session (id)"
    )
    op.execute(
        "CREATE INDEX fetch_observation_session ON fetch_observation (session_id)"
        " WHERE session_id IS NOT NULL"
    )
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
    counts = {
        "ad hoc searches": "SELECT count(*) FROM discovery_query WHERE discovery_id IS NULL",
        "page-dated Source Versions": "SELECT count(*) FROM source_version"
        " WHERE available_at_basis = 'page_published_date'",
        "third-party documents": "SELECT count(*) FROM source_document"
        " WHERE license_class = 'third_party'",
        "session-bound fetches": "SELECT count(*) FROM fetch_observation"
        " WHERE session_id IS NOT NULL",
    }
    found = {name: connection.execute(text(sql)).scalar_one() for name, sql in counts.items()}
    if any(found.values()):
        listed = ", ".join(f"{count} {name}" for name, count in found.items() if count)
        raise RuntimeError(
            f"refusing to downgrade: {listed} exist; leads, Source Versions and fetch"
            " observations are never deleted"
        )
    op.execute("DROP INDEX ix_discovery_query_session")
    op.execute("ALTER TABLE discovery_query DROP COLUMN session_id")
    op.execute("ALTER TABLE discovery_query DROP COLUMN theme")
    op.execute("ALTER TABLE discovery_query ALTER COLUMN discovery_id SET NOT NULL")
    op.execute("DROP INDEX fetch_observation_session")
    op.execute("ALTER TABLE fetch_observation DROP COLUMN session_id")
    op.execute("ALTER TABLE source_document DROP CONSTRAINT source_document_license_class_check")
    op.execute(f"""
        ALTER TABLE source_document ADD CONSTRAINT source_document_license_class_check
            CHECK (license_class IN ({_LICENSES}) OR license_class ~ '^licensed:[a-z0-9_-]+$')
    """)
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_available_at_basis_check")
    op.execute(f"""
        ALTER TABLE source_version ADD CONSTRAINT source_version_available_at_basis_check
            CHECK (available_at_basis IN ({_BASES}))
    """)
