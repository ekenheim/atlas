"""The gold set (ticket 25; docs/evaluation-methodology.md): the committed cases are valid, cover
the categories the ticket asks for, and the validator catches what the methodology forbids.

Seam: `atlas.evaluation.validate_gold`, the methodology's validator (§9), over the committed
`tests/evaluation/gold/` and over tampered copies of it.
"""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from atlas.evaluation import open_gold, validate_gold

GOLD = Path(__file__).parents[2] / "tests" / "evaluation" / "gold"
# Ticket 25's traps and outcomes: supplier edge, reversed direction, co-mention, partner page,
# layer confusion, syndication, hedged language, future-dated leakage, restatement, Skeptic.
REQUIRED = {"SUP", "DIR", "COM", "INF", "LAY", "SYN", "HED", "FUT", "RST", "CON"}


@pytest.fixture
def gold(tmp_path: Path) -> Path:
    """A copy of the committed gold set to tamper with."""
    copy = tmp_path / "gold"
    shutil.copytree(GOLD, copy)
    return copy


def manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def rewrite_case(root: Path, case_id: str, change: Any) -> None:
    """Edit a case and re-pin it in the manifest (as a new case would be): only the content
    checks can then fail."""
    path = root / "cases" / f"{case_id}.json"
    case = json.loads(path.read_text(encoding="utf-8"))
    change(case)
    raw = (json.dumps(case, indent=2) + "\n").encode()
    path.write_bytes(raw)
    index = manifest(root)
    for entry in index["cases"]:
        if entry["case_id"] == case_id:
            entry["case_sha256"] = hashlib.sha256(raw).hexdigest()
    (root / "manifest.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


def test_the_committed_gold_set_is_valid() -> None:
    assert validate_gold(GOLD) == []


def test_it_holds_10_to_15_active_cases_covering_the_ticket_s_categories() -> None:
    entries = manifest(GOLD)["cases"]
    active = [e for e in entries if e["status"] == "active"]
    assert 10 <= len(active) <= 15
    assert {e["category"] for e in active} >= REQUIRED
    for entry in active:
        case = open_gold(GOLD).load(entry["case_id"]).case
        assert case.gold.model_dump(exclude_defaults=True), entry["case_id"]
        assert case.adjudication.labeler
        # Fictional companies by default; a real one only with redistributable sources.
        if not all(entity.fictional for entity in case.entities):
            assert {s.provenance for s in case.sources} == {"redistributable"}


def test_a_changed_case_file_fails_its_pinned_hash(gold: Path) -> None:
    path = gold / "cases" / "EV-SUP-001.json"
    path.write_text(path.read_text(encoding="utf-8").replace("supplier", "vendor"), "utf-8")

    problems = validate_gold(gold)

    assert any("EV-SUP-001 changed" in p and "immutable" in p for p in problems)


def test_a_changed_source_file_fails_its_content_address(gold: Path) -> None:
    source = open_gold(gold).load("EV-SUP-001").case.sources[0]
    path = gold / "sources" / f"{source.sha256}.html"
    path.write_bytes(path.read_bytes().replace(b"Fremont", b"Oakland"))

    problems = validate_gold(gold)

    assert any("source s1" in p and "hashes to" in p for p in problems)


def test_a_gold_quote_must_occur_exactly_in_its_source_s_parse(gold: Path) -> None:
    def paraphrase(case: dict[str, Any]) -> None:
        case["gold"]["citations"][0]["quote"] = (
            "Borealis Substrates is Aurora's substrate supplier."
        )

    rewrite_case(gold, "EV-SUP-001", paraphrase)

    problems = validate_gold(gold)

    assert problems == [
        'EV-SUP-001: the gold quote "Borealis Substrates is Aurora\'s substrate supplier."'
        " doesn't occur in s1's parse"
    ]


def test_unknown_keys_licences_and_unlisted_cases_are_refused(gold: Path) -> None:
    def break_it(case: dict[str, Any]) -> None:
        case["gold"]["relationships"][0]["object"] = "zephyr"
        case["sources"][0]["license_class"] = "licensed_full_text"
        case["script"]["investigator"][0]["claims"][0]["subject"] = "zephyr"

    rewrite_case(gold, "EV-SUP-001", break_it)
    (gold / "cases" / "EV-SUP-999.json").write_text("{}", encoding="utf-8")

    problems = validate_gold(gold)

    assert "EV-SUP-001: unknown entity 'zephyr'" in problems
    assert any("licence 'licensed_full_text' can't be committed" in p for p in problems)
    assert "EV-SUP-999.json: a case file the manifest doesn't list" in problems


def test_case_ids_follow_the_pattern_and_are_unique(gold: Path) -> None:
    index = manifest(gold)
    index["cases"].append(dict(index["cases"][0]))
    index["cases"].append(index["cases"][1] | {"case_id": "EV-SUP-1"})
    (gold / "manifest.json").write_text(json.dumps(index), encoding="utf-8")

    problems = validate_gold(gold)

    assert f"{index['cases'][0]['case_id']}: listed twice" in problems
    assert "EV-SUP-1: the ID doesn't match EV-<CAT>-<NNN>" in problems
