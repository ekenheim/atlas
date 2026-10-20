"""The edition store (atlas-record ticket 01): the scheduled tasks' pages, kept insert-only.

Seams: the `atlas record import` CLI and `/api/v1/editions`, on a fresh database. The pages are
the byte-exact snapshots of 2026-10-19 (`tests/fixtures/artifacts/`); a few hand-written pages
cover what they do not (a rewrite the same day, a page with no ledger). The insert-only table is
attacked through the engine.
"""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.harness import REPO, Atlas

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
# From the MANIFEST's table: what the snapshot hashed to when it was read.
PHOTONICS_SHA256 = "1116274ec8f09f17039e4e33205977e26c33d90ade211bbb6baf6317d8171404"
COMMIT = "9fceb02d0ae598e95dc970b74767f19372d61af8"
NO_SUCH_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, "")
    yield harness
    harness.engine.dispose()


def page(name: str) -> bytes:
    return (PAGES / f"{name}.html").read_bytes()


def hand_written(theme: str, as_of: str, edition: int, note: str = "") -> bytes:
    ledger = {
        "theme": theme,
        "as_of": as_of,
        "edition": edition,
        "chokepoints": [{"id": "x-1", "name": f"A chokepoint {note}"}],
        "primary_sources": [],
    }
    return f'<html><body><pre id="ledger">{json.dumps(ledger)}</pre></body></html>'.encode()


def cli_import(atlas: Atlas, theme: str, page: bytes, *extra: str) -> dict[str, Any]:
    file = atlas.tmp_path / f"{theme}-{hashlib.sha256(page).hexdigest()[:8]}.html"
    file.write_bytes(page)
    result = atlas.cli("record", "import", "--theme", theme, "--file", str(file), *extra)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def post(atlas: Atlas, theme: str, page: bytes, **params: str) -> Any:
    return atlas.api.post(
        "/api/v1/editions",
        params={"theme": theme, **params},
        content=page,
        headers={"Content-Type": "text/html"},
    )


def audit_actions(atlas: Atlas, entity_id: str) -> list[tuple[str, str]]:
    with atlas.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT action, actor FROM audit_event WHERE entity_id = :id ORDER BY id"),
            {"id": entity_id},
        )
        return [(row.action, row.actor) for row in rows]


def row_count(atlas: Atlas) -> int:
    with atlas.engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM ledger_edition")).scalar_one()


def test_the_eight_fixtures_import_through_the_cli(atlas: Atlas) -> None:
    imported = {
        name: cli_import(atlas, "council" if name == "council" else name, page(name))
        for name in (*THEMES, "council")
    }

    assert all(result["outcome"] == "imported" for result in imported.values())
    assert row_count(atlas) == 8
    listed = atlas.get("/api/v1/editions")
    assert listed["total"] == 8
    found = {(e["theme"], e["as_of"], e["edition"]) for e in listed["items"]}
    assert found == {(name, "2026-10-19", 1) for name in THEMES} | {("council", "2026-10-19", 2)}
    assert all(e["source"] == "manual" and e["commit_sha"] is None for e in listed["items"])
    assert all(e["parse_error"] is None and not e["same_as_of_differs"] for e in listed["items"])
    assert "ledger" not in listed["items"][0]


def test_an_edition_reads_back_with_its_ledger_and_its_page(atlas: Atlas) -> None:
    result = cli_import(atlas, "nuclear", page("nuclear"))

    edition = atlas.get(f"/api/v1/editions/{result['id']}")

    assert (edition["theme"], edition["as_of"], edition["edition"]) == (
        "nuclear",
        "2026-10-19",
        1,
    )
    ledger = edition["ledger"]
    assert len(ledger["chokepoints"]) == 3
    assert ledger["chokepoints"][0]["id"] == "nuc-1"
    assert ledger["notes"].startswith("All quotes are fetch-tool excerpts")
    assert len(ledger["primary_sources"]) == 25
    assert edition["parse_error"] is None
    assert edition["page_uri"] == f"archive://raw/sha256/{edition['page_sha256']}"
    # The page is in the archive, byte for byte, under a sandboxing policy.
    download = atlas.api.get(edition["page_href"])
    assert download.status_code == 200
    assert download.content == page("nuclear")
    assert hashlib.sha256(download.content).hexdigest() == edition["page_sha256"]
    assert "sandbox" in download.headers["content-security-policy"]
    assert download.headers["content-disposition"].startswith("attachment")


def test_the_page_is_kept_as_the_manifest_hashed_it(atlas: Atlas) -> None:
    result = cli_import(atlas, "photonics", page("photonics"))

    edition = atlas.get(f"/api/v1/editions/{result['id']}")

    assert edition["page_sha256"] == PHOTONICS_SHA256
    assert edition["page_size"] == len(page("photonics"))


def test_the_council_is_kept_under_the_council_theme(atlas: Atlas) -> None:
    result = cli_import(atlas, "council", page("council"))

    edition = atlas.get(f"/api/v1/editions/{result['id']}")

    assert (edition["theme"], edition["as_of"], edition["edition"]) == (
        "council",
        "2026-10-19",
        2,
    )
    assert edition["ledger"]["board"][0]["chokepoint_id"] == "mem-1"
    assert len(edition["ledger"]["subagents"]) == 19
    assert [e["theme"] for e in atlas.get("/api/v1/editions", theme="council")["items"]] == [
        "council"
    ]


def test_importing_the_same_bytes_twice_stores_one_row(atlas: Atlas) -> None:
    first = cli_import(atlas, "quantum", page("quantum"))
    second = cli_import(atlas, "quantum", page("quantum"))
    third = post(atlas, "quantum", page("quantum"))

    assert (first["outcome"], second["outcome"]) == ("imported", "unchanged")
    assert second["id"] == first["id"]
    assert third.status_code == 200
    assert third.json()["outcome"] == "unchanged"
    assert third.json()["edition"]["id"] == first["id"]
    assert row_count(atlas) == 1
    # Only the first import was a change, so only it is audited.
    assert audit_actions(atlas, first["id"]) == [("edition.imported", "local-researcher")]


def test_an_import_through_the_api_is_audited_and_marks_its_source(atlas: Atlas) -> None:
    response = post(atlas, "robotics", page("robotics"), source="drop_box", commit_sha=COMMIT)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["outcome"] == "imported"
    edition = body["edition"]
    assert (edition["theme"], edition["source"], edition["commit_sha"]) == (
        "robotics",
        "drop_box",
        COMMIT,
    )
    assert edition["ledger"]["theme"] == "robotics"
    assert audit_actions(atlas, edition["id"]) == [("edition.imported", "local-researcher")]
    assert atlas.get(f"/api/v1/editions/{edition['id']}")["commit_sha"] == COMMIT


def test_the_same_day_with_other_bytes_is_kept_and_marked_a_rewrite(atlas: Atlas) -> None:
    first = cli_import(atlas, "photonics", hand_written("photonics", "2026-10-26", 2, "v1"))
    rewritten = cli_import(atlas, "photonics", hand_written("photonics", "2026-10-26", 2, "v2"))
    next_week = cli_import(atlas, "photonics", hand_written("photonics", "2026-11-02", 3, "v3"))
    other_theme = cli_import(atlas, "robotics", hand_written("robotics", "2026-10-26", 2, "v1"))

    assert [r["outcome"] for r in (first, rewritten, next_week, other_theme)] == ["imported"] * 4
    assert (first["same_as_of_differs"], rewritten["same_as_of_differs"]) == (False, True)
    assert not next_week["same_as_of_differs"] and not other_theme["same_as_of_differs"]
    assert row_count(atlas) == 4
    items = atlas.get("/api/v1/editions", theme="photonics")["items"]
    # Newest first: the later as-of day, then the rewrite before the original.
    assert [i["id"] for i in items] == [next_week["id"], rewritten["id"], first["id"]]
    assert [i["same_as_of_differs"] for i in items] == [False, True, False]


def test_a_page_with_no_ledger_is_kept_with_its_error(atlas: Atlas) -> None:
    page_without = b"<html><body><p>The task failed and published an apology.</p></body></html>"

    file = atlas.tmp_path / "apology.html"
    file.write_bytes(page_without)
    run = atlas.cli("record", "import", "--theme", "photonics", "--file", str(file))
    again = post(atlas, "photonics", page_without)

    assert run.returncode == 0, run.stderr
    assert "no readable ledger" in run.stderr
    stored = json.loads(run.stdout)
    assert stored["outcome"] == "imported"
    assert stored["as_of"] is None and stored["edition"] is None
    assert stored["parse_error"].startswith("no_ledger:")
    assert again.status_code == 200 and again.json()["outcome"] == "unchanged"
    edition = atlas.get(f"/api/v1/editions/{stored['id']}")
    assert edition["ledger"] is None
    assert edition["parse_error"].startswith("no_ledger:")
    assert row_count(atlas) == 1


def test_a_ledger_that_does_not_fit_is_kept_with_its_error(atlas: Atlas) -> None:
    broken = b'<pre>{"theme": "photonics", "as_of": "soon", "edition": 1, "chokepoints": []}</pre>'

    response = post(atlas, "photonics", broken)

    assert response.status_code == 201
    edition = response.json()["edition"]
    assert edition["ledger"] is None
    assert edition["parse_error"].startswith("invalid_ledger:")
    assert edition["as_of"] is None


def test_a_page_filed_under_the_wrong_theme_is_refused(atlas: Atlas) -> None:
    refused = post(atlas, "robotics", page("photonics"))
    file = atlas.tmp_path / "photonics.html"
    file.write_bytes(page("photonics"))
    cli = atlas.cli("record", "import", "--theme", "council", "--file", str(file))

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "theme_mismatch"
    assert cli.returncode == 2
    assert "theme_mismatch" in cli.stderr
    assert row_count(atlas) == 0


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"source": "drop_box"}, "invalid_source"),
        ({"source": "manual", "commit_sha": COMMIT}, "invalid_source"),
        ({"source": "drop_box", "commit_sha": "main"}, "invalid_commit_sha"),
        ({"theme": "Photonics!"}, "invalid_theme"),
    ],
)
def test_a_bad_import_request_is_refused_and_stores_nothing(
    atlas: Atlas, params: dict[str, str], code: str
) -> None:
    arguments = {"theme": "photonics"} | params

    response = post(atlas, arguments.pop("theme"), page("photonics"), **arguments)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert row_count(atlas) == 0


def test_an_empty_body_and_a_missing_theme_are_refused(atlas: Atlas) -> None:
    empty = post(atlas, "photonics", b"")
    no_theme = atlas.api.post("/api/v1/editions", content=page("photonics"))

    assert empty.status_code == 422 and empty.json()["error"]["code"] == "empty_page"
    assert no_theme.status_code == 422
    assert row_count(atlas) == 0


def test_the_list_filters_by_theme_and_pages(atlas: Atlas) -> None:
    for name in ("photonics", "robotics", "quantum"):
        cli_import(atlas, name, page(name))

    robotics = atlas.get("/api/v1/editions", theme="robotics")
    first_page = atlas.get("/api/v1/editions", limit=2)
    second_page = atlas.get("/api/v1/editions", limit=2, offset=2)

    assert [e["theme"] for e in robotics["items"]] == ["robotics"]
    assert robotics["total"] == 1
    assert (first_page["total"], len(first_page["items"]), len(second_page["items"])) == (3, 2, 1)
    nothing = atlas.get("/api/v1/editions", theme="nuclear")
    assert (nothing["items"], nothing["total"]) == ([], 0)


def test_an_unknown_edition_is_not_found(atlas: Atlas) -> None:
    for path in (f"/api/v1/editions/{NO_SUCH_ID}", f"/api/v1/editions/{NO_SUCH_ID}/page"):
        response = atlas.api.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    assert atlas.api.get("/api/v1/editions/not-an-id").status_code == 422


def test_an_edition_cannot_be_changed_or_removed(atlas: Atlas) -> None:
    cli_import(atlas, "photonics", page("photonics"))

    # Since migration 0123 `ledger_rewrite` references the table, so a plain TRUNCATE is refused
    # by the foreign key before the trigger; the CASCADE form reaches the triggers.
    for statement in (
        "UPDATE ledger_edition SET theme = 'robotics'",
        "UPDATE ledger_edition SET same_as_of_differs = true",
        "DELETE FROM ledger_edition",
        "TRUNCATE ledger_edition",
        "TRUNCATE ledger_edition CASCADE",
    ):
        message = (
            "cannot truncate|insert-only"
            if statement == "TRUNCATE ledger_edition"
            else ("insert-only")
        )
        with pytest.raises(DBAPIError, match=message), atlas.engine.begin() as connection:
            connection.execute(text(statement))
    assert row_count(atlas) == 1


def test_the_table_refuses_what_the_service_never_writes(atlas: Atlas) -> None:
    insert = (
        "INSERT INTO ledger_edition (id, theme, as_of, edition, page_sha256, page_uri, page_size,"
        " ledger, parse_error, source, commit_sha, read_at) VALUES (gen_random_uuid(), 'x',"
        " {as_of}, {edition}, repeat('a', 64), 'archive://raw/sha256/' || repeat('a', 64), 1,"
        " {ledger}, {error}, '{source}', {commit}, now())"
    )
    cases = [
        # a ledger with a parse error, and neither
        {"ledger": "'{}'", "error": "'e'", "as_of": "'2026-10-19'", "edition": "1"},
        {"ledger": "NULL", "error": "NULL", "as_of": "NULL", "edition": "NULL"},
        # a parsed ledger with no day; an error with a day
        {"ledger": "'{}'", "error": "NULL", "as_of": "NULL", "edition": "1"},
        {"ledger": "NULL", "error": "'e'", "as_of": "'2026-10-19'", "edition": "NULL"},
        # a drop-box page with no commit
        {
            "ledger": "'{}'",
            "error": "NULL",
            "as_of": "'2026-10-19'",
            "edition": "1",
            "source": "drop_box",
        },
        # an unknown source
        {"ledger": "'{}'", "error": "NULL", "as_of": "'2026-10-19'", "edition": "1", "source": "x"},
    ]
    for case in cases:
        values = {"source": "manual", "commit": "NULL"} | case
        with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
            connection.execute(text(insert.format(**values)))
    assert row_count(atlas) == 0
