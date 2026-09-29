"""Retention triage: a decision per section before anything is retained (ticket 30).

- `triage_decision`: whether a section of a Source Version is worth retaining into the
  research bank (`retain` or `skip`), with its value category, a one-line reason and how it
  was decided (`method`):
  - `rule`: a deterministic pre-filter rule (known boilerplate headings, empty sections);
  - `inherited`: the section's content hash equals a section of the previous comparable
    Source Version, whose decision it copies (`inherited_from_id`);
  - `role`: the Triage role's answer (`role_call_id`);
  - `default`: the role returned no decision for the section, so it is retained;
  - `on_demand`: a person or an investigation asked for the section to be retained
    (`requested_by`, and `investigation_id` when an investigation asked), with why.
  Each row records the section's offsets and sectioner version, the SHA-256 of its text, the
  rubric (the Triage prompt) version and the pre-filter rules version.

Insert-only (never updated or deleted, like the source ledger): a later decision for the
same section (an on-demand retain of a skipped one) is a new row, and the section's
**effective** decision is its latest (`seq`).

Revision ID: 0033
Revises: 0028 (re-chained at merge)
"""

from alembic import op

revision = "0033"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE triage_decision (
            id uuid PRIMARY KEY,
            seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            section_anchor text NOT NULL CHECK (btrim(section_anchor) <> ''),
            section_heading text,
            char_start integer NOT NULL CHECK (char_start >= 0),
            char_end integer NOT NULL,
            sectioner_version text NOT NULL,
            content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            decision text NOT NULL CHECK (decision IN ('retain', 'skip')),
            category text NOT NULL CHECK (btrim(category) <> ''),
            reason text NOT NULL CHECK (btrim(reason) <> ''),
            method text NOT NULL
                CHECK (method IN ('rule', 'inherited', 'role', 'default', 'on_demand')),
            rubric_version text NOT NULL,
            rules_version text NOT NULL,
            role_call_id uuid REFERENCES role_call (id),
            inherited_from_id uuid REFERENCES triage_decision (id),
            requested_by text,
            investigation_id uuid REFERENCES investigation (id),
            decided_at timestamptz NOT NULL DEFAULT now(),
            CHECK (char_end > char_start),
            CHECK ((method = 'role') = (role_call_id IS NOT NULL)),
            CHECK ((method = 'inherited') = (inherited_from_id IS NOT NULL)),
            CHECK ((method = 'on_demand') = (requested_by IS NOT NULL)),
            CHECK (method <> 'on_demand' OR decision = 'retain'),
            CHECK (investigation_id IS NULL OR method = 'on_demand')
        )
    """)
    op.execute(
        "CREATE INDEX ix_triage_decision_section ON triage_decision"
        " (source_version_id, section_anchor, seq)"
    )
    op.execute("CREATE INDEX ix_triage_decision_content ON triage_decision (content_sha256)")
    op.execute("""
        CREATE TRIGGER triage_decision_no_change BEFORE UPDATE OR DELETE ON triage_decision
        FOR EACH ROW EXECUTE FUNCTION ledger_reject_change()
    """)
    op.execute("""
        CREATE TRIGGER triage_decision_no_truncate BEFORE TRUNCATE ON triage_decision
        FOR EACH STATEMENT EXECUTE FUNCTION ledger_reject_change()
    """)
    for trigger in ("no_change", "no_truncate"):
        op.execute(f"ALTER TABLE triage_decision ENABLE ALWAYS TRIGGER triage_decision_{trigger}")
    op.execute("REVOKE ALL ON triage_decision FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON triage_decision TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE triage_decision")
