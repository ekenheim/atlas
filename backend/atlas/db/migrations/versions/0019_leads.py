"""Discovery: the Scout's SearXNG queries and the Tier C leads they found.

- `discovery`: one per discovery (a `discover` job): the theme and question, the run whose
  Scout call wrote the queries, the engines asked, where the open gaps came from (the
  Bottlenecks mental model, when it had been refreshed) and how it ended.
- `discovery_query`: one per SearXNG query (at most 10 per discovery): its text and purpose,
  and the search's outcome, including the engines SearXNG reported unresponsive.
- `lead`: one per canonical URL, ever (the dedupe key): Tier C metadata only (URL, title,
  snippet, published date, engines, the query that first found it). A lead is never Evidence:
  nothing references it from the source ledger, Assertions or memory documents.
- `lead_sighting`: each time a query returned a lead, with what that result said.

Revision ID: 0019
Revises: 0018 (re-chained at merge)
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE discovery (
            id uuid PRIMARY KEY,
            job_id uuid UNIQUE REFERENCES job (id),
            run_id uuid NOT NULL REFERENCES run (id),
            theme text NOT NULL CHECK (theme <> ''),
            question text NOT NULL CHECK (question <> ''),
            engines text[] NOT NULL CHECK (cardinality(engines) > 0),
            max_queries smallint NOT NULL CHECK (max_queries BETWEEN 1 AND 10),
            gaps_source text,
            scout_role_call_id uuid REFERENCES role_call (id),
            queries_proposed integer CHECK (queries_proposed >= 0),
            status text NOT NULL DEFAULT 'scouting'
                CHECK (status IN ('scouting', 'searching', 'completed')),
            last_error text,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            CHECK ((status = 'completed') = (finished_at IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ix_discovery_started ON discovery (started_at DESC, id)")
    op.execute("""
        CREATE TABLE discovery_query (
            id uuid PRIMARY KEY,
            discovery_id uuid NOT NULL REFERENCES discovery (id),
            position smallint NOT NULL CHECK (position BETWEEN 1 AND 10),
            query text NOT NULL CHECK (query <> ''),
            purpose text,
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'searched', 'failed')),
            result_count integer CHECK (result_count >= 0),
            new_leads integer CHECK (new_leads >= 0),
            unresponsive_engines jsonb NOT NULL DEFAULT '[]'
                CHECK (jsonb_typeof(unresponsive_engines) = 'array'),
            error text,
            searched_at timestamptz,
            UNIQUE (discovery_id, position),
            CHECK ((status = 'pending') = (searched_at IS NULL))
        )
    """)
    op.execute("""
        CREATE TABLE lead (
            id uuid PRIMARY KEY,
            canonical_url text NOT NULL UNIQUE,
            url text NOT NULL,
            title text NOT NULL,
            snippet text NOT NULL,
            published_date date,
            engines text[] NOT NULL,
            first_query_id uuid NOT NULL REFERENCES discovery_query (id),
            tier text NOT NULL DEFAULT 'C' CHECK (tier = 'C'),
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_lead_first_seen ON lead (first_seen_at DESC, id)")
    op.execute("""
        CREATE TABLE lead_sighting (
            lead_id uuid NOT NULL REFERENCES lead (id),
            discovery_query_id uuid NOT NULL REFERENCES discovery_query (id),
            position integer NOT NULL CHECK (position >= 1),
            url text NOT NULL,
            title text NOT NULL,
            snippet text NOT NULL,
            engines text[] NOT NULL,
            published_date date,
            seen_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (lead_id, discovery_query_id)
        )
    """)
    op.execute("CREATE INDEX ix_lead_sighting_query ON lead_sighting (discovery_query_id)")
    op.execute("REVOKE ALL ON discovery, discovery_query, lead, lead_sighting FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON discovery, discovery_query, lead TO atlas_app;
                GRANT SELECT, INSERT ON lead_sighting TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE lead_sighting")
    op.execute("DROP TABLE lead")
    op.execute("DROP TABLE discovery_query")
    op.execute("DROP TABLE discovery")
