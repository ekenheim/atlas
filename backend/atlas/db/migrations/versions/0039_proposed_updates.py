"""Proposed updates (spec §5.6, §5.7 "Contradiction flow"; ticket 21): later Evidence that
contradicts what a published Hypothesis version depends on flags the Hypothesis, and never
changes the version or its Research Snapshot.

- `hypothesis_dependency`: **insert-only**, written when a version is published: what the
  version depends on. `assertion` (its findings' Assertions), `claim` (the Claims they cite),
  `relationship` (the Relationships those Assertions support) and `source_version` (the Source
  Versions of their spans). The events that can contradict a version look it up here.
  Versions published before this migration get theirs from their content.
- `proposed_update`: one per (published version, contradicting event): the event
  (`trigger`, `trigger_key`), the contradicting Evidence, the findings it bears on, the
  Candidates it concerns, and the owner's resolution. `open` until the owner accepts it (a
  correction: `correction_version` is the new draft version) or dismisses it (with a
  reason). A trigger allows only that one resolution; every other UPDATE, and every DELETE and
  TRUNCATE, is refused.

Revision ID: 0039
Revises: 0037 (re-chained at merge)
"""

from alembic import op

revision = "0039"
down_revision = "0037"
branch_labels = None
depends_on = None

_KINDS = "'assertion', 'claim', 'relationship', 'source_version'"
_TRIGGERS = "'assertion_reviewed', 'relationship_rejected', 'source_revised', 'counterevidence'"


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE hypothesis_dependency (
            hypothesis_version_id uuid NOT NULL REFERENCES hypothesis_version (id),
            kind text NOT NULL CHECK (kind IN ({_KINDS})),
            ref_id uuid NOT NULL,
            PRIMARY KEY (hypothesis_version_id, kind, ref_id)
        )
    """)
    op.execute("CREATE INDEX ix_hypothesis_dependency_ref ON hypothesis_dependency (kind, ref_id)")
    op.execute("""
        CREATE FUNCTION hypothesis_dependency_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'hypothesis dependencies are insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    guards = {
        "hypothesis_dependency_no_update": "BEFORE UPDATE ON hypothesis_dependency FOR EACH ROW",
        "hypothesis_dependency_no_delete": "BEFORE DELETE ON hypothesis_dependency FOR EACH ROW",
        "hypothesis_dependency_no_truncate": "BEFORE TRUNCATE ON hypothesis_dependency"
        " FOR EACH STATEMENT",
    }
    for name, when in guards.items():
        op.execute(
            f"CREATE TRIGGER {name} {when} EXECUTE FUNCTION hypothesis_dependency_reject_change()"
        )
        op.execute(f"ALTER TABLE hypothesis_dependency ENABLE ALWAYS TRIGGER {name}")
    # Versions already published: their dependencies from their content (as at publication).
    op.execute("""
        INSERT INTO hypothesis_dependency (hypothesis_version_id, kind, ref_id)
        SELECT DISTINCT v.id, d.kind, d.ref_id
        FROM hypothesis_version v
        CROSS JOIN LATERAL jsonb_array_elements(v.content -> 'findings') f
        CROSS JOIN LATERAL (
            SELECT 'assertion' AS kind, (s ->> 'assertion_id')::uuid AS ref_id
            FROM jsonb_array_elements(f -> 'source_spans') s
            UNION ALL
            SELECT 'source_version', (s ->> 'source_version_id')::uuid
            FROM jsonb_array_elements(f -> 'source_spans') s
            UNION ALL
            SELECT 'claim', (c #>> '{}')::uuid FROM jsonb_array_elements(f -> 'claim_ids') c
        ) d
        WHERE v.published_at IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO hypothesis_dependency (hypothesis_version_id, kind, ref_id)
        SELECT DISTINCT d.hypothesis_version_id, 'relationship', ra.relationship_id
        FROM hypothesis_dependency d
        JOIN relationship_assertion ra ON ra.assertion_id = d.ref_id
        WHERE d.kind = 'assertion'
        ON CONFLICT DO NOTHING
    """)
    op.execute(f"""
        CREATE TABLE proposed_update (
            id uuid PRIMARY KEY,
            hypothesis_id uuid NOT NULL REFERENCES hypothesis (id),
            hypothesis_version_id uuid NOT NULL REFERENCES hypothesis_version (id),
            trigger text NOT NULL CHECK (trigger IN ({_TRIGGERS})),
            trigger_key text NOT NULL CHECK (btrim(trigger_key) <> ''),
            summary text NOT NULL CHECK (btrim(summary) <> ''),
            evidence jsonb NOT NULL
                CHECK (jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) > 0),
            affected_findings jsonb NOT NULL CHECK (jsonb_typeof(affected_findings) = 'array'),
            candidate_ids uuid[] NOT NULL DEFAULT '{{}}',
            detected_by_job_id uuid REFERENCES job (id),
            state text NOT NULL DEFAULT 'open'
                CHECK (state IN ('open', 'accepted', 'dismissed')),
            resolved_by text CHECK (btrim(resolved_by) <> ''),
            resolved_at timestamptz,
            resolution_note text,
            dismiss_reason text CHECK (btrim(dismiss_reason) <> ''),
            correction_version integer CHECK (correction_version >= 2),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (hypothesis_version_id, trigger_key),
            CHECK ((state = 'open') = (resolved_at IS NULL)),
            CHECK ((resolved_at IS NULL) = (resolved_by IS NULL)),
            CHECK ((state = 'dismissed') = (dismiss_reason IS NOT NULL)),
            CHECK ((state = 'accepted') = (correction_version IS NOT NULL))
        )
    """)
    op.execute(
        "CREATE INDEX ix_proposed_update_hypothesis ON proposed_update"
        " (hypothesis_id, created_at, id)"
    )
    op.execute(
        "CREATE INDEX ix_proposed_update_candidates ON proposed_update USING gin (candidate_ids)"
    )
    op.execute("""
        CREATE FUNCTION proposed_update_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'proposed updates are never deleted: % is not allowed', TG_OP;
            END IF;
            IF OLD.state <> 'open' THEN
                RAISE EXCEPTION 'proposed update % is already %', OLD.id, OLD.state;
            END IF;
            IF NEW.state = 'open'
                OR (NEW.id, NEW.hypothesis_id, NEW.hypothesis_version_id, NEW.trigger,
                    NEW.trigger_key, NEW.summary, NEW.evidence, NEW.affected_findings,
                    NEW.candidate_ids, NEW.detected_by_job_id, NEW.created_at)
                IS DISTINCT FROM
                   (OLD.id, OLD.hypothesis_id, OLD.hypothesis_version_id, OLD.trigger,
                    OLD.trigger_key, OLD.summary, OLD.evidence, OLD.affected_findings,
                    OLD.candidate_ids, OLD.detected_by_job_id, OLD.created_at)
            THEN
                RAISE EXCEPTION
                    'a proposed update never changes; only resolving it once is allowed';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    triggers = {
        "proposed_update_guard_update": "BEFORE UPDATE ON proposed_update FOR EACH ROW",
        "proposed_update_guard_delete": "BEFORE DELETE ON proposed_update FOR EACH ROW",
        "proposed_update_guard_truncate": "BEFORE TRUNCATE ON proposed_update FOR EACH STATEMENT",
    }
    for name, when in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {when} EXECUTE FUNCTION proposed_update_guard()")
        op.execute(f"ALTER TABLE proposed_update ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON hypothesis_dependency, proposed_update FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON hypothesis_dependency TO atlas_app;
                GRANT SELECT, INSERT, UPDATE ON proposed_update TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE proposed_update")
    op.execute("DROP FUNCTION proposed_update_guard()")
    op.execute("DROP TABLE hypothesis_dependency")
    op.execute("DROP FUNCTION hypothesis_dependency_reject_change()")
