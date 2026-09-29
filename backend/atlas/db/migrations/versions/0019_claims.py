"""Claims: the Investigator's extractions and the outcome of every Claim it proposed.

- `claim_extraction`: one per `extract_claims` job: the run its role calls belong to, the
  Source Versions asked for, the passages chosen (stored, so a resumed job sends the same
  ones), and progress by batch (one Investigator call per batch).
- `claim`: one per proposed Claim, **insert-only**: what was proposed (`proposed`, as the
  model answered), the resolved subject/object, the absolute span in the parsed text, and the
  outcome: `accepted` with the Assertion it became, or `rejected` with a reason code and
  message (`claim_rejected`). A Claim's outcome never changes; a later review acts on the
  Assertion (or, in ticket 12, the Relationship).

Revision ID: 0019
Revises: 0015 (re-chained at merge)
"""

from alembic import op

revision = "0019"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE claim_extraction (
            id uuid PRIMARY KEY,
            job_id uuid NOT NULL UNIQUE REFERENCES job (id),
            run_id uuid NOT NULL REFERENCES run (id),
            source_version_ids uuid[] NOT NULL CHECK (cardinality(source_version_ids) > 0),
            question text CHECK (btrim(question) <> ''),
            passages jsonb NOT NULL CHECK (jsonb_typeof(passages) = 'array'),
            passages_dropped integer NOT NULL DEFAULT 0 CHECK (passages_dropped >= 0),
            skipped jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(skipped) = 'array'),
            passages_per_call integer NOT NULL CHECK (passages_per_call > 0),
            batches_total integer NOT NULL CHECK (batches_total >= 0),
            batches_done integer NOT NULL DEFAULT 0
                CHECK (batches_done BETWEEN 0 AND batches_total),
            batches_quarantined integer NOT NULL DEFAULT 0
                CHECK (batches_quarantined BETWEEN 0 AND batches_done),
            status text NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'completed', 'budget_exhausted')),
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            CHECK ((status = 'running') = (finished_at IS NULL))
        )
    """)
    op.execute("CREATE INDEX ix_claim_extraction_run ON claim_extraction (run_id)")
    op.execute("""
        CREATE TABLE claim (
            id uuid PRIMARY KEY,
            extraction_id uuid NOT NULL REFERENCES claim_extraction (id),
            run_id uuid NOT NULL REFERENCES run (id),
            role_call_id uuid NOT NULL REFERENCES role_call (id),
            ordinal integer NOT NULL CHECK (ordinal >= 0),
            proposed jsonb NOT NULL,
            passage_id text NOT NULL,
            source_version_id uuid REFERENCES source_version (id),
            subject_company_id uuid REFERENCES company (id),
            predicate text NOT NULL,
            object_company_id uuid REFERENCES company (id),
            object_text text,
            product text,
            layer text NOT NULL,
            quote text NOT NULL,
            span_start integer CHECK (span_start >= 0),
            span_end integer,
            epistemic_type text NOT NULL,
            directional_cue text,
            outcome text NOT NULL CHECK (outcome IN ('accepted', 'rejected')),
            reason_code text CHECK (btrim(reason_code) <> ''),
            reason text CHECK (btrim(reason) <> ''),
            assertion_id uuid UNIQUE REFERENCES assertion (id),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (role_call_id, ordinal),
            CHECK ((span_start IS NULL) = (span_end IS NULL)),
            CHECK (span_end >= span_start),
            CHECK ((outcome = 'accepted') = (assertion_id IS NOT NULL)),
            CHECK ((outcome = 'rejected') = (reason_code IS NOT NULL)),
            CHECK ((reason_code IS NULL) = (reason IS NULL))
        )
    """)
    op.execute("CREATE INDEX ix_claim_extraction ON claim (extraction_id, created_at, id)")
    op.execute("CREATE INDEX ix_claim_source_version ON claim (source_version_id)")
    op.execute("CREATE INDEX ix_claim_outcome ON claim (outcome, reason_code)")
    op.execute("""
        CREATE FUNCTION claim_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'claim outcomes are insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    triggers = {
        "claim_no_update": "BEFORE UPDATE ON claim FOR EACH ROW"
        " EXECUTE FUNCTION claim_reject_change()",
        "claim_no_delete": "BEFORE DELETE ON claim FOR EACH ROW"
        " EXECUTE FUNCTION claim_reject_change()",
        "claim_no_truncate": "BEFORE TRUNCATE ON claim FOR EACH STATEMENT"
        " EXECUTE FUNCTION claim_reject_change()",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE claim ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON claim_extraction, claim FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON claim_extraction TO atlas_app;
                GRANT SELECT, INSERT ON claim TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE claim")
    op.execute("DROP FUNCTION claim_reject_change()")
    op.execute("DROP TABLE claim_extraction")
