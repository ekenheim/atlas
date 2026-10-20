"""The prediction record (atlas-record ticket 05): each prediction a stored edition makes, once.

Seams: `POST /api/v1/editions` (the import that records them) and `GET /api/v1/ledger-predictions`
on a fresh database, with the application clock under the test's control. The pages are the
byte-exact snapshots of 2026-10-19 (`tests/fixtures/artifacts/`, never changed); a later edition is
built in the test from a fixture's own ledger, so it has every field a task writes.
"""

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.api.app import create_app
from atlas.record import parse_page
from tests.harness import REPO, Atlas, Clock

PAGES = REPO / "tests" / "fixtures" / "artifacts" / "2026-10-19"
THEMES = (
    "photonics",
    "memory-packaging",
    "robotics",
    "power-equipment",
    "aerospace-defence",
    "nuclear",
    "quantum",
)
THEME_PREDICTIONS = {
    "photonics": 4,
    "memory-packaging": 4,
    "robotics": 3,
    "power-equipment": 4,
    "aerospace-defence": 4,
    "nuclear": 5,
    "quantum": 3,
}
NO_SUCH_ID = "00000000-0000-0000-0000-000000000000"
CLOCK_START = "2026-10-20T08:00:00+00:00"


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime.fromisoformat(CLOCK_START))


@pytest.fixture
def atlas(database_url: str, tmp_path: Path, clock: Clock) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, "")
    harness.api = TestClient(create_app(harness.settings(), clock=clock))
    yield harness
    harness.engine.dispose()


def page(name: str) -> bytes:
    return (PAGES / f"{name}.html").read_bytes()


def ledger_of(name: str) -> dict[str, Any]:
    raw = parse_page(page(name)).raw
    assert raw is not None
    return raw


def as_page(ledger: dict[str, Any]) -> bytes:
    return f"<html><body><pre>{json.dumps(ledger)}</pre></body></html>".encode()


def later_page(
    name: str, as_of: str, edition: int, change: dict[str, dict[str, Any]] | None = None
) -> bytes:
    """A later edition of a fixture's theme: its own ledger, the week on, `change` applying the
    given fields to the predictions by ID."""
    ledger = ledger_of(name)
    ledger["as_of"] = as_of
    ledger["edition"] = edition
    for prediction in ledger["predictions"]:
        prediction.update((change or {}).get(prediction["id"], {}))
    return as_page(ledger)


def post(atlas: Atlas, theme: str, body: bytes) -> dict[str, Any]:
    response = atlas.api.post(
        "/api/v1/editions",
        params={"theme": theme},
        content=body,
        headers={"Content-Type": "text/html"},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def import_all(atlas: Atlas) -> None:
    for name in (*THEMES, "council"):
        post(atlas, name, page(name))


def listed(atlas: Atlas, **params: Any) -> dict[str, Any]:
    return atlas.get("/api/v1/ledger-predictions", limit=200, **params)


def by_id(atlas: Atlas, theme: str, prediction_id: str) -> dict[str, Any]:
    items = listed(atlas, theme=theme)["items"]
    return next(item for item in items if item["prediction_id"] == prediction_id)


def count(atlas: Atlas, table: str) -> int:
    with atlas.engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_the_fixtures_give_twenty_seven_theme_predictions_and_four_of_the_councils(
    atlas: Atlas,
) -> None:
    import_all(atlas)

    everything = listed(atlas)
    council = listed(atlas, theme="council")

    assert everything["total"] == 31
    assert count(atlas, "ledger_prediction") == 31
    for theme, expected in THEME_PREDICTIONS.items():
        assert listed(atlas, theme=theme)["total"] == expected
    assert sum(THEME_PREDICTIONS.values()) == 27
    assert council["total"] == 4
    assert {item["theme"] for item in council["items"]} == {"council"}
    assert {item["prediction_id"] for item in council["items"]} == {
        "cou-p1",
        "cou-p2",
        "cou-p3",
        "cou-p4",
    }
    assert all(
        item["state"] == "open" and item["settlement"] is None for item in everything["items"]
    )


def test_a_prediction_is_recorded_as_the_ledger_wrote_it(atlas: Atlas) -> None:
    edition = post(atlas, "aerospace-defence", page("aerospace-defence"))["edition"]
    post(atlas, "council", page("council"))

    prediction = by_id(atlas, "aerospace-defence", "aer-p1")

    assert prediction["chokepoint"] == "aer-1"
    assert prediction["made"] == "2026-10-19"
    assert prediction["deadline"] == "2027-02-28"
    assert prediction["deadline_on"] == "2027-02-28"
    assert prediction["text"].startswith("By 2027-02-28, Howmet's Q4 2026 earnings release")
    assert prediction["source_type"] == "company earnings release"
    assert prediction["edition_id"] == edition["id"]
    # The council's prediction names no chokepoint.
    assert by_id(atlas, "council", "cou-p1")["chokepoint"] is None
    assert atlas.get(f"/api/v1/ledger-predictions/{prediction['id']}") == prediction


def test_importing_again_adds_none(atlas: Atlas) -> None:
    import_all(atlas)
    before = count(atlas, "audit_event")

    again = [post(atlas, name, page(name))["outcome"] for name in (*THEMES, "council")]

    assert again == ["unchanged"] * 8
    assert count(atlas, "ledger_prediction") == 31
    assert count(atlas, "audit_event") == before


def test_a_later_edition_never_changes_the_row_and_adds_only_new_ids(atlas: Atlas) -> None:
    first = post(atlas, "nuclear", page("nuclear"))["edition"]
    original = by_id(atlas, "nuclear", "nuc-p1")
    ledger = ledger_of("nuclear")
    ledger["as_of"], ledger["edition"] = "2026-10-26", 2
    ledger["predictions"][0].update(
        text="A different prediction altogether.", deadline="2030-01-01"
    )
    ledger["predictions"].append({"id": "nuc-p6", "chokepoint": "nuc-1", "text": "New one."})
    second = post(atlas, "nuclear", as_page(ledger))["edition"]

    items = listed(atlas, theme="nuclear")["items"]

    assert len(items) == 6
    assert by_id(atlas, "nuclear", "nuc-p1") == original
    assert by_id(atlas, "nuclear", "nuc-p6")["edition_id"] == second["id"]
    assert by_id(atlas, "nuclear", "nuc-p2")["edition_id"] == first["id"]


def test_the_same_id_in_two_themes_is_two_predictions(atlas: Atlas) -> None:
    post(atlas, "photonics", page("photonics"))
    odd = ledger_of("robotics")
    odd["predictions"][0]["id"] = "pho-p1"
    post(atlas, "robotics", as_page(odd))

    assert by_id(atlas, "photonics", "pho-p1")["text"] != by_id(atlas, "robotics", "pho-p1")["text"]
    assert listed(atlas)["total"] == 4 + 3


def test_a_later_edition_that_settles_one_makes_it_met(atlas: Atlas) -> None:
    first = post(atlas, "photonics", page("photonics"))["edition"]
    settled = {
        "pho-p1": {
            "state": "met",
            "settled_on": "2026-11-05",
            "settlement_quote": "we continue to ship behind demand for EML chips",
            "settlement_url": "https://example.com/lite-q1-fy27-call",
        }
    }
    second = post(atlas, "photonics", later_page("photonics", "2026-11-09", 2, settled))["edition"]

    met = by_id(atlas, "photonics", "pho-p1")

    assert met["state"] == "met"
    assert met["edition_id"] == first["id"]
    assert met["settlement"]["state"] == "met"
    assert met["settlement"]["settled_on"] == "2026-11-05"
    assert met["settlement"]["quote"] == "we continue to ship behind demand for EML chips"
    assert met["settlement"]["url"] == "https://example.com/lite-q1-fy27-call"
    assert met["settlement"]["edition_id"] == second["id"]
    assert listed(atlas, state="met")["total"] == 1
    assert listed(atlas, state="open", theme="photonics")["total"] == 3
    assert count(atlas, "ledger_prediction_settlement") == 1


def test_a_missed_prediction_stays_missed_after_its_deadline(atlas: Atlas, clock: Clock) -> None:
    post(atlas, "power-equipment", page("power-equipment"))
    missed = {"pwr-p2": {"state": "missed", "settled_on": "2026-11-20", "settlement_quote": "q"}}
    post(atlas, "power-equipment", later_page("power-equipment", "2026-11-23", 2, missed))

    assert by_id(atlas, "power-equipment", "pwr-p2")["state"] == "missed"
    clock.now = datetime.fromisoformat("2027-06-01T00:00:00+00:00")
    after = by_id(atlas, "power-equipment", "pwr-p2")
    assert after["state"] == "missed"
    assert after["settlement"]["url"] is None


def test_a_later_different_settlement_is_not_stored_here(atlas: Atlas) -> None:
    post(atlas, "photonics", page("photonics"))
    met = {"pho-p1": {"state": "met", "settled_on": "2026-11-05"}}
    post(atlas, "photonics", later_page("photonics", "2026-11-09", 2, met))
    flipped = {"pho-p1": {"state": "missed", "settled_on": "2026-11-12"}}
    post(atlas, "photonics", later_page("photonics", "2026-11-16", 3, flipped))
    unsettled = {"pho-p1": {"state": "open"}}
    post(atlas, "photonics", later_page("photonics", "2026-11-23", 4, unsettled))

    prediction = by_id(atlas, "photonics", "pho-p1")

    assert prediction["state"] == "met"
    assert prediction["settlement"]["settled_on"] == "2026-11-05"
    assert count(atlas, "ledger_prediction_settlement") == 1


def test_a_settlement_without_a_day_or_with_another_state_is_not_one(atlas: Atlas) -> None:
    post(atlas, "photonics", page("photonics"))
    claims = {
        "pho-p1": {"state": "met"},
        "pho-p2": {"state": "lapsed", "settled_on": "2026-11-05"},
        "pho-p3": {"state": "met", "settled_on": "  "},
    }
    post(atlas, "photonics", later_page("photonics", "2026-11-09", 2, claims))

    assert {i["state"] for i in listed(atlas, theme="photonics")["items"]} == {"open"}
    assert count(atlas, "ledger_prediction_settlement") == 0


def test_a_prediction_settled_in_the_edition_that_first_names_it_is_met(atlas: Atlas) -> None:
    settled = {"pho-p1": {"state": "met", "settled_on": "2026-11-05"}}
    edition = post(atlas, "photonics", later_page("photonics", "2026-11-09", 2, settled))["edition"]

    prediction = by_id(atlas, "photonics", "pho-p1")

    assert prediction["state"] == "met"
    assert prediction["edition_id"] == edition["id"] == prediction["settlement"]["edition_id"]


def test_past_its_deadline_with_no_settlement_a_prediction_lapses(
    atlas: Atlas, clock: Clock
) -> None:
    import_all(atlas)

    clock.now = datetime.fromisoformat("2026-11-30T23:00:00+00:00")
    on_the_day = listed(atlas, state="lapsed")
    clock.now = datetime.fromisoformat("2026-12-01T00:30:00+00:00")
    after = listed(atlas, state="lapsed")
    still_open = listed(atlas, state="open")

    # The day of the deadline is still open; the next day lapses (as for a Hypothesis).
    assert on_the_day["total"] == 0
    assert {(i["theme"], i["prediction_id"]) for i in after["items"]} == {
        ("power-equipment", "pwr-p2"),
        ("robotics", "rob-p1"),
    }
    assert all(i["state"] == "lapsed" and i["settlement"] is None for i in after["items"])
    assert still_open["total"] == 29
    assert by_id(atlas, "robotics", "rob-p1")["state"] == "lapsed"


def test_due_before_lists_what_falls_due_by_a_day_soonest_first(atlas: Atlas) -> None:
    import_all(atlas)

    due = listed(atlas, due_before="2026-11-30")
    january = listed(atlas, due_before="2027-01-31", state="open")

    assert [(i["theme"], i["prediction_id"]) for i in due["items"]] == [
        ("power-equipment", "pwr-p2"),
        ("robotics", "rob-p1"),
    ]
    deadlines = [i["deadline_on"] for i in january["items"]]
    assert deadlines == sorted(deadlines)
    assert max(deadlines) <= "2027-01-31"
    assert january["total"] > 2


def test_a_deadline_the_task_wrote_loosely_is_read_or_never_lapses(
    atlas: Atlas, clock: Clock
) -> None:
    changes = {
        "pho-p1": {"deadline": "2027-03"},
        "pho-p2": {"deadline": "end of fiscal 2027"},
        "pho-p3": {"deadline": None},
    }
    post(atlas, "photonics", later_page("photonics", "2026-11-09", 2, changes))

    month = by_id(atlas, "photonics", "pho-p1")
    loose = by_id(atlas, "photonics", "pho-p2")
    none = by_id(atlas, "photonics", "pho-p3")
    clock.now = datetime.fromisoformat("2035-01-01T00:00:00+00:00")

    assert (month["deadline"], month["deadline_on"]) == ("2027-03", "2027-03-31")
    assert (loose["deadline"], loose["deadline_on"]) == ("end of fiscal 2027", None)
    assert (none["deadline"], none["deadline_on"]) == (None, None)
    assert by_id(atlas, "photonics", "pho-p1")["state"] == "lapsed"
    assert by_id(atlas, "photonics", "pho-p2")["state"] == "open"
    assert by_id(atlas, "photonics", "pho-p3")["state"] == "open"
    # `pho-p4` keeps its fixture deadline; the loose ones have no day to be due by.
    assert [i["prediction_id"] for i in listed(atlas, due_before="2099-01-01")["items"]] == [
        "pho-p1",
        "pho-p4",
    ]


def test_a_page_with_no_ledger_records_nothing(atlas: Atlas) -> None:
    post(atlas, "photonics", b"<html><body><p>The task failed.</p></body></html>")

    assert listed(atlas)["total"] == 0


def test_recording_is_audited_once_per_prediction_and_settlement(atlas: Atlas) -> None:
    post(atlas, "photonics", page("photonics"))
    met = {"pho-p1": {"state": "met", "settled_on": "2026-11-05"}}
    post(atlas, "photonics", later_page("photonics", "2026-11-09", 2, met))
    prediction = by_id(atlas, "photonics", "pho-p1")

    with atlas.engine.connect() as connection:
        actions = [
            row.action
            for row in connection.execute(
                text(
                    "SELECT action FROM audit_event WHERE action LIKE 'ledger_prediction.%'"
                    " AND entity_id = :id ORDER BY id"
                ),
                {"id": prediction["id"]},
            )
        ]
        recorded = connection.execute(
            text("SELECT count(*) FROM audit_event WHERE action = 'ledger_prediction.recorded'")
        ).scalar_one()

    assert actions == ["ledger_prediction.recorded", "ledger_prediction.settled"]
    assert recorded == 4


def test_the_routes_refuse_what_they_cannot_read_and_find_nothing_unknown(atlas: Atlas) -> None:
    import_all(atlas)
    route = "/api/v1/ledger-predictions"

    assert atlas.api.get(route, params={"state": "settled"}).status_code == 422
    assert atlas.api.get(route, params={"due_before": "soon"}).status_code == 422
    missing = atlas.api.get(f"{route}/{NO_SUCH_ID}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert atlas.api.get(f"{route}/not-an-id").status_code == 422
    empty = listed(atlas, theme="no-such-theme")
    assert (empty["items"], empty["total"]) == ([], 0)
    page_two = atlas.get(route, limit=10, offset=30)
    assert (len(page_two["items"]), page_two["total"]) == (1, 31)
    # Hypothesis predictions keep their own route.
    assert atlas.get("/api/v1/predictions")["total"] == 0


def test_a_prediction_and_its_settlement_cannot_be_changed_or_removed(atlas: Atlas) -> None:
    post(atlas, "photonics", page("photonics"))
    met = {"pho-p1": {"state": "met", "settled_on": "2026-11-05"}}
    post(atlas, "photonics", later_page("photonics", "2026-11-09", 2, met))

    for statement in (
        "UPDATE ledger_prediction SET text = 'x'",
        "DELETE FROM ledger_prediction",
        "TRUNCATE ledger_prediction CASCADE",
        "UPDATE ledger_prediction_settlement SET state = 'missed'",
        "DELETE FROM ledger_prediction_settlement",
        "TRUNCATE ledger_prediction_settlement",
    ):
        with pytest.raises(DBAPIError, match="insert-only"), atlas.engine.begin() as connection:
            connection.execute(text(statement))
    assert count(atlas, "ledger_prediction") == 4
    assert count(atlas, "ledger_prediction_settlement") == 1


def test_the_tables_refuse_what_the_service_never_writes(atlas: Atlas) -> None:
    post(atlas, "photonics", page("photonics"))
    prediction = by_id(atlas, "photonics", "pho-p1")
    bad_settlement = (
        "INSERT INTO ledger_prediction_settlement (id, prediction_id, edition_id, state,"
        " settled_on, recorded_at) VALUES (gen_random_uuid(), :prediction, :edition,"
        " :state, :day, now())"
    )
    for state, day in (("open", "d"), ("lapsed", "d"), ("met", " ")):
        with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
            connection.execute(
                text(bad_settlement),
                {
                    "prediction": prediction["id"],
                    "edition": prediction["edition_id"],
                    "state": state,
                    "day": day,
                },
            )
    with pytest.raises(DBAPIError), atlas.engine.begin() as connection:  # not a theme slug
        connection.execute(
            text(
                "INSERT INTO ledger_prediction (id, theme, prediction_id, text, edition_id,"
                " recorded_at) VALUES (gen_random_uuid(), 'Bad Theme', 'x', 't', :edition, now())"
            ),
            {"edition": prediction["edition_id"]},
        )
    assert count(atlas, "ledger_prediction_settlement") == 0
