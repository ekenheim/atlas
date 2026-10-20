"""The artifact page's ledger (atlas-record ticket 01): `atlas.record.parse`, pure.

The eight pages are the byte-exact snapshots of 2026-10-19 (`tests/fixtures/artifacts/`). The
expected counts were read off each page's own JSON, not computed by the parser.
"""

import json
from datetime import date

import pytest

from atlas.record import CouncilLedger, ThemeLedger, parse_page
from tests.harness import REPO

PAGES = REPO / "tests" / "fixtures" / "artifacts" / "2026-10-19"

# theme, chokepoints, predictions, rejected, cross-theme hooks, primary sources
THEMES = [
    ("photonics", 2, 4, 5, 3, 21),
    ("memory-packaging", 3, 4, 6, 3, 22),
    ("robotics", 2, 3, 2, 3, 16),
    ("power-equipment", 3, 4, 2, 3, 18),
    ("aerospace-defence", 2, 4, 7, 3, 17),
    ("nuclear", 3, 5, 3, 3, 25),
    ("quantum", 2, 3, 6, 3, 16),
]
# The revised prompts (aerospace, nuclear, quantum) write these; the other four do not.
REVISED = {"aerospace-defence", "nuclear", "quantum"}


def page(name: str) -> bytes:
    return (PAGES / f"{name}.html").read_bytes()


def block(payload: str, *, pre: str = "<pre>") -> bytes:
    return f"<html><body><title>t</title>{pre}{payload}</pre></body></html>".encode()


@pytest.mark.parametrize(
    ("name", "chokepoints", "predictions", "rejected", "hooks", "sources"), THEMES
)
def test_each_theme_page_parses_to_its_ledger(
    name: str, chokepoints: int, predictions: int, rejected: int, hooks: int, sources: int
) -> None:
    parsed = parse_page(page(name))

    assert parsed.error is None
    ledger = parsed.ledger
    assert isinstance(ledger, ThemeLedger)
    assert (ledger.theme, ledger.as_of, ledger.edition) == (name, date(2026, 10, 19), 1)
    assert len(ledger.chokepoints) == chokepoints
    assert len(ledger.predictions) == predictions
    assert len(ledger.rejected) == rejected
    assert len(ledger.cross_theme_hooks) == hooks
    assert len(ledger.primary_sources) == sources
    assert all(source.url and source.quote for source in ledger.primary_sources)


@pytest.mark.parametrize("name", [row[0] for row in THEMES])
def test_the_optional_fields_are_absent_or_present_as_the_prompt_wrote_them(name: str) -> None:
    ledger = parse_page(page(name)).ledger
    assert isinstance(ledger, ThemeLedger)

    revised = name in REVISED
    assert all((c.earliest_evidence is not None) == revised for c in ledger.chokepoints)
    assert all((c.consensus is not None) == revised for c in ledger.chokepoints)
    assert (ledger.council_answers is not None) == revised
    assert (ledger.notes is not None) == (name == "nuclear")


def test_the_council_page_parses_to_the_councils_ledger() -> None:
    parsed = parse_page(page("council"))

    assert parsed.error is None
    ledger = parsed.ledger
    assert isinstance(ledger, CouncilLedger)
    assert (ledger.as_of, ledger.edition) == (date(2026, 10, 19), 2)
    assert len(ledger.themes) == 7
    assert len(ledger.board) == 5
    assert ledger.board[0].chokepoint_id == "mem-1"
    assert len(ledger.stacks) == 9
    assert len(ledger.contradictions) == 4
    assert len(ledger.predictions) == 4
    assert len(ledger.assignments_answered) == 10
    assert len(ledger.subagents) == 19
    assert ledger.primary_sources == []  # the council's ledger has none (yet)


def test_the_raw_object_is_kept_as_the_page_wrote_it() -> None:
    parsed = parse_page(page("nuclear"))

    assert parsed.raw is not None
    assert parsed.raw["notes"].startswith("All quotes are fetch-tool excerpts")
    assert list(parsed.raw)[:3] == ["theme", "as_of", "edition"]


def test_a_ledger_without_fences_or_an_id_parses() -> None:
    # power-equipment has no code fences and no id="ledger"; so does this one, by hand.
    payload = json.dumps({"theme": "x", "as_of": "2026-10-26", "edition": 3, "chokepoints": []})

    ledger = parse_page(block(payload)).ledger

    assert isinstance(ledger, ThemeLedger)
    assert (ledger.theme, ledger.as_of, ledger.edition) == ("x", date(2026, 10, 26), 3)


def test_tags_and_entities_in_the_block_are_stripped_and_unescaped() -> None:
    payload = (
        "```json\n<code>{&quot;theme&quot;: &quot;x&quot;,"
        " &quot;as_of&quot;: &quot;2026-10-26&quot;,"
        " &quot;edition&quot;: 1, &quot;chokepoints&quot;: [{&quot;id&quot;: &quot;x-1&quot;,"
        " &quot;name&quot;: &quot;A &amp; B &lt;C&gt;&quot;}]}</code>\n```"
    )

    ledger = parse_page(block(payload, pre='<pre id="ledger" class="a">')).ledger

    assert isinstance(ledger, ThemeLedger)
    assert ledger.chokepoints[0].name == "A & B <C>"


def test_the_first_block_that_is_a_ledger_wins_and_others_are_skipped() -> None:
    other = '<pre>not json at all</pre><pre>[1, 2]</pre><pre>{"unrelated": 1}</pre>'
    first = json.dumps({"theme": "a", "as_of": "2026-10-19", "edition": 1, "chokepoints": []})
    second = json.dumps({"theme": "b", "as_of": "2026-10-19", "edition": 1, "chokepoints": []})
    html = f"<body>{other}<pre>{first}</pre><pre>{second}</pre></body>".encode()

    ledger = parse_page(html).ledger

    assert isinstance(ledger, ThemeLedger)
    assert ledger.theme == "a"


def test_unknown_fields_are_kept_and_missing_optional_ones_tolerated() -> None:
    payload = json.dumps(
        {
            "theme": "x",
            "as_of": "2026-10-19",
            "edition": 1,
            "new_top_level": {"a": 1},
            "chokepoints": [{"id": "x-1", "name": "N", "new_field": [1]}],
            "predictions": [{"id": "x-p1", "text": "T", "extra": True}],
        }
    )

    ledger = parse_page(block(payload)).ledger

    assert isinstance(ledger, ThemeLedger)
    dumped = ledger.model_dump(mode="json")
    assert dumped["new_top_level"] == {"a": 1}
    assert dumped["chokepoints"][0]["new_field"] == [1]
    assert dumped["predictions"][0]["extra"] is True
    assert ledger.chokepoints[0].earliest_evidence is None
    assert ledger.predictions[0].state is None


@pytest.mark.parametrize(
    ("html", "reason"),
    [
        (b"<html><body><p>nothing here</p></body></html>", "no_ledger"),
        (b"", "no_ledger"),
        (b"\xff\xfe<pre>\x80</pre>", "no_ledger"),
        (block('{"a": 1}'), "no_ledger"),
        (block("{ truncated"), "no_ledger"),
        (block('{"chokepoints": []}'), "invalid_ledger"),
        (
            block('{"theme": "x", "as_of": "next week", "edition": 1, "chokepoints": []}'),
            "invalid_ledger",
        ),
        (block('{"board": [{"rank": "first"}]}'), "invalid_ledger"),
    ],
)
def test_a_page_with_no_usable_ledger_is_an_error_not_an_exception(
    html: bytes, reason: str
) -> None:
    parsed = parse_page(html)

    assert parsed.ledger is None
    assert parsed.raw is None
    assert parsed.error is not None
    assert parsed.error.startswith(f"{reason}:")


def test_parsing_is_deterministic() -> None:
    data = page("quantum")

    assert parse_page(data) == parse_page(data)
