"""A theme's layers are free slugs its config declares: `company.layer` is checked for format.

`company.layer` was checked against a fixed list of names (migration 0015, widened by 0115 for
the second theme), so no new industry could name its own layers (Chokepoint Watch W6a;
`docs/decisions.md`, "A theme's layers are its config's"). The check is now the slug format
`^[a-z][a-z0-9-]{1,40}$`; which slugs a company may take is its theme config's rule, checked at
load (`atlas.companies`). `claim.layer` and `relationship.layer` keep their checks: the Claim
taxonomy is the old pipeline's and unchanged.

The downgrade restores 0115's list, so it fails (the constraint is violated) while a company
has a layer outside it: move or clear those companies first.

Revision ID: 0119
Revises: 0118
"""

from alembic import op

revision = "0119"
down_revision = "0118"
branch_labels = None
depends_on = None

_PHOTONICS = ("substrate", "epi", "chip-laser", "dsp", "module", "contract-manufacturing", "system")
_MEMORY_PACKAGING = (
    "memory-dram",
    "memory-nand",
    "controller",
    "bond-equipment",
    "process-control",
    "test",
    "osat",
    "package-substrate",
    "package-materials",
)


def _check(layers: tuple[str, ...]) -> str:
    return ", ".join(f"'{layer}'" for layer in layers)


def upgrade() -> None:
    op.execute("ALTER TABLE company DROP CONSTRAINT company_layer_check")
    op.execute(
        "ALTER TABLE company ADD CONSTRAINT company_layer_check"
        " CHECK (layer ~ '^[a-z][a-z0-9-]{1,40}$')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE company DROP CONSTRAINT company_layer_check")
    op.execute(
        "ALTER TABLE company ADD CONSTRAINT company_layer_check"
        f" CHECK (layer IN ({_check(_PHOTONICS + _MEMORY_PACKAGING)}))"
    )
