"""The rewrite check (atlas-record ticket 02): `compare_ledgers`, pure.

Each pair is a snapshot of 2026-10-19 (`tests/fixtures/artifacts/`) and a hand-edited copy of its
parsed ledger, built here: the fixture files are never touched. The copy is the "next week"
edition (as-of a week on, the edition number up by one) with one thing changed.
"""

import copy
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from atlas.record import CouncilLedger, ThemeLedger, parse_page
from atlas.record.rewrites import Rewrite, compare_ledgers

PAGES = Path(__file__).resolve().parents[1] / "fixtures" / "artifacts" / "2026-10-19"


def raw(name: str) -> dict[str, Any]:
    parsed = parse_page((PAGES / f"{name}.html").read_bytes()).raw
    assert parsed is not None
    return parsed


def theme(data: dict[str, Any]) -> ThemeLedger:
    return ThemeLedger.model_validate(data)


def council(data: dict[str, Any]) -> CouncilLedger:
    return CouncilLedger.model_validate(data)


def next_week(data: dict[str, Any]) -> dict[str, Any]:
    """A copy of the ledger one edition on, as the task would publish it unchanged."""
    following = copy.deepcopy(data)
    key = "council_as_of" if "board" in data else "as_of"
    following[key] = (date.fromisoformat(data[key]) + timedelta(days=7)).isoformat()
    following["edition"] = data["edition"] + 1
    return following


def edited(name: str, change: Callable[[dict[str, Any]], None]) -> list[Rewrite]:
    previous = raw(name)
    following = next_week(previous)
    change(following)
    if "board" in previous:
        return compare_ledgers(council(following), council(previous))
    return compare_ledgers(theme(following), theme(previous))


def only(findings: list[Rewrite]) -> Rewrite:
    assert len(findings) == 1, findings
    return findings[0]


# The fixtures, by what they carry: aerospace has `earliest_evidence`; photonics does not.


def test_an_unchanged_second_edition_finds_nothing() -> None:
    for name in (
        "photonics",
        "memory-packaging",
        "robotics",
        "power-equipment",
        "aerospace-defence",
        "nuclear",
        "quantum",
    ):
        previous = raw(name)
        assert compare_ledgers(theme(next_week(previous)), theme(previous)) == [], name
    previous = raw("council")
    assert compare_ledgers(council(next_week(previous)), council(previous)) == []


def test_new_chokepoints_predictions_and_a_new_settlement_are_no_finding() -> None:
    def change(data: dict[str, Any]) -> None:
        data["chokepoints"].append(
            {"id": "pho-99", "name": "A new one", "first_seen": "2026-10-26"}
        )
        data["predictions"].append({"id": "pho-p99", "text": "A new prediction"})
        data["predictions"][0].update(
            state="met",
            settled_on="2026-10-26",
            settlement_quote="we are still shipping behind demand",
            settlement_url="https://example.com/call",
        )

    assert edited("photonics", change) == []


def test_a_ledger_that_lacks_earliest_evidence_finds_nothing() -> None:
    def strip(data: dict[str, Any]) -> None:
        for chokepoint in data["chokepoints"]:
            chokepoint.pop("earliest_evidence", None)
            chokepoint.pop("consensus", None)
        data.pop("council_answers", None)

    # Aerospace carries the fields (its prompt was revised); the next edition lacks them.
    assert "earliest_evidence" in raw("aerospace-defence")["chokepoints"][0]
    assert edited("aerospace-defence", strip) == []
    # Photonics never had them; an edition that gains them is no rewrite either.
    gained = edited("photonics", lambda d: d["chokepoints"][0].update(earliest_evidence="2026-10"))
    assert gained == []


def test_a_past_prediction_whose_deadline_moved_is_changed() -> None:
    finding = only(edited("photonics", lambda d: d["predictions"][0].update(deadline="2027-06-30")))

    assert finding.kind == "prediction_changed"
    assert (finding.subject_id, finding.field) == ("pho-p1", "deadline")
    assert (finding.before, finding.after) == ("2027-02-15", "2027-06-30")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("text", "By 2027-02-15, Lumentum will say something far safer."),
        ("deadline", "2027-03-01"),
        ("chokepoint", "pho-2"),
        ("made", "2026-10-26"),
    ],
)
def test_each_of_a_predictions_four_fields_is_checked(field: str, value: str) -> None:
    finding = only(edited("photonics", lambda d: d["predictions"][0].update({field: value})))

    assert (finding.kind, finding.subject_id, finding.field) == (
        "prediction_changed",
        "pho-p1",
        field,
    )
    assert finding.after == value
    assert finding.before == raw("photonics")["predictions"][0][field]


def test_a_prediction_that_is_gone_is_removed() -> None:
    finding = only(edited("photonics", lambda d: d["predictions"].pop(0)))

    assert finding.kind == "prediction_removed"
    assert finding.subject_id == "pho-p1"
    assert finding.after is None
    assert finding.before["text"].startswith("By 2027-02-15, Lumentum")


def settled_before(data: dict[str, Any]) -> None:
    data["predictions"][0].update(
        state="met",
        settled_on="2026-10-26",
        settlement_quote="we are still shipping behind demand",
        settlement_url="https://example.com/call",
    )


def test_a_settled_prediction_that_is_open_again_is_unsettled() -> None:
    previous = raw("photonics")
    settled_before(previous)
    following = next_week(previous)
    following["predictions"][0].update(
        state="open", settled_on=None, settlement_quote=None, settlement_url=None
    )

    finding = only(compare_ledgers(theme(following), theme(previous)))

    assert (finding.kind, finding.subject_id) == ("prediction_unsettled", "pho-p1")
    assert finding.before["state"] == "met" and finding.after["state"] == "open"


def test_a_settlement_that_changed_is_unsettled() -> None:
    previous = raw("photonics")
    settled_before(previous)
    following = next_week(previous)
    following["predictions"][0]["settlement_quote"] = "a different quote"

    finding = only(compare_ledgers(theme(following), theme(previous)))

    assert finding.kind == "prediction_unsettled"
    assert finding.before["settlement_quote"] == "we are still shipping behind demand"
    assert finding.after["settlement_quote"] == "a different quote"
    # The same settlement again is no finding.
    assert compare_ledgers(theme(next_week(previous)), theme(previous)) == []


def test_a_chokepoint_whose_id_is_gone_has_vanished() -> None:
    finding = only(edited("photonics", lambda d: d["chokepoints"].pop(0)))

    assert (finding.kind, finding.subject_id) == ("chokepoint_vanished", "pho-1")
    assert finding.before["name"].startswith("InP laser-chip")
    assert finding.after is None


def test_a_chokepoint_marked_killed_may_leave() -> None:
    previous = raw("photonics")
    previous["chokepoints"][0]["status"] = "killed"
    following = next_week(previous)
    following["chokepoints"].pop(0)

    assert compare_ledgers(theme(following), theme(previous)) == []


def test_an_id_kept_for_another_name_or_layer_is_reused() -> None:
    renamed = only(
        edited("photonics", lambda d: d["chokepoints"][0].update(name="Silicon photonics foundry"))
    )
    relayered = only(edited("photonics", lambda d: d["chokepoints"][0].update(layer="module")))

    assert (renamed.kind, renamed.subject_id, renamed.field) == ("id_reused", "pho-1", "name")
    assert renamed.after == "Silicon photonics foundry"
    assert (relayered.kind, relayered.field) == ("id_reused", "layer")
    assert (relayered.before, relayered.after) == ("chip", "module")


def test_a_name_that_differs_only_in_case_punctuation_and_whitespace_is_the_same() -> None:
    name = raw("photonics")["chokepoints"][0]["name"]

    def reword(data: dict[str, Any]) -> None:
        data["chokepoints"][0]["name"] = f"  {name.upper().replace(' ', '  ')}. "
        data["chokepoints"][0]["layer"] = "CHIP!"

    assert edited("photonics", reword) == []


@pytest.mark.parametrize("field", ["first_seen", "earliest_evidence"])
def test_a_date_that_moved_later_is_found(field: str) -> None:
    previous = raw("aerospace-defence")
    old = previous["chokepoints"][0][field]
    assert old is not None

    finding = only(
        edited("aerospace-defence", lambda d: d["chokepoints"][0].update({field: "2027-01"}))
    )

    assert (finding.kind, finding.subject_id, finding.field) == (
        "date_moved_later",
        "aer-1",
        field,
    )
    assert (finding.before, finding.after) == (old, "2027-01")


def test_a_date_that_moved_earlier_or_only_gained_precision_is_no_finding() -> None:
    def earlier(data: dict[str, Any]) -> None:
        data["chokepoints"][0]["earliest_evidence"] = "2020-01"
        data["chokepoints"][0]["first_seen"] = "2020-01-01"

    assert edited("aerospace-defence", earlier) == []
    # A month that gains its day is the same month.
    previous = raw("aerospace-defence")
    previous["chokepoints"][0]["earliest_evidence"] = "2026-07"
    following = next_week(previous)
    following["chokepoints"][0]["earliest_evidence"] = "2026-07-28"
    assert compare_ledgers(theme(following), theme(previous)) == []


def test_an_edition_number_that_did_not_rise_is_found() -> None:
    previous = raw("photonics")
    following = next_week(previous)
    following["edition"] = previous["edition"]

    finding = only(compare_ledgers(theme(following), theme(previous)))

    assert (finding.kind, finding.subject_id, finding.field) == (
        "edition_not_increasing",
        "photonics",
        "edition",
    )
    assert (finding.before, finding.after) == (1, 1)


def test_the_council_is_compared_the_same_way_but_leaving_the_board_is_no_finding() -> None:
    def vanish(data: dict[str, Any]) -> None:
        data["board"].pop(0)

    def retheme(data: dict[str, Any]) -> None:
        data["board"][1]["theme"] = "robotics"

    def later(data: dict[str, Any]) -> None:
        data["board"][0]["earliest_evidence"] = "2027-01"

    def deadline(data: dict[str, Any]) -> None:
        data["predictions"][0]["deadline"] = "2027-12-31"

    def remove(data: dict[str, Any]) -> None:
        data["predictions"].pop(0)

    def contradiction(data: dict[str, Any]) -> None:
        data["contradictions"][0]["first_seen"] = "2026-12-01"

    previous = raw("council")
    first = previous["board"][0]
    assert first["chokepoint_id"] and edited("council", vanish) == []
    reused = only(edited("council", retheme))
    assert (reused.kind, reused.field, reused.after) == ("id_reused", "theme", "robotics")
    assert only(edited("council", later)).kind == "date_moved_later"
    changed = only(edited("council", deadline))
    assert (changed.kind, changed.subject_id) == ("prediction_changed", "cou-p1")
    assert only(edited("council", remove)).kind == "prediction_removed"
    moved = only(edited("council", contradiction))
    assert (moved.kind, moved.subject_id, moved.field) == (
        "date_moved_later",
        "ccx-1",
        "first_seen",
    )
    assert (moved.before, moved.after) == ("2026-10-19", "2026-12-01")


def test_the_findings_come_in_a_fixed_order() -> None:
    def many(data: dict[str, Any]) -> None:
        data["edition"] = 1
        data["chokepoints"].pop(0)
        data["predictions"][0]["deadline"] = "2030-01-01"
        data["chokepoints"][0]["name"] = "Something else"

    findings = edited("photonics", many)

    assert [f.kind for f in findings] == [
        "edition_not_increasing",
        "chokepoint_vanished",
        "id_reused",
        "prediction_changed",
    ]
    assert edited("photonics", many) == findings
