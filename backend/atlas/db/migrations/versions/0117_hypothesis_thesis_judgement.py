"""A thesis judged again (atlas-beliefs ticket 30).

`hypothesis_thesis_judgement`: the finding judge's verdict on a Belief-backed Hypothesis version's
thesis, recorded apart from the version. A version's content never changes (a published one is
immutable), so judging a thesis that no judge saw, or judging it again, cannot rewrite
`content.thesis_judged`; it adds a row here, and the version's effective verdict is its latest
row if it has one, else the content's (`docs/decisions.md`, "A corrected thesis is judged").
`verdict` is `unjudged` when there was nothing to judge the thesis against (its Beliefs cite no
recorded Fact). Insert-only.

Revision ID: 0117
Revises: 0116
"""

from alembic import op

revision = "0117"
down_revision = "0116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE hypothesis_thesis_judgement (
            id uuid PRIMARY KEY,
            hypothesis_id uuid NOT NULL REFERENCES hypothesis (id),
            version integer NOT NULL CHECK (version >= 1),
            verdict text NOT NULL CHECK (verdict IN ('supported', 'misstated', 'unjudged')),
            reason text NOT NULL,
            judge_role text NOT NULL CHECK (btrim(judge_role) <> ''),
            prompt_version text NOT NULL CHECK (btrim(prompt_version) <> ''),
            role_call_id uuid REFERENCES role_call (id),
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            note text,
            at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (hypothesis_id, version)
                REFERENCES hypothesis_version (hypothesis_id, version)
        )
    """)
    op.execute(
        "CREATE INDEX ix_hypothesis_thesis_judgement ON hypothesis_thesis_judgement"
        " (hypothesis_id, version, at)"
    )
    for kind, event in (("update", "UPDATE"), ("delete", "DELETE")):
        name = f"hypothesis_thesis_judgement_no_{kind}"
        op.execute(
            f"CREATE TRIGGER {name} BEFORE {event} ON hypothesis_thesis_judgement"
            " FOR EACH ROW EXECUTE FUNCTION belief_reject_change()"
        )
        op.execute(f"ALTER TABLE hypothesis_thesis_judgement ENABLE ALWAYS TRIGGER {name}")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON hypothesis_thesis_judgement TO atlas_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE hypothesis_thesis_judgement")
