"""The memory conformance check's frame (memory-quality ticket 14): the known-answers file, how
a sentence is found, how recalls are merged, and the report's exit rule.

Seams: the file as the loader reads it (`atlas.conformance.load_known_answers`), the recorded
EDGAR fixtures each anchored answer must quote (parsed and sectioned by Atlas's own parser and
sectioner), and the report a run writes. Pure: no service is reached.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from atlas.companies import load_universe
from atlas.conformance import (
    HOPS,
    TEST_PARTS,
    CheckResult,
    ConformanceReport,
    KnownAnswersError,
    KnownAnswerSet,
    find_sentence,
    load_known_answers,
    ranked_sections,
)
from atlas.parsing import ParsedText, parse
from atlas.research.probes import load_probes
from atlas.retention.sections import split_sections

REPO = Path(__file__).parents[2]
KNOWN_ANSWERS = REPO / "configs" / "memory" / "known-answers.yaml"
PROBES = REPO / "configs" / "memory" / "probes.yaml"
THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"
EDGAR = REPO / "tests" / "fixtures" / "edgar"
# The recorded documents the anchored answers name: (company, form, primary document?).
FIXTURE_FORMS = {
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026057358/lite-20260627.htm": (
        "lumentum",
        "10-K",
    ),
    "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm": (
        "coherent",
        "10-K",
    ),
    "https://www.sec.gov/Archives/edgar/data/820318/000082031826000013/iivi-20260331.htm": (
        "coherent",
        "10-Q",
    ),
}


def load(path: Path = KNOWN_ANSWERS, **kwargs: Any) -> KnownAnswerSet:
    universe = load_universe(THEMES)
    return load_known_answers(path, universe, load_probes(PROBES, universe), **kwargs)


def test_the_configured_file_holds_at_least_20_labelled_answers_over_the_five_questions() -> None:
    answers = load().answers

    assert len(answers) >= 20
    assert {a.question for a in answers} == {
        "laser-chips",
        "inp-substrates",
        "module-assembly",
        "dsp-drivers",
        "coherent-demand",
    }
    assert all(a.hop in HOPS and a.test in TEST_PARTS for a in answers)
    assert all(len(a.sentence) >= 20 and a.review for a in answers)
    # The method's hops and test parts are covered, so a blind spot shows in the report.
    assert {"demand", "chip", "module", "substrate", "feedstock", "equipment"} <= {
        a.hop for a in answers
    }
    assert {"demand_vs_capacity", "second_source", "pricing_power", "financing_dilution"} <= {
        a.test for a in answers
    }
    # Most rest on a fact the pilot's reviews quote; none was invented.
    assert sum(a.basis == "review_quote" for a in answers) >= 15


# The 10-Q fixture is truncated at the start of Item 1.
TRUNCATED_FIXTURE = "iivi-20260331.htm"


def test_every_anchored_answer_quotes_its_section_of_the_recorded_document() -> None:
    """An answer with an anchor whose document is in the recorded fixtures quotes a sentence of
    exactly that section; the others leave the anchor to the first live run."""
    checked = 0
    for answer in load().answers:
        url = answer.document.url
        if answer.section is None or url not in FIXTURE_FORMS:
            continue
        company, form = FIXTURE_FORMS[url]
        relative = url.removeprefix("https://")
        parsed = parse((EDGAR / company / relative).read_bytes(), "text/html")
        assert isinstance(parsed, ParsedText)
        span = find_sentence(parsed.text, answer.sentence)
        if span is None and url.endswith(TRUNCATED_FIXTURE):
            continue  # its anchor comes from the first live run, not from the fixture
        assert span is not None, answer.id
        holding = [
            s.anchor
            for s in split_sections(parsed.text, form=form, primary=True)
            if s.start <= span[0] and span[1] <= s.end
        ]
        assert holding == [answer.section], answer.id
        checked += 1
    assert checked >= 15


def test_an_answer_without_an_anchor_names_a_document_the_fixtures_do_not_hold_whole() -> None:
    # The first live run (2026-10-02) filled the anchors version 1 left open; an answer added
    # without one must still name a document the fixtures cannot anchor.
    unanchored = [a for a in load().answers if a.section is None]

    for answer in unanchored:
        assert answer.document.url not in FIXTURE_FORMS or answer.document.url.endswith(
            TRUNCATED_FIXTURE
        )


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("company: lumentum", "company: acme", "unknown company acme"),
        ("question: dsp-drivers", "question: lasers", "unknown question lasers"),
        ("hop: equipment", "hop: tools", "hop"),
        ("test: pricing_power", "test: margins", "test"),
        ("id: coh-buys-dsps", "id: coh-buys-inp-substrates", "unique"),
    ],
)
def test_an_invalid_file_is_refused_at_load(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    broken = tmp_path / "known-answers.yaml"
    broken.write_text(KNOWN_ANSWERS.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    with pytest.raises(KnownAnswersError, match=message):
        load(broken)


def test_fewer_than_20_answers_are_refused(tmp_path: Path) -> None:
    raw = KNOWN_ANSWERS.read_text(encoding="utf-8")
    cut = raw[: raw.index("  # --- inp-substrates")]
    short = tmp_path / "known-answers.yaml"
    short.write_text(cut, encoding="utf-8")

    with pytest.raises(KnownAnswersError, match="at least 20 are required"):
        load(short)


RSQUO, NB_HYPHEN = chr(0x2019), chr(0x2011)  # typographic apostrophe, non-breaking hyphen


def test_a_sentence_is_found_whatever_its_typography_and_line_breaks() -> None:
    wrapped = f"Our customers{RSQUO} demand" + "\n  " + f"exceeds 6{NB_HYPHEN}inch supply."
    text = "Intro." + "\n\n" + wrapped + " Next."

    span = find_sentence(text, "Our customers' demand exceeds 6-inch supply.")

    assert span is not None
    assert text[span[0] : span[1]] == wrapped
    assert find_sentence(text, "Our suppliers' demand exceeds supply.") is None


def recall(*sections: tuple[str, str], state: str = "resolved") -> dict[str, Any]:
    return {
        "memories": [
            {
                "provenance": {
                    "state": state,
                    "sources": [{"source_document_id": d, "section_anchor": a}],
                }
            }
            for d, a in sections
        ]
    }


def test_recalls_are_merged_by_rank_each_section_once() -> None:
    first = recall(("d1", "item-1"), ("d1", "item-7"), ("d2", "item-1"))
    second = recall(("d3", "chunk-001"), ("d1", "item-1"))
    unresolved = recall(("d9", "item-1"), state="broken")

    assert ranked_sections([first, second, unresolved]) == [
        ("d1", "item-1"),
        ("d3", "chunk-001"),
        ("d1", "item-7"),
        ("d2", "item-1"),
    ]


def check(number: int, verdict: str) -> CheckResult:
    return CheckResult.model_validate(
        {
            "number": number,
            "id": f"check-{number}",
            "ticket": "03",
            "promise": "a promise",
            "source": "a sentence",
            "verdict": verdict,
            "reason": None,
            "evidence": {},
        }
    )


def test_pending_fails_the_run_only_when_strict(tmp_path: Path) -> None:
    report = ConformanceReport(
        mode="rehearse",
        strict=False,
        behaviours=[check(1, "passed"), check(2, "pending")],
        bank_id="atlas-conformance-1",
        bank_deleted=True,
    )

    assert report.exit_code() == 0
    assert report.exit_code(strict=True) == 1
    report.write(tmp_path)
    written = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert written["exit_code"] == 0
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "| 2 | check-2 | 03 | **pending** |" in summary


@pytest.mark.parametrize(
    ("changes", "failure"),
    [
        ({"behaviours": [check(1, "failed")]}, "check 1"),
        ({"aborted": "a cap refused POST /memories"}, "behaviours aborted"),
        ({"bank_deleted": False}, "was not deleted"),
        ({"known_answers_error": "invalid file"}, "known answers"),
    ],
)
def test_a_failure_fails_the_run(changes: dict[str, Any], failure: str) -> None:
    report = ConformanceReport.model_validate(
        {
            "mode": "live",
            "strict": False,
            "behaviours": [check(1, "passed")],
            "bank_id": "atlas-conformance-1",
            "bank_deleted": True,
        }
        | changes
    )

    assert report.exit_code() == 1
    assert any(failure in each for each in report.failures())
