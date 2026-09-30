"""Triage audits (ticket 33): how often retention triage skips a section a full reading
would retain.

- `triage_audit_run`: one audit (`atlas triage audit`): what was asked (sample size, company,
  seed), the reader settings it describes (window size, windows per section, overlap) and the
  judge's (its rubric version, the characters it reads per call), the skipped sections it
  drew from (`population`) and each stratum (form x length band) with its population and
  how many it sampled, the drawn sample in judging order (`plan`, triage decision IDs), its
  job, its status and, once completed, the summary (miss rate with its Wilson interval, by
  category and length band, example misses).
- `triage_audit`: **insert-only**: one row per judged sample: the section (Source Version,
  anchor, heading, offsets, form, length band), the triage decision audited (its method,
  category and reason) and the windows the reader reads of it, the full-section judge's
  decision, category and reason (NULL with an `error` when it gave none), how many chunks it
  read, its role calls, and whether the two agree (`agreement` false: a miss).

Revision ID: 0040
Revises: 0039
"""

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE triage_audit_run (
            id uuid PRIMARY KEY,
            status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed')),
            sample_requested integer NOT NULL CHECK (sample_requested >= 1),
            company_slug text,
            seed integer NOT NULL,
            population integer NOT NULL CHECK (population >= 0),
            strata jsonb NOT NULL CHECK (jsonb_typeof(strata) = 'array'),
            plan uuid[] NOT NULL,
            judge_rubric_version text NOT NULL,
            triage_rubric_version text NOT NULL,
            excerpt_chars integer NOT NULL CHECK (excerpt_chars >= 1),
            windows_per_section integer NOT NULL CHECK (windows_per_section >= 1),
            window_overlap_chars integer NOT NULL CHECK (window_overlap_chars >= 0),
            judge_max_chars integer NOT NULL CHECK (judge_max_chars >= 1),
            job_id uuid NOT NULL,
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            summary jsonb CHECK (summary IS NULL OR jsonb_typeof(summary) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            CHECK ((status = 'completed') = (finished_at IS NOT NULL)),
            CHECK ((status = 'completed') = (summary IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ix_triage_audit_run_created ON triage_audit_run (created_at, id)")
    op.execute("""
        CREATE TABLE triage_audit (
            id uuid PRIMARY KEY,
            seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
            triage_audit_run_id uuid NOT NULL REFERENCES triage_audit_run (id),
            triage_decision_id uuid NOT NULL REFERENCES triage_decision (id),
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            section_anchor text NOT NULL,
            section_heading text,
            char_start integer NOT NULL CHECK (char_start >= 0),
            char_end integer NOT NULL,
            form text NOT NULL,
            length_band text NOT NULL,
            triage_decision text NOT NULL CHECK (triage_decision IN ('retain', 'skip')),
            triage_method text NOT NULL,
            triage_category text NOT NULL,
            triage_reason text NOT NULL,
            windows_read integer NOT NULL CHECK (windows_read >= 0),
            windows_total integer NOT NULL CHECK (windows_total >= 1),
            judge_decision text CHECK (judge_decision IN ('retain', 'skip')),
            judge_category text,
            judge_reason text,
            judge_chunks integer NOT NULL CHECK (judge_chunks >= 0),
            role_call_ids uuid[] NOT NULL,
            agreement boolean,
            error text,
            judged_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (triage_audit_run_id, triage_decision_id),
            CHECK (char_end > char_start),
            CHECK (windows_read <= windows_total),
            CHECK ((judge_decision IS NULL) = (error IS NOT NULL)),
            CHECK ((judge_decision IS NULL) = (agreement IS NULL)),
            CHECK ((judge_decision IS NULL) = (judge_category IS NULL)),
            CHECK ((judge_decision IS NULL) = (judge_reason IS NULL)),
            CHECK (agreement IS NULL OR agreement = (judge_decision = triage_decision))
        )
    """)
    op.execute("""
        CREATE TRIGGER triage_audit_no_change BEFORE UPDATE OR DELETE ON triage_audit
        FOR EACH ROW EXECUTE FUNCTION ledger_reject_change()
    """)
    op.execute("""
        CREATE TRIGGER triage_audit_no_truncate BEFORE TRUNCATE ON triage_audit
        FOR EACH STATEMENT EXECUTE FUNCTION ledger_reject_change()
    """)
    for trigger in ("no_change", "no_truncate"):
        op.execute(f"ALTER TABLE triage_audit ENABLE ALWAYS TRIGGER triage_audit_{trigger}")
    op.execute("REVOKE ALL ON triage_audit FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON triage_audit TO atlas_app;
                GRANT SELECT, INSERT, UPDATE ON triage_audit_run TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE triage_audit")
    op.execute("DROP TABLE triage_audit_run")
