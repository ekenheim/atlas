"""The rewrite check (atlas-record ticket 02): an edition is compared with the theme's previous
parsed one when it is stored, and each difference is kept insert-only.

Seams: the `atlas record import` CLI, `/api/v1/editions`, `/api/v1/rewrites` and `/metrics`, on a
fresh database. The editions are the byte-exact snapshots of 2026-10-19 (`tests/fixtures/
artifacts/`) and hand-edited copies of their ledgers, built here. The comparison's every kind is
tested on its own in `tests/unit/test_record_rewrites.py`; here: when it runs, against which
edition, and what is kept.
"""

import copy
import html
import json
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.record import parse_page
from tests.harness import REPO, Atlas, scrape_metrics

PAGES = REPO / "tests" / "fixtures" / "artifacts" / "2026-10-19"
COMMIT = "9fceb02d0ae598e95dc970b74767f19372d61af8"


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, "")
    yield harness
    harness.engine.dispose()


def raw(name: str) -> dict[str, Any]:
    parsed = parse_page((PAGES / f"{name}.html").read_bytes()).raw
    assert parsed is not None
    return parsed


def as_page(ledger: dict[str, Any]) -> bytes:
    body = html.escape(json.dumps(ledger, indent=1))
    return f"<html><body><pre>{body}</pre></body></html>".encode()


def next_week(ledger: dict[str, Any], weeks: int = 1) -> dict[str, Any]:
    following = copy.deepcopy(ledger)
    key = "council_as_of" if "board" in ledger else "as_of"
    following[key] = (date.fromisoformat(ledger[key]) + timedelta(days=7 * weeks)).isoformat()
    following["edition"] = ledger["edition"] + weeks
    return following


def post(atlas: Atlas, theme: str, page: bytes) -> dict[str, Any]:
    response = atlas.api.post(
        "/api/v1/editions",
        params={"theme": theme, "source": "drop_box", "commit_sha": COMMIT},
        content=page,
        headers={"Content-Type": "text/html"},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def rewrites_of(atlas: Atlas, edition_id: str) -> list[dict[str, Any]]:
    return atlas.get(f"/api/v1/editions/{edition_id}/rewrites")["items"]


def kinds(items: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(item["kind"], item["subject_id"]) for item in items]


def audit_actions(atlas: Atlas, entity_id: str) -> list[str]:
    with atlas.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT action FROM audit_event WHERE entity_id = :id ORDER BY id"),
            {"id": entity_id},
        )
        return [row.action for row in rows]


def count(atlas: Atlas, table: str) -> int:
    with atlas.engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_the_first_edition_and_an_unchanged_second_one_find_nothing(atlas: Atlas) -> None:
    first = post(atlas, "photonics", (PAGES / "photonics.html").read_bytes())
    second = post(atlas, "photonics", as_page(next_week(raw("photonics"))))

    assert first["outcome"] == second["outcome"] == "imported"
    assert first["rewrites_found"] == second["rewrites_found"] == 0
    assert rewrites_of(atlas, first["edition"]["id"]) == []
    assert rewrites_of(atlas, second["edition"]["id"]) == []
    assert atlas.get("/api/v1/rewrites")["total"] == 0
    assert audit_actions(atlas, second["edition"]["id"]) == ["edition.imported"]


def test_a_rewriting_edition_is_compared_when_it_is_stored(atlas: Atlas) -> None:
    previous = post(atlas, "photonics", (PAGES / "photonics.html").read_bytes())
    following = next_week(raw("photonics"))
    following["predictions"][0]["deadline"] = "2027-06-30"
    following["chokepoints"].pop(1)

    stored = post(atlas, "photonics", as_page(following))

    assert stored["rewrites_found"] == 2
    items = rewrites_of(atlas, stored["edition"]["id"])
    assert kinds(items) == [("chokepoint_vanished", "pho-2"), ("prediction_changed", "pho-p1")]
    vanished, changed = items
    assert vanished["edition_id"] == stored["edition"]["id"]
    assert vanished["previous_edition_id"] == previous["edition"]["id"]
    assert (vanished["theme"], vanished["as_of"]) == ("photonics", "2026-10-26")
    assert vanished["before"]["id"] == "pho-2" and vanished["after"] is None
    assert changed["field"] == "deadline"
    assert (changed["before"], changed["after"]) == ("2027-02-15", "2027-06-30")
    assert audit_actions(atlas, stored["edition"]["id"]) == [
        "edition.imported",
        "edition.rewrites_found",
    ]
    # The previous edition has nothing to report of its own.
    assert rewrites_of(atlas, previous["edition"]["id"]) == []


def test_the_same_bytes_again_find_and_store_nothing_more(atlas: Atlas) -> None:
    post(atlas, "photonics", (PAGES / "photonics.html").read_bytes())
    following = next_week(raw("photonics"))
    following["predictions"].pop(0)
    page = as_page(following)

    first = post(atlas, "photonics", page)
    again = post(atlas, "photonics", page)

    assert (first["outcome"], first["rewrites_found"]) == ("imported", 1)
    assert (again["outcome"], again["rewrites_found"]) == ("unchanged", 0)
    assert count(atlas, "ledger_rewrite") == 1


def test_a_ledger_that_lacks_earliest_evidence_finds_nothing(atlas: Atlas) -> None:
    post(atlas, "aerospace-defence", (PAGES / "aerospace-defence.html").read_bytes())
    following = next_week(raw("aerospace-defence"))
    for chokepoint in following["chokepoints"]:
        chokepoint.pop("earliest_evidence")
        chokepoint.pop("consensus")
    following.pop("council_answers")

    stored = post(atlas, "aerospace-defence", as_page(following))

    assert stored["rewrites_found"] == 0
    assert count(atlas, "ledger_rewrite") == 0


def test_the_council_is_checked_against_its_previous_edition(atlas: Atlas) -> None:
    post(atlas, "council", (PAGES / "council.html").read_bytes())
    following = next_week(raw("council"))
    following["contradictions"][0]["first_seen"] = "2026-12-01"

    stored = post(atlas, "council", as_page(following))

    items = rewrites_of(atlas, stored["edition"]["id"])
    assert kinds(items) == [("date_moved_later", "ccx-1")]
    assert items[0]["theme"] == "council"


def test_each_theme_is_compared_only_with_its_own_editions(atlas: Atlas) -> None:
    post(atlas, "photonics", (PAGES / "photonics.html").read_bytes())
    robotics = post(atlas, "robotics", (PAGES / "robotics.html").read_bytes())

    assert robotics["rewrites_found"] == 0
    assert count(atlas, "ledger_rewrite") == 0


def test_the_previous_edition_is_the_latest_parsed_one_before_it(atlas: Atlas) -> None:
    one = raw("photonics")
    two = next_week(one)
    three = next_week(two)
    post(atlas, "photonics", as_page(one))
    stored_two = post(atlas, "photonics", as_page(two))
    # A page with no ledger between the two is neither compared nor a previous edition.
    post(atlas, "photonics", b"<html><body><p>The task failed.</p></body></html>")
    three["predictions"][0]["text"] = "A different prediction"

    stored_three = post(atlas, "photonics", as_page(three))

    assert rewrites_of(atlas, stored_two["edition"]["id"]) == []
    items = rewrites_of(atlas, stored_three["edition"]["id"])
    assert kinds(items) == [("prediction_changed", "pho-p1")]
    assert items[0]["previous_edition_id"] == stored_two["edition"]["id"]
    # An edition that does not parse is not compared at all.
    with atlas.engine.connect() as connection:
        parsed = connection.execute(
            text("SELECT count(*) FROM ledger_edition WHERE ledger IS NULL")
        ).scalar_one()
    assert parsed == 1


def test_a_page_rewritten_the_same_day_is_compared_with_the_one_it_rewrote(atlas: Atlas) -> None:
    original = raw("photonics")
    following = next_week(original)
    post(atlas, "photonics", as_page(original))
    first = post(atlas, "photonics", as_page(following))
    rewritten = copy.deepcopy(following)
    rewritten["predictions"][0]["made"] = "2026-10-26"

    stored = post(atlas, "photonics", as_page(rewritten))

    assert stored["edition"]["same_as_of_differs"] is True
    items = rewrites_of(atlas, stored["edition"]["id"])
    assert kinds(items) == [
        ("edition_not_increasing", "photonics"),
        ("prediction_changed", "pho-p1"),
    ]
    assert {item["previous_edition_id"] for item in items} == {first["edition"]["id"]}


def test_an_edition_number_that_did_not_rise_is_found(atlas: Atlas) -> None:
    post(atlas, "photonics", (PAGES / "photonics.html").read_bytes())
    following = next_week(raw("photonics"))
    following["edition"] = 1

    stored = post(atlas, "photonics", as_page(following))

    assert kinds(rewrites_of(atlas, stored["edition"]["id"])) == [
        ("edition_not_increasing", "photonics")
    ]


def stored_with(atlas: Atlas, theme: str, change: Callable[[dict[str, Any]], None]) -> str:
    """Edition 1 of `theme`, then an edition 2 with `change` made; the second's ID."""
    first = raw(theme)
    post(atlas, theme, as_page(first))
    following = next_week(first)
    change(following)
    return post(atlas, theme, as_page(following))["edition"]["id"]


def test_the_cli_reports_how_many_rewrites_it_found(atlas: Atlas) -> None:
    first = atlas.tmp_path / "one.html"
    first.write_bytes((PAGES / "photonics.html").read_bytes())
    following = next_week(raw("photonics"))
    following["predictions"].clear()
    second = atlas.tmp_path / "two.html"
    second.write_bytes(as_page(following))

    one = atlas.cli("record", "import", "--theme", "photonics", "--file", str(first))
    two = atlas.cli("record", "import", "--theme", "photonics", "--file", str(second))

    assert one.returncode == two.returncode == 0, two.stderr
    assert json.loads(one.stdout)["rewrites_found"] == 0
    assert "rewrites" not in one.stderr
    assert json.loads(two.stdout)["rewrites_found"] == len(raw("photonics")["predictions"])
    assert "rewrites" in two.stderr


def test_rewrites_are_listed_across_editions_by_theme_and_day(atlas: Atlas) -> None:
    post(atlas, "photonics", (PAGES / "photonics.html").read_bytes())
    post(atlas, "robotics", (PAGES / "robotics.html").read_bytes())
    photonics = next_week(raw("photonics"))
    photonics["predictions"].pop(0)
    robotics = next_week(raw("robotics"), weeks=2)
    robotics["chokepoints"].pop(0)
    robotics_id = raw("robotics")["chokepoints"][0]["id"]
    post(atlas, "photonics", as_page(photonics))
    post(atlas, "robotics", as_page(robotics))

    everything = atlas.get("/api/v1/rewrites")
    only_photonics = atlas.get("/api/v1/rewrites", theme="photonics")
    since = atlas.get("/api/v1/rewrites", since="2026-11-01")
    nothing = atlas.get("/api/v1/rewrites", since="2026-12-01")

    assert everything["total"] == 2
    # Newest edition first: robotics (2026-11-02), then photonics (2026-10-26).
    assert kinds(everything["items"]) == [
        ("chokepoint_vanished", robotics_id),
        ("prediction_removed", "pho-p1"),
    ]
    assert kinds(only_photonics["items"]) == [("prediction_removed", "pho-p1")]
    assert kinds(since["items"]) == [("chokepoint_vanished", robotics_id)]
    assert nothing == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert atlas.api.get("/api/v1/rewrites", params={"since": "soon"}).status_code == 422


def test_an_unknown_edition_has_no_rewrites_to_read(atlas: Atlas) -> None:
    response = atlas.api.get("/api/v1/editions/00000000-0000-0000-0000-000000000000/rewrites")

    assert response.status_code == 404


def test_the_metric_counts_each_kind(atlas: Atlas) -> None:
    before = scrape_metrics(atlas.api)
    post(atlas, "photonics", (PAGES / "photonics.html").read_bytes())
    following = next_week(raw("photonics"))
    following["predictions"].pop(0)
    following["predictions"][0]["deadline"] = "2030-01-01"
    following["chokepoints"].pop(0)
    post(atlas, "photonics", as_page(following))

    after = scrape_metrics(atlas.api)

    def total(kind: str) -> float:
        return after[("atlas_ledger_rewrites_total", frozenset({("kind", kind)}))]

    assert before[("atlas_ledger_rewrites_total", frozenset({("kind", "id_reused")}))] == 0
    assert total("prediction_removed") == 1
    assert total("prediction_changed") == 1
    assert total("chokepoint_vanished") == 1
    assert total("id_reused") == 0
    assert total("edition_not_increasing") == 0


def test_a_finding_cannot_be_changed_or_removed(atlas: Atlas) -> None:
    stored = stored_with(atlas, "photonics", lambda d: d["predictions"].pop(0))
    assert rewrites_of(atlas, stored)

    for statement in (
        "UPDATE ledger_rewrite SET subject_id = 'x'",
        "DELETE FROM ledger_rewrite",
        "TRUNCATE ledger_rewrite",
    ):
        with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
            connection.execute(text(statement))
    assert count(atlas, "ledger_rewrite") == 1


def test_a_finding_is_unique_to_its_edition_kind_subject_and_field(atlas: Atlas) -> None:
    stored = stored_with(atlas, "photonics", lambda d: d["predictions"].pop(0))
    with atlas.engine.connect() as connection:
        row = connection.execute(
            text("SELECT edition_id, previous_edition_id FROM ledger_rewrite")
        ).one()

    with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ledger_rewrite (id, edition_id, previous_edition_id, kind,"
                " subject_id, found_at) VALUES (gen_random_uuid(), :e, :p, 'prediction_removed',"
                " 'pho-p1', now())"
            ),
            {"e": row.edition_id, "p": row.previous_edition_id},
        )
    assert str(row.edition_id) == stored
