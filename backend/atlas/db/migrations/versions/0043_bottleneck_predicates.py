"""The company-level bottleneck predicates join the Relationship whitelist.

- `relationship.predicate`: the check constraint gains `capacity_constrained`,
  `sole_sources`, `vertically_integrates` and `qualified_for` (pilot-fixes ticket 03, an
  owner-authorized domain-model extension: docs/decisions.md, "Company-level bottleneck
  predicates", 2026-09-30). Like `manufactures`, each is an edge from a company to a product
  node (`object_text`), so no other column changes. Claims and Assertions keep their
  predicate as text checked in code (`atlas.claims.predicates`).

The downgrade refuses while any Relationship uses a new predicate: Relationships are never
deleted.

Revision ID: 0043
Revises: 0042
"""

from alembic import op
from sqlalchemy import text

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

_BUILD_PLAN = (
    "manufactures",
    "supplies",
    "buys_from",
    "uses_material",
    "owns",
    "competes_with",
    "substitutes_for",
    "expands_capacity_for",
    "depends_on",
)
_BOTTLENECK = ("capacity_constrained", "sole_sources", "vertically_integrates", "qualified_for")


def _constraint(predicates: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{name}'" for name in predicates)
    op.execute("ALTER TABLE relationship DROP CONSTRAINT relationship_predicate_check")
    op.execute(
        "ALTER TABLE relationship ADD CONSTRAINT relationship_predicate_check"
        f" CHECK (predicate IN ({listed}))"
    )


def upgrade() -> None:
    _constraint(_BUILD_PLAN + _BOTTLENECK)


def downgrade() -> None:
    used = (
        op.get_bind()
        .execute(
            text("SELECT count(*) FROM relationship WHERE predicate = ANY(:names)"),
            {"names": list(_BOTTLENECK)},
        )
        .scalar_one()
    )
    if used:
        raise RuntimeError(
            f"{used} Relationships use a bottleneck predicate; they are never deleted"
        )
    _constraint(_BUILD_PLAN)
