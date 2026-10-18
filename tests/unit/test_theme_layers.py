"""A company's layer is its theme's (atlas-beliefs ticket 20a): the repository's universe loads
with both themes, and a company whose layer its theme does not list is refused at load.

Seam: `atlas.companies.load_universe` on the shipped config and on copies of it.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from atlas.claims import LAYERS
from atlas.companies import UniverseConfigError, load_universe
from atlas.retention.service import SourceVersionInfo, observation_scopes, version_tags
from atlas.retention.triage import triage_themes
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


SQUEEZED_BUYERS = {"extreme-networks", "pacific-biosciences", "napco", "aerovironment", "brady"}


def test_the_universe_loads_with_both_themes_and_the_seven_seeds() -> None:
    universe = load_universe(THEMES)

    assert sorted(universe.themes) == ["memory-packaging", "photonics", "robotics", "scorecard"]
    assert len(universe.themes["photonics"].companies) == 12
    # Ticket 33's scan admitted five buyers squeezed by memory supply, with no layer.
    assert set(universe.themes["memory-packaging"].companies) == set(SEEDS) | SQUEEZED_BUYERS
    assert all(universe.companies[slug].layer is None for slug in SQUEEZED_BUYERS)
    assert universe.themes["memory-packaging"].title == "Memory and advanced packaging for AI"
    assert {slug: universe.companies[slug].cik for slug in SEEDS} == SEEDS
    assert {universe.companies[slug].source_path for slug in SEEDS} == {"sec"}
    assert {universe.companies[slug].layer for slug in SEEDS} <= set(MEMORY_LAYERS)
    assert universe.companies["sk-hynix"].sec_forms == ("F-1", "424B4", "6-K", "20-F")
    assert universe.companies["ase-technology"].sec_forms == ("20-F", "6-K")
    assert universe.companies["camtek"].sec_forms == ("20-F", "6-K")
    assert universe.companies["micron"].tradingview_symbol == "NASDAQ:MU"


def test_the_scorecard_theme_has_sandisk_and_four_companies_with_no_layer() -> None:
    # The early-call scorecard's theme (ticket 29a): CIKs and forms as SEC's ticker file and
    # submissions gave them on 2026-10-18, not read back from the config.
    universe = load_universe(THEMES)

    scorecard = universe.themes["scorecard"]
    assert scorecard.companies == ("sandisk", "iren", "etoro", "snap", "poet-technologies")
    assert [layer.name for layer in scorecard.layers or ()] == ["memory-nand"]
    assert universe.companies["sandisk"].layer == "memory-nand"
    forms = {
        "iren": ("0001878848", ("10-K", "10-Q", "8-K", "20-F", "6-K"), "NASDAQ:IREN"),
        "etoro": ("0001493318", ("F-1", "20-F", "6-K"), "NASDAQ:ETOR"),
        "snap": ("0001564408", None, "NYSE:SNAP"),
        "poet-technologies": ("0001437424", ("20-F", "6-K"), "NASDAQ:POET"),
    }
    for slug, (cik, sec_forms, symbol) in forms.items():
        company = universe.companies[slug]
        assert (company.cik, company.sec_forms, company.tradingview_symbol) == (
            cik,
            sec_forms,
            symbol,
        )
        assert company.layer is None and company.source_path == "sec"
    # SanDisk sits in two themes; nobody else is in two.
    assert "sandisk" in universe.themes["memory-packaging"].companies
    members = [slug for theme in universe.themes.values() for slug in theme.companies]
    assert sorted(slug for slug in set(members) if members.count(slug) > 1) == ["sandisk"]


def test_a_scorecard_company_with_a_layer_the_theme_does_not_list_is_refused(
    tmp_path: Path,
) -> None:
    path = written(tmp_path, setting("iren", "module"))

    with pytest.raises(UniverseConfigError) as refused:
        load_universe(path)

    assert "'iren'" in str(refused.value) and "'scorecard'" in str(refused.value)


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


def version_of(slug: str) -> SourceVersionInfo:
    return SourceVersionInfo(
        id=uuid.uuid4(),
        raw_sha256="0" * 64,
        parse_status="parsed",
        parsed_object_uri=None,
        language="en",
        available_at=datetime(2026, 1, 1, tzinfo=UTC),
        provider="sec_edgar",
        source_type="filing",
        form_type="10-K",
        document_type=None,
        title="annual report",
        company_id=uuid.uuid4(),
        company_slug=slug,
        company_name=slug,
        company_legal_name=slug,
        publisher="SEC EDGAR",
        metadata={},
    )


def test_a_company_s_retain_item_carries_only_its_own_themes() -> None:
    universe = load_universe(THEMES)

    for slug, theme in (
        ("lumentum", "photonics"),
        ("micron", "memory-packaging"),
        ("iren", "scorecard"),
    ):
        tags = version_tags(version_of(slug), universe)
        assert [tag for tag in tags if tag.startswith("theme:")] == [f"theme:{theme}"]
        assert observation_scopes(tags) == [[f"theme:{theme}"]]
        assert [t.theme_id for t in triage_themes(version_of(slug), universe)] == [theme]


def test_sandisk_in_two_themes_carries_both_theme_tags_and_scopes() -> None:
    # The one company in two themes (ticket 29a): memory-packaging's and the scorecard's.
    universe = load_universe(THEMES)

    tags = version_tags(version_of("sandisk"), universe)

    assert sorted(tag for tag in tags if tag.startswith("theme:")) == [
        "theme:memory-packaging",
        "theme:scorecard",
    ]
    assert sorted(observation_scopes(tags) or []) == [
        ["theme:memory-packaging"],
        ["theme:scorecard"],
    ]
    assert sorted(t.theme_id for t in triage_themes(version_of("sandisk"), universe)) == [
        "memory-packaging",
        "scorecard",
    ]
