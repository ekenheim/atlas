"""Investigations: a theme question run as a fixed plan of role tasks on the job queue.

- `investigation`: one per investigation: the theme question and its §7.2 request (seed
  companies, as-of time), the per-run budgets (rounds, leads, documents, tokens), the run
  its role calls belong to, whether it is running or stopped (and why), and the Editor's
  research card.
- `investigation_premise`: what the plan's tasks assume: the question itself, and that each
  seed company belongs in it. A disproven premise cancels only the tasks that depend on it.
- `investigation_task`: one per role task of a round (Scout, one Investigator per seed
  company, the Skeptic and Financial Analyst slots, the Editor): its dependencies and
  premises, its status and the job that runs it (a resumed task gets a new generation, so a
  new job).
- `investigation_lead` / `investigation_document`: the leads (≤ `max_leads`) and the Source
  Versions (≤ `max_documents`) the investigation took, counted against its budgets.
- `investigation_event`: **insert-only**: what happened, in order (created, task queued,
  started, paused, resumed, succeeded, skipped, cancelled, failed, budget reached, premise
  disproven, stopped, resumed after a budget stop).
- `claim_extraction.continues_id`: an extraction that continues a budget-exhausted one (its
  remaining passages, in the same run), so a resumed investigation doesn't send a passage
  twice.

Revision ID: 0023
Revises: 0022 (re-chained at merge)
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

_STOP_REASONS = (
    "'answered', 'no_new_independent_evidence', 'budget_exhausted', 'needs_review',"
    " 'premise_disproven'"
)
_TASK_STATUSES = (
    "'pending', 'queued', 'running', 'succeeded', 'skipped', 'cancelled', 'failed',"
    " 'budget_exhausted'"
)
_ROLES = "'scout', 'investigator', 'skeptic', 'financial_analyst', 'editor'"


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE investigation (
            id uuid PRIMARY KEY,
            theme text NOT NULL CHECK (theme <> ''),
            question text NOT NULL CHECK (btrim(question) <> ''),
            seed_company_ids uuid[] NOT NULL CHECK (cardinality(seed_company_ids) > 0),
            as_of timestamptz NOT NULL,
            bank_id text NOT NULL CHECK (bank_id <> ''),
            max_rounds smallint NOT NULL CHECK (max_rounds BETWEEN 1 AND 2),
            max_leads smallint NOT NULL CHECK (max_leads BETWEEN 1 AND 10),
            max_documents smallint NOT NULL CHECK (max_documents BETWEEN 1 AND 25),
            token_budget integer NOT NULL CHECK (token_budget > 0),
            round smallint NOT NULL DEFAULT 1 CHECK (round BETWEEN 1 AND max_rounds),
            run_id uuid UNIQUE REFERENCES run (id),
            status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'stopped')),
            stop_reason text CHECK (stop_reason IN ({_STOP_REASONS})),
            stop_detail text,
            research_card jsonb CHECK (jsonb_typeof(research_card) = 'object'),
            created_by text NOT NULL CHECK (btrim(created_by) <> ''),
            created_at timestamptz NOT NULL DEFAULT now(),
            stopped_at timestamptz,
            CHECK ((status = 'stopped') = (stop_reason IS NOT NULL)),
            CHECK ((status = 'stopped') = (stopped_at IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ix_investigation_created ON investigation (created_at DESC, id)")
    op.execute("""
        CREATE TABLE investigation_premise (
            id uuid PRIMARY KEY,
            investigation_id uuid NOT NULL REFERENCES investigation (id),
            key text NOT NULL CHECK (key <> ''),
            statement text NOT NULL CHECK (btrim(statement) <> ''),
            company_id uuid REFERENCES company (id),
            status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'disproven')),
            reason text,
            disproven_by text,
            disproven_at timestamptz,
            UNIQUE (investigation_id, key),
            CHECK ((status = 'disproven') = (disproven_at IS NOT NULL)),
            CHECK ((status = 'disproven') = (btrim(reason) <> '' AND disproven_by IS NOT NULL))
        )
    """)
    op.execute(f"""
        CREATE TABLE investigation_task (
            id uuid PRIMARY KEY,
            investigation_id uuid NOT NULL REFERENCES investigation (id),
            round smallint NOT NULL CHECK (round >= 1),
            position smallint NOT NULL CHECK (position >= 1),
            key text NOT NULL CHECK (key <> ''),
            role text NOT NULL CHECK (role IN ({_ROLES})),
            company_id uuid REFERENCES company (id),
            depends_on text[] NOT NULL DEFAULT '{{}}',
            premise_keys text[] NOT NULL DEFAULT '{{}}',
            status text NOT NULL DEFAULT 'pending' CHECK (status IN ({_TASK_STATUSES})),
            generation smallint NOT NULL DEFAULT 0 CHECK (generation >= 0),
            job_id uuid REFERENCES job (id),
            detail text,
            artifacts jsonb NOT NULL DEFAULT '{{}}' CHECK (jsonb_typeof(artifacts) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (investigation_id, round, key),
            UNIQUE (investigation_id, round, position),
            CHECK ((role = 'investigator') = (company_id IS NOT NULL)),
            CHECK (status IN ('pending', 'skipped', 'cancelled') OR job_id IS NOT NULL)
        )
    """)
    op.execute("""
        CREATE TABLE investigation_lead (
            investigation_id uuid NOT NULL REFERENCES investigation (id),
            lead_id uuid NOT NULL REFERENCES lead (id),
            rank smallint NOT NULL CHECK (rank BETWEEN 1 AND 10),
            discovery_id uuid NOT NULL REFERENCES discovery (id),
            added_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (investigation_id, lead_id),
            UNIQUE (investigation_id, rank)
        )
    """)
    op.execute("""
        CREATE TABLE investigation_document (
            investigation_id uuid NOT NULL REFERENCES investigation (id),
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            task_id uuid NOT NULL REFERENCES investigation_task (id),
            added_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (investigation_id, source_version_id)
        )
    """)
    op.execute("CREATE INDEX ix_investigation_document_task ON investigation_document (task_id)")
    op.execute("""
        CREATE TABLE investigation_event (
            seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            investigation_id uuid NOT NULL REFERENCES investigation (id),
            type text NOT NULL CHECK (type <> ''),
            round smallint,
            task_key text,
            detail jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(detail) = 'object'),
            at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_investigation_event ON investigation_event (investigation_id, seq)")
    op.execute("CREATE INDEX ix_investigation_event_type ON investigation_event (type)")
    op.execute("""
        CREATE FUNCTION investigation_event_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'investigation events are insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    triggers = {
        "investigation_event_no_update": "BEFORE UPDATE ON investigation_event FOR EACH ROW"
        " EXECUTE FUNCTION investigation_event_reject_change()",
        "investigation_event_no_delete": "BEFORE DELETE ON investigation_event FOR EACH ROW"
        " EXECUTE FUNCTION investigation_event_reject_change()",
        "investigation_event_no_truncate": "BEFORE TRUNCATE ON investigation_event"
        " FOR EACH STATEMENT EXECUTE FUNCTION investigation_event_reject_change()",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE investigation_event ENABLE ALWAYS TRIGGER {name}")
    op.execute(
        "ALTER TABLE claim_extraction ADD COLUMN continues_id uuid UNIQUE"
        " REFERENCES claim_extraction (id)"
    )
    op.execute(
        "REVOKE ALL ON investigation, investigation_premise, investigation_task,"
        " investigation_lead, investigation_document, investigation_event FROM PUBLIC"
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON investigation, investigation_premise,
                    investigation_task TO atlas_app;
                GRANT SELECT, INSERT ON investigation_lead, investigation_document,
                    investigation_event TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE claim_extraction DROP COLUMN continues_id")
    op.execute("DROP TABLE investigation_event")
    op.execute("DROP FUNCTION investigation_event_reject_change()")
    op.execute("DROP TABLE investigation_document")
    op.execute("DROP TABLE investigation_lead")
    op.execute("DROP TABLE investigation_task")
    op.execute("DROP TABLE investigation_premise")
    op.execute("DROP TABLE investigation")
