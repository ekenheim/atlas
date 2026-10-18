"""A theme's layers are free slugs its config declares (Chokepoint Watch W6a).

Seams: the company seed on a test theme config (`tests/fixtures/themes/free-layers.yaml`: a
robotics theme, not production's) and `GET /api/v1/themes[/{id}/map]` over it; the database's
slug check on `company.layer`; migration `0119` up and down. Expected layers come from the test
config's text, not from the code that reads it.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from atlas.api.app import create_app
from atlas.audit import Actor
from atlas.companies import load_universe, seed
from atlas.db.migrate import alembic_config, upgrade
from tests.harness import REPO, THEMES, make_settings

FREE_LAYERS = REPO / "tests" / "fixtures" / "themes" / "free-layers.yaml"


@pytest.fixture
def api(database_url: str, engine: Engine, tmp_path: Path) -> Iterator[TestClient]:
    archive = tmp_path / "archive"
    archive.mkdir()
    universe = load_universe(FREE_LAYERS)
    with engine.begin() as connection:
        seed(connection, Actor("local-researcher"), universe)
    yield TestClient(
        create_app(make_settings(archive, database_url=database_url, themes_config=FREE_LAYERS))
    )


def get(api: TestClient, path: str) -> Any:
    response = api.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def insert_company(engine: Engine, slug: str, layer: str | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO company (id, slug, legal_name, display_name, country, layer,"
                " source_path) VALUES (:id, :slug, :slug, :slug, 'US', :layer, NULL)"
            ),
            {"id": uuid.uuid4(), "slug": slug, "layer": layer},
        )


def test_a_theme_with_layers_of_its_own_seeds_and_appears_on_the_map_by_layer(
    api: TestClient,
) -> None:
    companies = {c["slug"]: c for c in get(api, "/api/v1/companies?limit=100")["items"]}
    assert {slug: companies[slug]["layer"] for slug in companies} == {
        "acme-actuators": "actuators",
        "gearbox-works": "reducers",
        "volt-motors": "motors",
        "integrator-one": None,
    }

    themes = {t["id"]: t for t in get(api, "/api/v1/themes")}
    assert sorted(themes) == ["robotics-test"]
    assert themes["robotics-test"]["company_count"] == 4
    assert themes["robotics-test"]["empty_layers"] == ["sensors"]

    robotics = get(api, "/api/v1/themes/robotics-test/map")
    assert [(layer["layer"], layer["covers"]) for layer in robotics["layers"]] == [
        ("actuators", "linear and rotary actuators for robot joints"),
        ("reducers", "harmonic and planetary reducers"),
        ("motors", "frameless torque motors"),
        ("sensors", "encoders and force-torque sensors (no company yet)"),
    ]
    assert {
        layer["layer"]: [c["slug"] for c in layer["companies"]] for layer in robotics["layers"]
    } == {
        "actuators": ["acme-actuators"],
        "reducers": ["gearbox-works"],
        "motors": ["volt-motors"],
        "sensors": [],
    }
    assert [c["slug"] for c in robotics["unlayered"]] == ["integrator-one"]


def test_the_company_s_own_page_shows_its_layer(api: TestClient) -> None:
    companies = {c["slug"]: c["id"] for c in get(api, "/api/v1/companies?limit=100")["items"]}

    one = get(api, f"/api/v1/companies/{companies['gearbox-works']}")
    dossier = get(api, f"/api/v1/companies/{companies['gearbox-works']}/dossier")

    assert one["layer"] == "reducers"
    assert dossier["company"]["layer"] == "reducers"


def test_the_database_checks_the_slug_format_not_a_list(engine: Engine) -> None:
    for layer in ("actuators", "ab", "x" * 41, "high-voltage-motors", "epi", None):
        insert_company(engine, f"ok-{uuid.uuid4().hex[:8]}", layer)

    for layer in ("Actuators", "a", "x" * 42, "1motors", "motor_s", "motors ", ""):
        with pytest.raises(DBAPIError, match="company_layer_check"):
            insert_company(engine, f"bad-{uuid.uuid4().hex[:8]}", layer)


def test_the_shipped_universe_seeds_as_before(engine: Engine) -> None:
    universe = load_universe(THEMES)
    with engine.begin() as connection:
        seed(connection, Actor("local-researcher"), universe)
        rows = {
            slug: layer
            for slug, layer in connection.execute(text("SELECT slug, layer FROM company"))
        }

    assert rows["lumentum"] == "chip-laser"
    assert rows["micron"] == "memory-dram"
    assert rows["sandisk"] == "memory-nand"
    assert rows["iren"] is None


def test_migration_0119_widens_the_check_to_the_slug_format_and_downgrades_to_the_list(
    empty_database_url: str,
) -> None:
    config = alembic_config(empty_database_url)
    upgrade(empty_database_url, "0119")
    engine = create_engine(empty_database_url)
    try:
        insert_company(engine, "motors-co", "motors")
        with pytest.raises(DBAPIError, match="company_layer_check"):
            insert_company(engine, "bad-co", "Not_A_Slug")

        # The downgrade fails while a company has a layer the old list lacks ...
        with pytest.raises(DBAPIError, match="company_layer_check"):
            command.downgrade(config, "-1")
        with engine.begin() as connection:
            connection.execute(text("UPDATE company SET layer = 'osat' WHERE slug = 'motors-co'"))
        # ... and restores 0115's check once none does.
        command.downgrade(config, "-1")
        with pytest.raises(DBAPIError, match="company_layer_check"):
            insert_company(engine, "actuators-co", "actuators")
        insert_company(engine, "epi-co", "epi")
        insert_company(engine, "dram-co", "memory-dram")

        # And upgrading again keeps every row and takes new slugs.
        upgrade(empty_database_url, "0119")
        insert_company(engine, "reducers-co", "reducers")
        with engine.connect() as connection:
            count = connection.execute(text("SELECT count(*) FROM company")).scalar_one()
        assert count == 4
    finally:
        engine.dispose()
