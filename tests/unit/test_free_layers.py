"""A theme's layers are free slugs its config declares (Chokepoint Watch W6a).

Seam: `atlas.companies.load_universe` on a test theme config
(`tests/fixtures/themes/free-layers.yaml`, not production's) and on copies of it, and on the
shipped config, which loads as it did.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from atlas.claims import LAYERS
from atlas.companies import UniverseConfigError, load_universe
from tests.harness import REPO, THEMES

FREE_LAYERS = REPO / "tests" / "fixtures" / "themes" / "free-layers.yaml"


def written(tmp_path: Path, change: Callable[[dict[str, Any]], object]) -> Path:
    document = yaml.safe_load(FREE_LAYERS.read_text(encoding="utf-8"))
    change(document)
    path = tmp_path / "free-layers.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def test_a_theme_with_layers_of_its_own_loads() -> None:
    universe = load_universe(FREE_LAYERS)

    theme = universe.themes["robotics-test"]
    assert theme.layer_names() == ("actuators", "reducers", "motors", "sensors")
    assert all(layer.covers for layer in theme.layers or ())
    assert {slug: universe.companies[slug].layer for slug in theme.companies} == {
        "acme-actuators": "actuators",
        "gearbox-works": "reducers",
        "volt-motors": "motors",
        "integrator-one": None,
    }


def test_the_claim_taxonomy_is_not_the_themes() -> None:
    # `actuators` is no Claim layer, and the Claim taxonomy is what it was (seven names).
    assert "actuators" not in {layer.name for layer in LAYERS}
    assert len(LAYERS) == 7


def test_a_layer_the_theme_did_not_declare_is_refused_naming_company_layer_and_theme(
    tmp_path: Path,
) -> None:
    def undeclare(document: dict[str, Any]) -> None:
        document["companies"]["volt-motors"]["layer"] = "batteries"

    with pytest.raises(UniverseConfigError) as refused:
        load_universe(written(tmp_path, undeclare))

    message = str(refused.value)
    assert "'volt-motors'" in message and "'batteries'" in message
    assert "'robotics-test'" in message and "actuators" in message


def test_another_themes_layer_is_not_declared_by_this_one(tmp_path: Path) -> None:
    def borrow(document: dict[str, Any]) -> None:
        document["companies"]["volt-motors"]["layer"] = "memory-dram"

    with pytest.raises(UniverseConfigError, match=r"'volt-motors'.*'memory-dram'"):
        load_universe(written(tmp_path, borrow))


@pytest.mark.parametrize(
    "slug", ["Actuators", "a", "1motors", "motor_s", "x" * 42, "reducers ", "motors.", ""]
)
def test_a_layer_that_is_not_a_slug_is_refused(tmp_path: Path, slug: str) -> None:
    def rename(document: dict[str, Any]) -> None:
        document["themes"]["robotics-test"]["layers"][0]["name"] = slug
        document["companies"]["acme-actuators"]["layer"] = slug

    with pytest.raises(UniverseConfigError, match="invalid"):
        load_universe(written(tmp_path, rename))


@pytest.mark.parametrize("slug", ["ab", "x" * 41, "a1", "high-voltage-motors"])
def test_the_edges_of_the_slug_format_are_accepted(tmp_path: Path, slug: str) -> None:
    def rename(document: dict[str, Any]) -> None:
        document["themes"]["robotics-test"]["layers"][0]["name"] = slug
        document["companies"]["acme-actuators"]["layer"] = slug

    universe = load_universe(written(tmp_path, rename))

    assert universe.companies["acme-actuators"].layer == slug


def test_a_declared_layer_needs_what_it_covers(tmp_path: Path) -> None:
    def blank(document: dict[str, Any]) -> None:
        document["themes"]["robotics-test"]["layers"][0]["covers"] = ""

    with pytest.raises(UniverseConfigError, match="covers"):
        load_universe(written(tmp_path, blank))


def test_a_layer_declared_twice_is_still_refused(tmp_path: Path) -> None:
    def twice(document: dict[str, Any]) -> None:
        layers = document["themes"]["robotics-test"]["layers"]
        layers.append(dict(layers[0]))

    with pytest.raises(UniverseConfigError, match="lists a layer twice"):
        load_universe(written(tmp_path, twice))


def test_the_shipped_themes_declare_what_they_did() -> None:
    universe = load_universe(THEMES)

    assert universe.themes["photonics"].layers is None
    assert universe.themes["photonics"].layer_names() == (
        "substrate",
        "epi",
        "chip-laser",
        "dsp",
        "module",
        "contract-manufacturing",
        "system",
    )
    assert universe.themes["memory-packaging"].layer_names() == (
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
    assert universe.themes["scorecard"].layer_names() == ("memory-nand",)
    assert universe.companies["lumentum"].layer == "chip-laser"
    assert universe.companies["micron"].layer == "memory-dram"
