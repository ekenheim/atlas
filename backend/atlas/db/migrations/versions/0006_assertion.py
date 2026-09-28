"""Assertions (spec Part A, Assertions; build plan §5.4; spec stories 37-42).

`assertion`: a statement bound to one Source Version and an exact quote span of its
parsed text, with an epistemic type and a review state (`verification_status`).

Invariants the database enforces (the service checks the same rules first, so callers
get a clear error rather than a database exception):
- The statement is immutable: every column except the review columns
  (`verification_status`, `reviewer_id`, `reviewed_at`, `superseded_by`) never changes.
  A correction is a new Assertion plus supersession, never an edit.
- A new Assertion is `unreviewed`, and cites a Source Version that has parsed text.
- `span_end - span_start` is the quote's length in characters. Whether the quote occurs
  at those offsets of the archived parse is checked by the service, which can read the
  archive; the database cannot.
- Review transitions: `unreviewed`, `corroborated` and `disputed` are open;
  `rejected` and `superseded` are final. A review never returns to `unreviewed` and never
  repeats the current state. Reviewed rows carry their reviewer and review time.
- `superseded_by` is set exactly when the status is `superseded`, names another
  Assertion, and that successor is not itself rejected or superseded (so chains of
  supersession never form a cycle).
- No DELETE, no TRUNCATE.

The protective triggers are ENABLE ALWAYS, like the audit trail's (migration 0002).

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_STATES = "'unreviewed', 'corroborated', 'disputed', 'rejected', 'superseded'"
_EPISTEMIC_TYPES = (
    "'direct_source_statement', 'company_claim', 'third_party_report',"
    " 'agent_inference', 'quantitative_derived'"
)
# Every column that is not a review column.
_STATEMENT = (
    "id, subject_company_id, predicate, object_company_id, value_json, source_version_id,"
    " quote, span_start, span_end, page_or_anchor, event_start, event_end, epistemic_type,"
    " independence_family_id, extracted_at, extractor_version, created_by"
)


def _columns(prefix: str) -> str:
    return ", ".join(f"{prefix}.{column.strip()}" for column in _STATEMENT.split(","))


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE assertion (
            id uuid PRIMARY KEY,
            subject_company_id uuid NOT NULL REFERENCES company (id),
            predicate text NOT NULL CHECK (btrim(predicate) <> ''),
            object_company_id uuid REFERENCES company (id),
            value_json jsonb,
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            quote text NOT NULL CHECK (quote <> ''),
            -- Character (code point) offsets into the parsed text: [span_start, span_end).
            span_start integer NOT NULL CHECK (span_start >= 0),
            span_end integer NOT NULL,
            page_or_anchor text CHECK (btrim(page_or_anchor) <> ''),
            event_start timestamptz,
            event_end timestamptz CHECK (event_end >= event_start),
            epistemic_type text NOT NULL CHECK (epistemic_type IN ({_EPISTEMIC_TYPES})),
            verification_status text NOT NULL DEFAULT 'unreviewed'
                CHECK (verification_status IN ({_STATES})),
            -- An Evidence Family (Phase 3); null until then.
            independence_family_id uuid,
            extracted_at timestamptz NOT NULL DEFAULT now(),
            extractor_version text NOT NULL CHECK (btrim(extractor_version) <> ''),
            created_by text NOT NULL CHECK (btrim(created_by) <> ''),
            reviewer_id text CHECK (btrim(reviewer_id) <> ''),
            reviewed_at timestamptz,
            superseded_by uuid REFERENCES assertion (id),
            CHECK (span_end - span_start = char_length(quote)),
            CHECK ((verification_status = 'unreviewed') = (reviewer_id IS NULL)),
            CHECK ((verification_status = 'unreviewed') = (reviewed_at IS NULL)),
            CHECK ((verification_status = 'superseded') = (superseded_by IS NOT NULL)),
            CHECK (superseded_by <> id)
        )
    """)
    op.execute("CREATE INDEX assertion_subject ON assertion (subject_company_id, extracted_at, id)")
    op.execute(
        "CREATE INDEX assertion_object ON assertion (object_company_id, extracted_at, id)"
        " WHERE object_company_id IS NOT NULL"
    )
    op.execute("CREATE INDEX assertion_source_version ON assertion (source_version_id)")
    op.execute("CREATE INDEX assertion_status ON assertion (verification_status, extracted_at)")
    op.execute("CREATE INDEX assertion_superseded_by ON assertion (superseded_by)")

    op.execute("""
        CREATE FUNCTION assertion_guard_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.verification_status <> 'unreviewed' THEN
                RAISE EXCEPTION 'a new assertion is unreviewed, not %', NEW.verification_status;
            END IF;
            IF NOT EXISTS (
                SELECT FROM source_version
                WHERE id = NEW.source_version_id AND parse_status IN ('parsed', 'incomplete')
            ) THEN
                RAISE EXCEPTION 'an assertion must cite a source version with parsed text';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute(f"""
        CREATE FUNCTION assertion_guard_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF ({_columns("NEW")}) IS DISTINCT FROM ({_columns("OLD")}) THEN
                RAISE EXCEPTION 'assertion statement columns are immutable';
            END IF;
            IF OLD.verification_status IN ('rejected', 'superseded') THEN
                RAISE EXCEPTION 'assertion review is final (%)', OLD.verification_status;
            END IF;
            IF NEW.verification_status = 'unreviewed'
               OR NEW.verification_status = OLD.verification_status THEN
                RAISE EXCEPTION 'assertion review % -> % is not a transition',
                    OLD.verification_status, NEW.verification_status;
            END IF;
            IF NEW.superseded_by IS NOT NULL AND NOT EXISTS (
                SELECT FROM assertion
                WHERE id = NEW.superseded_by
                  AND verification_status NOT IN ('rejected', 'superseded')
            ) THEN
                RAISE EXCEPTION 'an assertion is superseded only by a live assertion';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE FUNCTION assertion_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'assertions are never removed: % is not allowed', TG_OP;
        END
        $$
    """)
    triggers = {
        "assertion_new": "BEFORE INSERT ON assertion FOR EACH ROW"
        " EXECUTE FUNCTION assertion_guard_insert()",
        "assertion_review": "BEFORE UPDATE ON assertion FOR EACH ROW"
        " EXECUTE FUNCTION assertion_guard_update()",
        "assertion_no_delete": "BEFORE DELETE ON assertion FOR EACH ROW"
        " EXECUTE FUNCTION assertion_reject_change()",
        "assertion_no_truncate": "BEFORE TRUNCATE ON assertion FOR EACH STATEMENT"
        " EXECUTE FUNCTION assertion_reject_change()",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE assertion ENABLE ALWAYS TRIGGER {name}")

    op.execute("REVOKE ALL ON assertion FROM PUBLIC")
    # The runtime role (see migration 0002): Assertions are inserted, then reviewed.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON assertion TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE assertion")
    op.execute("DROP FUNCTION assertion_reject_change()")
    op.execute("DROP FUNCTION assertion_guard_update()")
    op.execute("DROP FUNCTION assertion_guard_insert()")
