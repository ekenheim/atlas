"""Hypotheses: an investigation's result saved as a versioned, falsifiable research object
(spec §5.6, §8.1).

- `hypothesis`: one per saved investigation: its theme, related companies, §5.6 lifecycle
  status, author, first publication and next review times, and the Editor's drafting of
  version 1 (the `draft_hypothesis` job, its run, and whether it drafted or failed).
- `hypothesis_version`: the versions, numbered from 1. Content (thesis statement, mechanism,
  predictions, catalysts, falsifiers, required Evidence, alternatives, unresolved questions,
  findings citing Assertions, unsupported findings) is a JSON object whose SHA-256 is kept
  beside it, with its provenance (the investigation's run, the drafting run and Editor call).
  **A version never changes**: a trigger allows only the one publication stamp
  (`published_at`, `published_by`) on an unpublished version, and refuses every other update
  and every delete; so a published version is immutable and a correction is a new version.
- `hypothesis_transition`: **insert-only**: each lifecycle change (and publication), who made
  it and why.

Revision ID: 0027
Revises: 0023 (re-chained at merge)
"""

from alembic import op

revision = "0027"
down_revision = "0023"
branch_labels = None
depends_on = None

_STATUSES = (
    "'draft', 'researching', 'evidence_ready', 'reviewed', 'paper_tracking', 'closed',"
    " 'rejected', 'needs_more_evidence'"
)


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE hypothesis (
            id uuid PRIMARY KEY,
            theme_id text NOT NULL CHECK (theme_id <> ''),
            investigation_id uuid NOT NULL UNIQUE REFERENCES investigation (id),
            related_company_ids uuid[] NOT NULL DEFAULT '{{}}',
            status text NOT NULL DEFAULT 'draft' CHECK (status IN ({_STATUSES})),
            author text NOT NULL CHECK (btrim(author) <> ''),
            draft_status text NOT NULL DEFAULT 'queued'
                CHECK (draft_status IN ('queued', 'drafted', 'failed')),
            draft_job_id uuid NOT NULL REFERENCES job (id),
            draft_run_id uuid UNIQUE REFERENCES run (id),
            draft_error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            first_published_at timestamptz,
            next_review_at timestamptz,
            CHECK ((draft_status = 'failed') = (draft_error IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ix_hypothesis_created ON hypothesis (created_at DESC, id)")
    op.execute("""
        CREATE TABLE hypothesis_version (
            id uuid PRIMARY KEY,
            hypothesis_id uuid NOT NULL REFERENCES hypothesis (id),
            version integer NOT NULL CHECK (version >= 1),
            based_on_version integer CHECK (based_on_version >= 1 AND based_on_version < version),
            origin text NOT NULL CHECK (origin IN ('editor_draft', 'correction')),
            content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'object'),
            content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            provenance jsonb NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
            note text,
            created_by text NOT NULL CHECK (btrim(created_by) <> ''),
            created_at timestamptz NOT NULL DEFAULT now(),
            published_at timestamptz,
            published_by text,
            UNIQUE (hypothesis_id, version),
            CHECK ((published_at IS NULL) = (published_by IS NULL)),
            CHECK ((origin = 'editor_draft') = (based_on_version IS NULL))
        )
    """)
    op.execute("""
        CREATE FUNCTION hypothesis_version_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'hypothesis versions are never deleted: % is not allowed', TG_OP;
            END IF;
            IF OLD.published_at IS NOT NULL THEN
                RAISE EXCEPTION 'hypothesis version % is published and immutable', OLD.id;
            END IF;
            IF NEW.published_at IS NULL
                OR (NEW.id, NEW.hypothesis_id, NEW.version, NEW.based_on_version, NEW.origin,
                    NEW.content, NEW.content_sha256, NEW.provenance, NEW.note, NEW.created_by,
                    NEW.created_at)
                IS DISTINCT FROM
                   (OLD.id, OLD.hypothesis_id, OLD.version, OLD.based_on_version, OLD.origin,
                    OLD.content, OLD.content_sha256, OLD.provenance, OLD.note, OLD.created_by,
                    OLD.created_at)
            THEN
                RAISE EXCEPTION
                    'a hypothesis version never changes; only publishing it is allowed';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    guards = {
        "hypothesis_version_guard_update": "BEFORE UPDATE ON hypothesis_version FOR EACH ROW",
        "hypothesis_version_guard_delete": "BEFORE DELETE ON hypothesis_version FOR EACH ROW",
        "hypothesis_version_guard_truncate": "BEFORE TRUNCATE ON hypothesis_version"
        " FOR EACH STATEMENT",
    }
    for name, when in guards.items():
        op.execute(f"CREATE TRIGGER {name} {when} EXECUTE FUNCTION hypothesis_version_guard()")
        op.execute(f"ALTER TABLE hypothesis_version ENABLE ALWAYS TRIGGER {name}")
    op.execute(f"""
        CREATE TABLE hypothesis_transition (
            seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            hypothesis_id uuid NOT NULL REFERENCES hypothesis (id),
            from_status text NOT NULL CHECK (from_status IN ({_STATUSES})),
            to_status text NOT NULL CHECK (to_status IN ({_STATUSES})),
            action text NOT NULL CHECK (action IN ('transition', 'publish')),
            version integer,
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            note text,
            at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_hypothesis_transition ON hypothesis_transition (hypothesis_id, seq)"
    )
    op.execute("""
        CREATE FUNCTION hypothesis_transition_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'hypothesis transitions are insert-only: % is not allowed', TG_OP;
        END
        $$
    """)
    triggers = {
        "hypothesis_transition_no_update": "BEFORE UPDATE ON hypothesis_transition FOR EACH ROW",
        "hypothesis_transition_no_delete": "BEFORE DELETE ON hypothesis_transition FOR EACH ROW",
        "hypothesis_transition_no_truncate": "BEFORE TRUNCATE ON hypothesis_transition"
        " FOR EACH STATEMENT",
    }
    for name, when in triggers.items():
        op.execute(
            f"CREATE TRIGGER {name} {when} EXECUTE FUNCTION hypothesis_transition_reject_change()"
        )
        op.execute(f"ALTER TABLE hypothesis_transition ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON hypothesis, hypothesis_version, hypothesis_transition FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON hypothesis, hypothesis_version TO atlas_app;
                GRANT SELECT, INSERT ON hypothesis_transition TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE hypothesis_transition")
    op.execute("DROP FUNCTION hypothesis_transition_reject_change()")
    op.execute("DROP TABLE hypothesis_version")
    op.execute("DROP FUNCTION hypothesis_version_guard()")
    op.execute("DROP TABLE hypothesis")
