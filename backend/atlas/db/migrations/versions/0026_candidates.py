"""Candidates: companies outside the universe that leads name, and the universe's DB extension.

- `lead_examination`: one per lead whose title and snippet the mention extractor has read
  (the role call that read it, and how many companies it named). A lead is examined once.
- `candidate`: one per (theme, company) a lead named that isn't in the universe (spec §8.3
  states). `identity_key` is what entity resolution identified it by (`cik:`, `lei:` or,
  when it found no single entity, `name:` and the normalized name); the resolution is kept
  as JSON. The owner commits a `lead` (it becomes `investigating`, with its company and the
  ingest enqueued, or a note that no automated source exists yet) or rejects it with a
  reason. Candidates are never deleted, rejected ones included.
- `lead_mention`: each company a lead named, in the extractor's order, with its outcome:
  `in_universe` (the company), `candidate` (the Candidate it proposed or joined) or
  `unresolved` (no source identified it). A Candidate's leads are its mentions' leads.
- `universe_company`: the universe stored in the database beside the theme config: each
  company a committed Candidate added, in the Candidate's theme (atlas.companies
  `extend_universe`).

Revision ID: 0026
Revises: 0025 (re-chained at merge)
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

_STATES = (
    "'lead', 'investigating', 'evidence_ready', 'needs_more_evidence', 'paper_tracking',"
    " 'rejected', 'closed'"
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE lead_examination (
            lead_id uuid PRIMARY KEY REFERENCES lead (id),
            discovery_id uuid NOT NULL REFERENCES discovery (id),
            role_call_id uuid NOT NULL REFERENCES role_call (id),
            mentions integer NOT NULL CHECK (mentions >= 0),
            examined_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(f"""
        CREATE TABLE candidate (
            id uuid PRIMARY KEY,
            theme text NOT NULL CHECK (theme <> ''),
            identity_key text NOT NULL CHECK (identity_key ~ '^(cik|lei|name):.+$'),
            name text NOT NULL CHECK (btrim(name) <> ''),
            cik text CHECK (cik ~ '^[0-9]{{10}}$'),
            lei text CHECK (lei ~ '^[A-Z0-9]{{20}}$'),
            country text CHECK (country ~ '^[A-Z]{{2}}$'),
            tier text NOT NULL CHECK (tier IN ('exact', 'corroborated', 'candidate', 'conflict')),
            source_path text CHECK (source_path = 'sec'),
            resolution jsonb NOT NULL CHECK (jsonb_typeof(resolution) = 'object'),
            state text NOT NULL DEFAULT 'lead' CHECK (state IN ({_STATES})),
            company_id uuid REFERENCES company (id),
            ingest_job_id uuid REFERENCES job (id),
            ingest_note text,
            reject_reason text CHECK (btrim(reject_reason) <> ''),
            decided_by text,
            decided_at timestamptz,
            decision_note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (theme, identity_key),
            CHECK (source_path IS DISTINCT FROM 'sec' OR cik IS NOT NULL),
            CHECK ((state = 'rejected') = (reject_reason IS NOT NULL)),
            CHECK ((state IN ('lead', 'rejected')) = (company_id IS NULL)),
            CHECK ((state = 'lead') = (decided_at IS NULL)),
            CHECK (ingest_job_id IS NULL OR ingest_note IS NULL)
        )
    """)
    op.execute("CREATE INDEX ix_candidate_state ON candidate (state, created_at DESC, id)")
    op.execute("""
        CREATE TABLE lead_mention (
            id uuid PRIMARY KEY,
            lead_id uuid NOT NULL REFERENCES lead_examination (lead_id),
            position smallint NOT NULL CHECK (position >= 1),
            name text NOT NULL,
            ticker text,
            exchange text,
            mic text CHECK (mic ~ '^[A-Z0-9]{4}$'),
            outcome text NOT NULL CHECK (outcome IN ('in_universe', 'candidate', 'unresolved')),
            tier text,
            company_id uuid REFERENCES company (id),
            candidate_id uuid REFERENCES candidate (id),
            UNIQUE (lead_id, position),
            CHECK ((outcome = 'in_universe') = (company_id IS NOT NULL)),
            CHECK ((outcome = 'candidate') = (candidate_id IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ix_lead_mention_candidate ON lead_mention (candidate_id)")
    op.execute("""
        CREATE TABLE universe_company (
            theme text NOT NULL CHECK (theme <> ''),
            company_id uuid NOT NULL REFERENCES company (id),
            candidate_id uuid NOT NULL UNIQUE REFERENCES candidate (id),
            added_by text NOT NULL,
            added_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (theme, company_id)
        )
    """)
    op.execute("""
        CREATE FUNCTION candidate_never_removed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Candidates are never removed: % is not allowed', TG_OP;
        END
        $$
    """)
    triggers = {
        "candidate_no_delete": "BEFORE DELETE ON candidate FOR EACH ROW",
        "candidate_no_truncate": "BEFORE TRUNCATE ON candidate FOR EACH STATEMENT",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition} EXECUTE FUNCTION candidate_never_removed()")
        op.execute(f"ALTER TABLE candidate ENABLE ALWAYS TRIGGER {name}")
    op.execute(
        "REVOKE ALL ON lead_examination, candidate, lead_mention, universe_company FROM PUBLIC"
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON candidate TO atlas_app;
                GRANT SELECT, INSERT ON lead_examination, lead_mention, universe_company
                    TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE universe_company")
    op.execute("DROP TABLE lead_mention")
    op.execute("DROP TABLE candidate")
    op.execute("DROP FUNCTION candidate_never_removed()")
    op.execute("DROP TABLE lead_examination")
