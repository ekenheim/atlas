"""A company's layer is its theme's: the second theme's nine layers are valid.

`company.layer` was checked against the photonics layers alone (migration 0015). The second
theme, `memory-packaging` (atlas-beliefs ticket 20a; `docs/decisions.md`, "The second theme:
layers per theme, the Claim taxonomy stays photonics'"), has layers of its own, so the check
admits them too. Nothing else changes: `claim.layer` and `relationship.layer` stay checked
against the photonics taxonomy (the Claim taxonomy is photonics-only), and which layers a theme
allows is the theme config's rule, checked at load (`atlas.companies`).

Revision ID: 0115
Revises: 0114
"""

from alembic import op

revision = "0115"
down_revision = "0114"
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
        f" CHECK (layer IN ({_check(_PHOTONICS + _MEMORY_PACKAGING)}))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE company DROP CONSTRAINT company_layer_check")
    op.execute(
        "ALTER TABLE company ADD CONSTRAINT company_layer_check"
        f" CHECK (layer IN ({_check(_PHOTONICS)}))"
    )
