"""Relationships: typed, directed, layer-tagged edges backed by Assertions, and their review.

- `relationship`: one per edge, identified by (subject, predicate, object, layer): the object
  is a company, or a product/material/technology named in text (`object_key` is the company
  ID or the casefolded text). Its `review_state` is `machine_reviewed` or
  `needs_human_review` (set by machine review) or `approved`/`rejected` (the owner's
  decision, with who, when and a note). Only the review columns ever change; the identity is
  fixed and a Relationship is never deleted.
- `relationship_assertion`: the Assertions supporting an edge (§5.5
  `supporting_assertion_ids[]`); an Assertion supports at most one. Insert-only.
- `relationship_review`: the machine review of one Assertion, **insert-only**, at most one
  per Assertion: the deterministic checks (verbatim span, Tier A, directional language with
  its cue and hedge), the Reviewer's answer (or why there is none), and the outcome with its
  reason codes. `not_eligible` Assertions (off-whitelist predicate, no layer, co-mention)
  have no Relationship.
- `relationship_review_job`: a `review_relationships` job's run, so a retried job keeps
  calling the Reviewer in the same run.

Revision ID: 0022
Revises: 0018 (re-chained at merge)
"""

from alembic import op

revision = "0022"
down_revision = "0018"
branch_labels = None
depends_on = None

_PREDICATES = (
    "'manufactures', 'supplies', 'buys_from', 'uses_material', 'owns', 'competes_with',"
    " 'substitutes_for', 'expands_capacity_for', 'depends_on'"
)
_LAYERS = "'substrate', 'epi', 'chip-laser', 'dsp', 'module', 'contract-manufacturing', 'system'"
_INSERT_ONLY = ("relationship_assertion", "relationship_review")


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE relationship (
            id uuid PRIMARY KEY,
            subject_company_id uuid NOT NULL REFERENCES company (id),
            predicate text NOT NULL CHECK (predicate IN ({_PREDICATES})),
            object_company_id uuid REFERENCES company (id),
            object_text text CHECK (btrim(object_text) <> ''),
            object_key text NOT NULL CHECK (object_key <> ''),
            layer text NOT NULL CHECK (layer IN ({_LAYERS})),
            review_state text NOT NULL CHECK (
                review_state IN ('machine_reviewed', 'needs_human_review', 'approved', 'rejected')
            ),
            reviewed_by text,
            reviewed_at timestamptz,
            review_note text CHECK (btrim(review_note) <> ''),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (subject_company_id, predicate, object_key, layer),
            CHECK ((object_company_id IS NULL) <> (object_text IS NULL)),
            CHECK (object_company_id IS DISTINCT FROM subject_company_id),
            CHECK ((review_state IN ('approved', 'rejected'))
                   = (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)),
            CHECK (review_note IS NULL OR reviewed_by IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX ix_relationship_state ON relationship (review_state, created_at)")
    op.execute("CREATE INDEX ix_relationship_object ON relationship (object_company_id)")
    op.execute("""
        CREATE TABLE relationship_assertion (
            assertion_id uuid PRIMARY KEY REFERENCES assertion (id),
            relationship_id uuid NOT NULL REFERENCES relationship (id),
            added_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_relationship_assertion ON relationship_assertion"
        " (relationship_id, added_at)"
    )
    op.execute("""
        CREATE TABLE relationship_review_job (
            job_id uuid PRIMARY KEY REFERENCES job (id),
            run_id uuid NOT NULL REFERENCES run (id),
            owns_run boolean NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE relationship_review (
            id uuid PRIMARY KEY,
            assertion_id uuid NOT NULL UNIQUE REFERENCES assertion (id),
            relationship_id uuid REFERENCES relationship (id),
            job_id uuid REFERENCES job (id),
            run_id uuid REFERENCES run (id),
            role_call_id uuid REFERENCES role_call (id),
            verbatim_span boolean,
            tier_a boolean,
            directional_language text
                CHECK (directional_language IN ('explicit', 'hedged', 'absent')),
            directional_cue text,
            hedge text,
            reviewer_status text NOT NULL
                CHECK (reviewer_status IN ('answered', 'skipped', 'quarantined', 'no_answer')),
            reviewer_verdict text
                CHECK (reviewer_verdict IN ('confirmed', 'rejected', 'uncertain')),
            reviewer_direction text CHECK (
                reviewer_direction IN ('as_proposed', 'reversed', 'undirected', 'not_stated')
            ),
            reviewer_layer text CHECK (reviewer_layer IN ('correct', 'wrong', 'unclear')),
            reviewer_suggested_layer text,
            reviewer_reasoning text,
            outcome text NOT NULL
                CHECK (outcome IN ('machine_reviewed', 'needs_human_review', 'not_eligible')),
            reasons text[] NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((outcome = 'not_eligible') = (relationship_id IS NULL)),
            CHECK ((outcome = 'machine_reviewed') = (cardinality(reasons) = 0)),
            CHECK ((reviewer_status = 'answered') = (reviewer_verdict IS NOT NULL)),
            CHECK ((reviewer_verdict IS NULL) = (reviewer_direction IS NULL)),
            CHECK ((reviewer_verdict IS NULL) = (reviewer_layer IS NULL)),
            CHECK (outcome <> 'machine_reviewed' OR reviewer_status = 'answered')
        )
    """)
    op.execute(
        "CREATE INDEX ix_relationship_review_relationship ON relationship_review"
        " (relationship_id, created_at)"
    )
    op.execute("CREATE INDEX ix_relationship_review_outcome ON relationship_review (outcome)")
    op.execute("""
        CREATE FUNCTION relationship_guard_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.id, NEW.subject_company_id, NEW.predicate, NEW.object_company_id,
                NEW.object_text, NEW.object_key, NEW.layer, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.subject_company_id, OLD.predicate, OLD.object_company_id,
                OLD.object_text, OLD.object_key, OLD.layer, OLD.created_at) THEN
                RAISE EXCEPTION 'a relationship''s identity is immutable; only its review changes';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    triggers = [
        (
            "relationship",
            "relationship_identity",
            "BEFORE UPDATE ON relationship FOR EACH ROW"
            " EXECUTE FUNCTION relationship_guard_update()",
        ),
        (
            "relationship",
            "relationship_no_delete",
            "BEFORE DELETE ON relationship FOR EACH ROW EXECUTE FUNCTION ledger_reject_change()",
        ),
        (
            "relationship",
            "relationship_no_truncate",
            "BEFORE TRUNCATE ON relationship FOR EACH STATEMENT"
            " EXECUTE FUNCTION ledger_reject_change()",
        ),
    ]
    for table in _INSERT_ONLY:
        triggers += [
            (
                table,
                f"{table}_no_change",
                f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW"
                " EXECUTE FUNCTION ledger_reject_change()",
            ),
            (
                table,
                f"{table}_no_truncate",
                f"BEFORE TRUNCATE ON {table} FOR EACH STATEMENT"
                " EXECUTE FUNCTION ledger_reject_change()",
            ),
        ]
    for table, name, definition in triggers:
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {name}")
    tables = ("relationship", "relationship_review_job", *_INSERT_ONLY)
    op.execute(f"REVOKE ALL ON {', '.join(tables)} FROM PUBLIC")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON relationship TO atlas_app;
                GRANT SELECT, INSERT ON relationship_review_job, {", ".join(_INSERT_ONLY)}
                    TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE relationship_review")
    op.execute("DROP TABLE relationship_review_job")
    op.execute("DROP TABLE relationship_assertion")
    op.execute("DROP TABLE relationship")
    op.execute("DROP FUNCTION relationship_guard_update()")
