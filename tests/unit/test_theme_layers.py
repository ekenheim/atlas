"""A company's layer is its theme's (atlas-beliefs ticket 20a): the repository's universe loads
with both themes, and a company whose layer its theme does not list is refused at load.

Seam: `atlas.companies.load_universe` on the shipped config and on copies of it.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from atlas.claims import LAYERS
from atlas.companies import UniverseConfigError, load_universe
from tests.harness import THEMES

MEMORY_LAYERS = [
    "memory-dram",
    "memory-nand",
    "controller",
    "bond-equipment",
    "process-control",
    "test",
    "osat",
    "package-substrate",
    "package-materials",
]
# Seven SEC-path seeds with the CIKs the seed list gives (docs/research/seed-list-memory-
# packaging.md), not read back from the config.
SEEDS = {
    "micron": "0000723125",
    "sk-hynix": "0002120882",
    "sandisk": "0002023554",
    "camtek": "0001109138",
    "formfactor": "0001039399",
    "ase-technology": "0001122411",
    "amkor": "0001047127",
}


def written(tmp_path: Path, change: Callable[[dict[str, Any]], object]) -> Path:
    document = yaml.safe_load(THEMES.read_text(encoding="utf-8"))
    change(document)
    path = tmp_path / "themes.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def setting(slug: str, layer: str) -> Callable[[dict[str, Any]], None]:
    def change(document: dict[str, Any]) -> None:
        document["companies"][slug]["layer"] = layer

    return change


def test_the_universe_loads_with_both_themes_and_the_seven_seeds() -> None:
    universe = load_universe(THEMES)

    assert sorted(universe.themes) == ["memory-packaging", "photonics"]
    assert len(universe.themes["photonics"].companies) == 12
    assert set(universe.themes["memory-packaging"].companies) == set(SEEDS)
    assert universe.themes["memory-packaging"].title == "Memory and advanced packaging for AI"
    assert {slug: universe.companies[slug].cik for slug in SEEDS} == SEEDS
    assert {universe.companies[slug].source_path for slug in SEEDS} == {"sec"}
    assert {universe.companies[slug].layer for slug in SEEDS} <= set(MEMORY_LAYERS)
    assert universe.companies["sk-hynix"].sec_forms == ("F-1", "424B4", "6-K", "20-F")
    assert universe.companies["ase-technology"].sec_forms == ("20-F", "6-K")
    assert universe.companies["camtek"].sec_forms == ("20-F", "6-K")
    assert universe.companies["micron"].tradingview_symbol == "NASDAQ:MU"


def test_the_themes_list_their_layers_upstream_to_downstream() -> None:
    universe = load_universe(THEMES)

    memory = universe.themes["memory-packaging"]
    assert [layer.name for layer in memory.layers or ()] == MEMORY_LAYERS
    assert all(layer.covers for layer in memory.layers or ())
    # Photonics lists none: its layers are the Claim taxonomy's, which stays photonics-only.
    assert universe.themes["photonics"].layers is None
    assert universe.themes["photonics"].layer_names() == tuple(layer.name for layer in LAYERS)
    assert not set(memory.layer_names()) & {"substrate", "epi", "chip-laser"}


def test_a_company_with_a_layer_outside_its_theme_s_is_refused(tmp_path: Path) -> None:
    path = written(tmp_path, setting("micron", "substrate"))

    with pytest.raises(UniverseConfigError) as refused:
        load_universe(path)

    message = str(refused.value)
    assert "'micron'" in message and "'substrate'" in message  # the company and its layer
    assert "'memory-packaging'" in message and "memory-dram" in message  # the theme and its own


def test_a_memory_layer_is_refused_in_a_theme_that_lists_none(tmp_path: Path) -> None:
    path = written(tmp_path, setting("lumentum", "memory-dram"))

    with pytest.raises(UniverseConfigError) as refused:
        load_universe(path)

    message = str(refused.value)
    assert "'lumentum'" in message and "'memory-dram'" in message and "'photonics'" in message


def test_a_theme_listing_a_layer_twice_is_refused(tmp_path: Path) -> None:
    def twice(document: dict[str, Any]) -> None:
        layers = document["themes"]["memory-packaging"]["layers"]
        layers.append(dict(layers[0]))

    with pytest.raises(UniverseConfigError, match="lists a layer twice"):
        load_universe(written(tmp_path, twice))


def test_a_company_with_no_layer_is_allowed_in_either_theme(tmp_path: Path) -> None:
    def clear(document: dict[str, Any]) -> None:
        document["companies"]["amkor"].pop("layer")

    assert load_universe(written(tmp_path, clear)).companies["amkor"].layer is None
