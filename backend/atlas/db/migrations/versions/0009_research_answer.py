"""Research answers: stored reflect answers with their resolved citations (spec Part B
"Schema"; stories 18-25).

- `research_answer`: one row per reflect question: the question, its applied scope (company
  and theme IDs and the strict tags sent), the optional response schema, and once the
  `reflect` job has answered: the answer text, the structured output and its error, the raw
  citations as Hindsight returned them, every citation with its resolved state, the quote
  normalization rule used, and the run that produced it. `job_id` is the reflect job's
  deterministic ID (enqueued right after the row commits, so it has no foreign key).

Invariants the database enforces:
- A `completed` answer has its text, citations, raw citations, quote rule and answer time;
  a `failed` one has its error. Structured output (or its error) needs a response schema.
- Only a `pending` answer changes, and only its outcome columns: the question, scope,
  schema, bank and job never change, a `completed` or `failed` answer is final, and rows are
  never deleted.

Revision ID: 0009
Revises: 0007 (re-chained at merge)
"""

from alembic import op

revision = "0009"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE research_answer (
            id uuid PRIMARY KEY,
            bank_id text NOT NULL CHECK (btrim(bank_id) <> ''),
            question text NOT NULL CHECK (btrim(question) <> ''),
            scope jsonb NOT NULL CHECK (jsonb_typeof(scope) = 'object'),
            response_schema jsonb CHECK (jsonb_typeof(response_schema) = 'object'),
            status text NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
            answer_text text,
            structured_output jsonb,
            structured_output_error text,
            raw_citations jsonb CHECK (jsonb_typeof(raw_citations) = 'array'),
            citations jsonb CHECK (jsonb_typeof(citations) = 'array'),
            quote_rule text CHECK (btrim(quote_rule) <> ''),
            run_id uuid REFERENCES run (id),
            job_id uuid NOT NULL,
            error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            answered_at timestamptz,
            CHECK ((status = 'completed') = (answer_text IS NOT NULL AND citations IS NOT NULL
                AND raw_citations IS NOT NULL AND quote_rule IS NOT NULL
                AND answered_at IS NOT NULL)),
            CHECK ((status = 'failed') = (error IS NOT NULL)),
            CHECK (response_schema IS NOT NULL
                OR (structured_output IS NULL AND structured_output_error IS NULL))
        )
    """)
    op.execute("CREATE INDEX research_answer_created ON research_answer (created_at, id)")
    op.execute("CREATE UNIQUE INDEX research_answer_job ON research_answer (job_id)")

    op.execute("""
        CREATE FUNCTION research_answer_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'research_answer rows are never removed (% is not allowed)', TG_OP;
            END IF;
            IF OLD.status <> 'pending' THEN
                RAISE EXCEPTION 'a % research answer is final', OLD.status;
            END IF;
            IF (NEW.id, NEW.bank_id, NEW.question, NEW.scope, NEW.response_schema, NEW.job_id,
                NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.bank_id, OLD.question, OLD.scope, OLD.response_schema, OLD.job_id,
                OLD.created_at)
            THEN
                RAISE EXCEPTION 'a research answer''s question, scope and schema are immutable';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER research_answer_guard BEFORE UPDATE OR DELETE ON research_answer
        FOR EACH ROW EXECUTE FUNCTION research_answer_guard()
    """)
    op.execute("""
        CREATE TRIGGER research_answer_no_truncate BEFORE TRUNCATE ON research_answer
        FOR EACH STATEMENT EXECUTE FUNCTION research_answer_guard()
    """)
    for trigger in ("research_answer_guard", "research_answer_no_truncate"):
        op.execute(f"ALTER TABLE research_answer ENABLE ALWAYS TRIGGER {trigger}")

    op.execute("REVOKE ALL ON research_answer FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON research_answer TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE research_answer")
    op.execute("DROP FUNCTION research_answer_guard()")
