"""The Skeptic: its independent counterevidence search and what it found (ticket 15).

- `skeptic_search`: one per Skeptic task: the run and the plan call, the discovery holding its
  own web queries (Tier C leads only), the Source Versions it chose to read (from the catalog
  or from its search results) and why, the passages it sent, and its progress per batch, so a
  retried or resumed task continues where it stopped.
- `counterevidence`: **insert-only**: every item the Skeptic proposed, accepted or rejected
  (with its reason), like a Claim. An accepted item is an Assertion (predicate
  `counterevidence`) and records its Evidence Family and whether that family is independent of
  the supporting Claims' families. Memory and other roles' outputs can't be witnesses: an item
  must quote a passage of a Source Version the Skeptic chose.

Revision ID: 0030
Revises: 0028 (re-chained at merge)
"""

from alembic import op

revision = "0030"
down_revision = "0028"
branch_labels = None
depends_on = None

_CHECKLIST = (
    "'substitutes', 'second_sources', 'capacity_additions', 'inventory_cycle',"
    " 'dilution_financing', 'customer_concentration'"
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE skeptic_search (
            id uuid PRIMARY KEY,
            investigation_id uuid NOT NULL REFERENCES investigation (id),
            task_id uuid NOT NULL UNIQUE REFERENCES investigation_task (id),
            run_id uuid NOT NULL REFERENCES run (id),
            phase text NOT NULL DEFAULT 'planning'
                CHECK (phase IN ('planning', 'searching', 'reading', 'completed')),
            plan_role_call_id uuid REFERENCES role_call (id),
            discovery_id uuid REFERENCES discovery (id),
            queries_proposed integer CHECK (queries_proposed >= 0),
            documents_proposed integer CHECK (documents_proposed >= 0),
            documents jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(documents) = 'array'),
            documents_dropped integer NOT NULL DEFAULT 0 CHECK (documents_dropped >= 0),
            passages jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(passages) = 'array'),
            passages_dropped integer NOT NULL DEFAULT 0 CHECK (passages_dropped >= 0),
            passages_per_call integer NOT NULL CHECK (passages_per_call > 0),
            batches_total integer NOT NULL DEFAULT 0 CHECK (batches_total >= 0),
            batches_done integer NOT NULL DEFAULT 0
                CHECK (batches_done BETWEEN 0 AND batches_total),
            batches_quarantined integer NOT NULL DEFAULT 0 CHECK (batches_quarantined >= 0),
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            CHECK ((phase = 'completed') = (finished_at IS NOT NULL))
        )
    """)
    op.execute(f"""
        CREATE TABLE counterevidence (
            id uuid PRIMARY KEY,
            search_id uuid NOT NULL REFERENCES skeptic_search (id),
            investigation_id uuid NOT NULL REFERENCES investigation (id),
            run_id uuid NOT NULL REFERENCES run (id),
            role_call_id uuid NOT NULL REFERENCES role_call (id),
            batch integer NOT NULL CHECK (batch >= 0),
            ordinal integer NOT NULL CHECK (ordinal >= 0),
            proposed jsonb NOT NULL CHECK (jsonb_typeof(proposed) = 'object'),
            checklist_item text NOT NULL,
            passage_id text NOT NULL,
            source_version_id uuid REFERENCES source_version (id),
            subject_company_id uuid REFERENCES company (id),
            statement text NOT NULL,
            quote text NOT NULL,
            span_start integer CHECK (span_start >= 0),
            span_end integer CHECK (span_end >= span_start),
            epistemic_type text NOT NULL,
            contradicts_claim_ids uuid[] NOT NULL DEFAULT '{{}}',
            disproves_premise text,
            outcome text NOT NULL CHECK (outcome IN ('accepted', 'rejected')),
            reason_code text,
            reason text,
            assertion_id uuid UNIQUE REFERENCES assertion (id),
            evidence_family text,
            independent boolean,
            independence_detail text,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (search_id, batch, ordinal),
            CHECK ((outcome = 'accepted') = (assertion_id IS NOT NULL)),
            CHECK ((outcome = 'accepted') = (independent IS NOT NULL)),
            CHECK ((outcome = 'accepted') = (evidence_family IS NOT NULL)),
            CHECK ((outcome = 'rejected') = (reason_code IS NOT NULL)),
            CHECK (outcome = 'rejected' OR checklist_item IN ({_CHECKLIST}))
        )
    """)
    op.execute(
        "CREATE INDEX ix_counterevidence_investigation"
        " ON counterevidence (investigation_id, created_at, id)"
    )
    op.execute("""
        CREATE FUNCTION counterevidence_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'counterevidence is insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    triggers = {
        "counterevidence_no_update": "BEFORE UPDATE ON counterevidence FOR EACH ROW"
        " EXECUTE FUNCTION counterevidence_reject_change()",
        "counterevidence_no_delete": "BEFORE DELETE ON counterevidence FOR EACH ROW"
        " EXECUTE FUNCTION counterevidence_reject_change()",
        "counterevidence_no_truncate": "BEFORE TRUNCATE ON counterevidence"
        " FOR EACH STATEMENT EXECUTE FUNCTION counterevidence_reject_change()",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE counterevidence ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON skeptic_search, counterevidence FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON skeptic_search TO atlas_app;
                GRANT SELECT, INSERT ON counterevidence TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE counterevidence")
    op.execute("DROP FUNCTION counterevidence_reject_change()")
    op.execute("DROP TABLE skeptic_search")
