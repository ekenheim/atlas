"""The early-call scorecard's reader and reporter (atlas-beliefs ticket 29a).

`scripts/scorecard.py`.

Seam: the script's functions and its `main`, loaded from the file, over recorded answers of
Atlas's API that were written by hand (`tests/fixtures/scorecard/api.json`, a path -> answer map
for the GETs the reader makes; the companies, documents and sentences are invented, shaped like
Atlas's answers). Nothing is called: the reader takes its `get` as an argument.

The fixtures hold seven runs: SanDisk as of 28 February (hit) and 31 May (the reviewers disagree,
the lead adjudicates a miss), IREN as of 31 March and 31 May (two misses), Snap (a false
positive), eToro (clean) and AXT (calibration); Raspberry Pi is reported not run.
"""

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.harness import REPO

FIXTURES = REPO / "tests" / "fixtures" / "scorecard"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("scorecard", REPO / "scripts" / "scorecard.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["scorecard"] = module  # its dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


sc = load()
API: dict[str, Any] = json.loads((FIXTURES / "api.json").read_text(encoding="utf-8"))
RUNS: dict[str, Any] = json.loads((FIXTURES / "runs.json").read_text(encoding="utf-8"))
MARKS: dict[str, Any] = json.loads((FIXTURES / "marks.json").read_text(encoding="utf-8"))


def get(path: str, **params: Any) -> Any:
    """A recorded GET: the answer for the path; a list route's page past its end is empty."""
    answer: dict[str, Any] | list[Any] = copy.deepcopy(API[path])
    if isinstance(answer, dict) and "items" in answer and params.get("offset", 0):
        answer["items"] = []
    return answer


def bundles(runs: Any) -> dict[str, dict[str, Any]]:
    return {run.label: sc.collect_bundle(get, run) for run in runs.runs}


def report(runs_file: dict[str, Any] = RUNS, marks_file: dict[str, Any] = MARKS) -> dict[str, Any]:
    runs = sc.parse_runs(runs_file)
    return sc.build_report(runs, bundles(runs), marks_file["marks"], marks_file["adjudications"])


def row(result: dict[str, Any], label: str) -> dict[str, Any]:
    return next(each for each in result["runs"] if each["run"] == label)


# --- the key -------------------------------------------------------------------------------------


def test_the_key_is_the_one_fixed_on_the_eighteenth_of_october() -> None:
    # Written out by hand from the ticket's table, never read back from the module.
    expected = {
        "sandisk": ("positive", ["2025-02-28", "2025-05-31", "2025-08-31"], "2025-09-10"),
        "iren": ("positive", ["2025-03-31", "2025-05-31"], "2025-08-28"),
        "axt": ("calibration", ["2025-08-31"], "2025-10-30"),
        "etoro": ("negative", ["2025-09-30"], None),
        "snap": ("negative", ["2025-08-31"], None),
        "poet": ("negative", ["2025-11-30"], None),
        "raspberry-pi": ("squeezed_buyer", ["2025-10-31"], "2026-03-31"),
    }
    assert {
        case.id: (case.kind, list(case.as_of_dates), case.priced) for case in sc.KEY.values()
    } == expected
    assert [case.id for case in sc.KEY.values() if not case.scored] == ["axt"]
    assert sc.KEY["sandisk"].slug == "sandisk" and sc.KEY["raspberry-pi"].slug is None
    assert "utilisation cut while profitable" in sc.KEY["sandisk"].hit_text
    assert "Grid power" in sc.KEY["iren"].hit_text
    assert sc.KEY["sandisk"].in_sample and sc.KEY["axt"].in_sample
    assert not any(sc.KEY[each].in_sample for each in ("iren", "etoro", "snap", "poet"))
    # Thirteen runs in all (3 + 2 + 1 + 1 + 1 + 1 + 1 = 10 as-of dates).
    assert sum(len(case.as_of_dates) for case in sc.KEY.values()) == 10


# --- the runs file -------------------------------------------------------------------------------


def test_the_runs_file_is_checked_against_the_key() -> None:
    runs = sc.parse_runs(RUNS)
    assert [run.label for run in runs.runs] == [
        "sandisk@2025-02-28",
        "sandisk@2025-05-31",
        "iren@2025-03-31",
        "iren@2025-05-31",
        "snap@2025-08-31",
        "etoro@2025-09-30",
        "axt@2025-08-31",
    ]
    assert runs.not_run == {"raspberry-pi": "LSE, not an SEC filer: no documents reachable"}
    iren = runs.runs[2]
    assert (iren.code_read, iren.code_rank, iren.code_pooled_percentile) == (True, None, 0.41)
    assert runs.runs[5].code_read is False  # eToro's code reading is not in the file yet


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"case": "tesla"}, "no such case"),
        ({"as_of": "2025-06-30"}, "is run as of"),
        ({"session_id": ""}, "session_id is missing"),
        ({"closed_book": "maybe"}, "closed_book is one of"),
        ({"code_rank": 0}, "code_rank is a rank"),
        ({"fact_precision": "high"}, "must be a number"),
    ],
)
def test_a_run_that_does_not_fit_the_key_is_refused(change: dict[str, Any], message: str) -> None:
    document = copy.deepcopy(RUNS)
    document["runs"][0].update(change)

    with pytest.raises(sc.ScorecardError, match=message):
        sc.parse_runs(document)


def test_a_run_listed_twice_or_a_not_run_without_a_reason_is_refused() -> None:
    twice = copy.deepcopy(RUNS)
    twice["runs"].append(copy.deepcopy(twice["runs"][0]))
    with pytest.raises(sc.ScorecardError, match="listed twice"):
        sc.parse_runs(twice)
    silent = copy.deepcopy(RUNS)
    silent["not_run"] = [{"case": "raspberry-pi", "reason": " "}]
    with pytest.raises(sc.ScorecardError, match="needs a reason"):
        sc.parse_runs(silent)


def test_every_case_at_every_date_is_run_reported_not_run_or_missing() -> None:
    rows = {each["run"]: each for each in sc.coverage(sc.parse_runs(RUNS))}

    assert len(rows) == 10
    assert rows["sandisk@2025-02-28"]["status"] == "run"
    assert rows["sandisk@2025-08-31"]["status"] == "missing"  # no one dropped it silently
    assert rows["poet@2025-11-30"]["status"] == "missing"
    assert rows["raspberry-pi@2025-10-31"] == {
        "run": "raspberry-pi@2025-10-31",
        "status": "not run",
        "reason": "LSE, not an SEC filer: no documents reachable",
    }


# --- reading a run -------------------------------------------------------------------------------


def test_a_run_is_read_as_the_session_its_own_beliefs_its_trace_and_its_documents() -> None:
    run = sc.parse_runs(RUNS).runs[0]

    bundle = sc.collect_bundle(get, run)

    assert bundle["run"] == "sandisk@2025-02-28"
    assert bundle["session"]["isolated"] is True
    # Its two Beliefs; the other session's Belief of the same theme is not read.
    assert [b["statement"][:12] for b in bundle["beliefs"]] == ["Zephyr cut w", "Zephyr repor"]
    assert all(b["produced_by"] == run.session_id for b in bundle["beliefs"])
    assert [c["tool"] for c in bundle["tool_calls"]][:3] == ["open_session", "prior_work", "search"]
    # A cited document's date comes with its citation; the 10-Q only a Fact quotes is asked for.
    assert bundle["version_dates"] == {
        "00000003-0000-4000-8000-000000000001": "2025-01-30T21:05:00Z",
        "00000003-0000-4000-8000-000000000002": "2025-02-12T21:30:00Z",
    }


def test_the_trace_summary_counts_calls_refusals_searches_documents_and_facts_by_month() -> None:
    run = sc.parse_runs(RUNS).runs[0]

    summary = sc.trace_summary(sc.collect_bundle(get, run))

    assert summary["calls"] == 9
    assert summary["by_tool"]["search"] == 2 and summary["by_tool"]["read"] == 2
    assert summary["by_outcome"] == {"ok": 8, "refused": 1}
    assert summary["refusals"] == {"isolated_session": 1}
    assert summary["searches"] == ["sandisk: wafer starts supply", "sandisk: price increase"]
    assert summary["documents_read"] == 2
    assert summary["facts"] == 3
    assert summary["facts_by_document_month"] == {"2025-01": 2, "2025-02": 1}


# --- the review sheet ----------------------------------------------------------------------------


def test_a_review_sheet_has_the_key_and_the_beliefs_and_no_price_probe_or_rank() -> None:
    runs = sc.parse_runs(RUNS)
    run = runs.runs[0]

    sheet = sc.review_sheet(run, sc.collect_bundle(get, run))

    assert sheet.startswith("# Review sheet: SanDisk (NAND), as of 2025-02-28")
    assert "`sandisk@2025-02-28`" in sheet
    assert (
        "As of 2025-02-28, does anything constrain supply in SanDisk's market, who holds it,"
        " and what would relieve it?" in sheet
    )
    assert "NAND undersupply that the suppliers chose (utilisation cut while profitable)" in sheet
    # Each Belief with its citation: the statement, the quote, the document and the day public.
    assert "Zephyr cut wafer starts to keep supply in balance while profitable." in sheet
    assert '"we reduced wafer starts in the quarter to keep supply in balance"' in sheet
    assert "Zephyr Flash Q2 FY25 results release, public 2025-01-30" in sheet
    assert sheet.count("- Mark: ____") == 2
    assert "Isolated session: yes" in sheet
    assert "Atlas refused or failed: isolated_session 1" in sheet
    assert "Facts by the month their documents became public: 2025-01 2, 2025-02 1" in sheet
    # Nothing a blind reviewer must not see: the priced date, the closed-book verdict, the rank.
    lowered = sheet.lower()
    for hidden in ("2025-09-10", "priced", "closed", "code rank", "hedged", "pooled", "0.95"):
        assert hidden not in lowered, hidden


def test_a_negative_s_sheet_says_what_the_key_expects_and_a_run_without_beliefs_says_so() -> None:
    runs = sc.parse_runs(RUNS)
    snap = next(run for run in runs.runs if run.case == "snap")
    iren = next(run for run in runs.runs if run.label == "iren@2025-05-31")

    sheet = sc.review_sheet(snap, sc.collect_bundle(get, snap))
    empty = sc.review_sheet(iren, sc.collect_bundle(get, iren))

    assert "No bottleneck: ad inventory outgrows demand, prices falling" in sheet
    assert "Case kind: negative" in sheet
    assert "The session proposed no Belief" in empty
    assert "Mark: ____" not in empty


# --- the marks and the report --------------------------------------------------------------------


def test_the_outcome_of_each_run_follows_the_reviewers_and_the_lead() -> None:
    result = report()

    assert {each["run"]: each["raw"] for each in result["runs"]} == {
        "sandisk@2025-02-28": "hit",
        "sandisk@2025-05-31": "miss",  # A said hit, B said miss: the lead's mark stands
        "iren@2025-03-31": "miss",
        "iren@2025-05-31": "miss",  # no Belief at all
        "snap@2025-08-31": "false_positive",
        "etoro@2025-09-30": "clean",
        "axt@2025-08-31": "calibration",
    }
    assert result["positive_hits"] == "1 of 4"
    assert result["negative_false_positives"] == "1 of 2"
    assert result["misses_by_class"] == {"M3": 1, "M4": 2}


def test_the_report_keeps_the_raw_hit_the_closed_book_verdict_and_the_code_rank_apart() -> None:
    result = report()

    feb = row(result, "sandisk@2025-02-28")
    assert (feb["raw"], feb["closed_book"], feb["code_rank"]) == ("hit", "hedged", 3)
    assert feb["code_rank_in_sample"] is True
    may = row(result, "sandisk@2025-05-31")
    assert "not discriminating: the closed-book model states it" in may["flags"]
    iren = row(result, "iren@2025-03-31")
    assert (iren["code_read"], iren["code_rank"], iren["code_rank_in_sample"]) == (
        True,
        None,
        False,
    )
    assert iren["code_pooled_percentile"] == 0.41
    etoro = row(result, "etoro@2025-09-30")
    assert (etoro["code_read"], etoro["closed_book"]) == (False, None)
    assert not any("score" in key for key in feb), "no composite score"
    assert (feb["session_id"], feb["tool_calls"]) == ("00000001-0000-4000-8000-000000000001", 9)


def test_the_guardrails_flag_a_run_below_them() -> None:
    result = report()

    assert row(result, "sandisk@2025-02-28")["flags"] == []  # 95% and 4%: inside both
    assert "Fact precision 88% is below 92%" in row(result, "iren@2025-05-31")["flags"]
    assert "trust gate 20% is above 10%" in row(result, "snap@2025-08-31")["flags"]


def test_the_lead_time_runs_from_the_earliest_hit_to_the_priced_date() -> None:
    cases = report()["cases"]

    # 28 February to 10 September 2025.
    assert cases["sandisk"]["lead"] == {
        "earliest_hit_as_of": "2025-02-28",
        "priced": "2025-09-10",
        "days": 194,
    }
    assert cases["sandisk"]["hits"] == 1
    assert cases["iren"]["lead"] is None and cases["iren"]["hits"] == 0
    assert cases["snap"]["false_positives"] == 1
    assert cases["etoro"]["lead"] is None


def test_the_rule_builds_the_class_two_positive_cases_share() -> None:
    decision = report()["decision"]

    # M4 on SanDisk (31 May) and on IREN (31 March); M3 and AXT's M2 are one run each.
    assert decision["build"] == "M4"
    assert decision["reason"] == "M4 on 2 positive cases (iren, sandisk)"
    assert decision["runs_by_class"] == {"M2": 1, "M3": 1, "M4": 2}


def outcome(case: str, miss_class: str | None, kind: str = "miss") -> Any:
    return sc.RunOutcome(
        run=f"{case}@x",
        case=case,
        outcome=kind,
        belief_marks={},
        unresolved=(),
        miss_class=miss_class,
        reason=None,
        not_scored=None,
    )


def test_the_rule_without_a_shared_class_takes_the_most_frequent_and_ties_go_to_intake() -> None:
    # No class on two cases: IREN twice M3, SanDisk M2 -> the most frequent, M3.
    most = sc.decide_build([outcome("iren", "M3"), outcome("iren", "M3"), outcome("sandisk", "M2")])
    assert most["build"] == "M3" and "most frequent" in most["reason"]
    # A tie between M1 and M5 goes to M1; one between M3 and M4 to the lower number.
    tie = sc.decide_build([outcome("iren", "M1"), outcome("sandisk", "M5")])
    assert tie["build"] == "M1" and "a tie of M1, M5 going to M1" in tie["reason"]
    lower = sc.decide_build([outcome("iren", "M4"), outcome("sandisk", "M3")])
    assert lower["build"] == "M3"
    # AXT counts in the fallback count, but is no positive case for the shared-class trigger.
    axt = sc.decide_build([outcome("sandisk", "M2"), outcome("axt", "M2", "calibration")])
    assert axt["build"] == "M2" and "shared" not in axt["reason"]
    assert "positive cases" not in axt["reason"]


def test_one_miss_alone_triggers_nothing_and_no_miss_builds_nothing() -> None:
    assert sc.decide_build([outcome("iren", "M3")]) == {
        "runs_by_class": {"M3": 1},
        "build": None,
        "reason": "one miss alone triggers nothing",
    }
    assert sc.decide_build([])["build"] is None
    # A false positive is a negative's, not a miss to build for; an unclassified miss is no class.
    assert (
        sc.decide_build([outcome("snap", "FP", "false_positive"), outcome("iren", None)])["build"]
        is None
    )


def test_a_run_on_another_configuration_or_not_isolated_is_flagged_and_not_scored() -> None:
    changed = copy.deepcopy(RUNS)
    changed["runs"][0]["configuration"]["agent_model"] = "opus"  # the alias, not the exact ID
    del changed["runs"][1]["configuration"]["judge"]  # a frozen key the run does not record

    result = report(changed)

    feb = row(result, "sandisk@2025-02-28")
    assert feb["raw"] is None
    assert "not scored: another configuration than the frozen one: agent_model" in feb["flags"]
    assert row(result, "sandisk@2025-05-31")["raw"] is None
    # Excluded from the totals and the lead time: SanDisk has no scored hit now.
    assert result["positive_hits"] == "0 of 2"
    assert result["cases"]["sandisk"]["lead"] is None

    loose = copy.deepcopy(API)
    loose[f"/sessions/{RUNS['runs'][4]['session_id']}"]["isolated"] = False
    runs = sc.parse_runs(RUNS)
    snap = next(run for run in runs.runs if run.case == "snap")
    marks = [m for m in MARKS["marks"] if m["run"] == snap.label]

    def get_loose(path: str, **params: Any) -> Any:
        answer = loose[path]
        return copy.deepcopy(answer) if not params.get("offset") else {**answer, "items": []}

    bundle = sc.collect_bundle(get_loose, snap)
    resolved = sc.resolve_run(snap, runs, bundle, marks, None)
    assert resolved.not_scored == "the session was not isolated"


def test_reviewers_who_disagree_leave_the_run_unsettled_until_the_lead_adjudicates() -> None:
    marks = copy.deepcopy(MARKS)
    marks["adjudications"] = [a for a in marks["adjudications"] if a["run"] != "sandisk@2025-05-31"]

    result = report(marks_file=marks)

    unsettled = row(result, "sandisk@2025-05-31")
    assert unsettled["raw"] is None
    assert "1 Belief(s) await the lead's adjudication" in unsettled["flags"]
    # The positive totals leave an unsettled run out of both numbers' hits, not out of the count.
    assert result["positive_hits"] == "1 of 4"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"mark": "maybe"}, "is one of hit, miss, false_positive"),
        ({"belief_id": "00000002-0000-4000-8000-000000000008"}, "is not the session's"),
    ],
)
def test_a_mark_that_does_not_fit_is_refused(change: dict[str, Any], message: str) -> None:
    marks = copy.deepcopy(MARKS)
    marks["marks"][0].update(change)

    with pytest.raises(sc.ScorecardError, match=message):
        report(marks_file=marks)


def test_a_hit_on_a_negative_or_a_false_positive_on_a_positive_is_refused() -> None:
    hit_on_negative = copy.deepcopy(MARKS)
    for mark in hit_on_negative["marks"]:
        if mark["run"] == "etoro@2025-09-30":
            mark["mark"] = "hit"
    with pytest.raises(sc.ScorecardError, match="a negative case has no hit"):
        report(marks_file=hit_on_negative)
    fp_on_positive = copy.deepcopy(MARKS)
    for mark in fp_on_positive["marks"]:
        if mark["run"] == "sandisk@2025-02-28":
            mark["mark"] = "false_positive"
    with pytest.raises(sc.ScorecardError, match="only a negative has a false positive"):
        report(marks_file=fp_on_positive)


def test_the_rendered_report_says_seven_cases_are_no_hit_rate_and_lists_what_was_not_run() -> None:
    text = sc.render_report(report())

    assert "Seven cases are no hit rate" in text
    assert "| sandisk@2025-02-28 |" in text
    assert "3 (in-sample)" in text  # SanDisk's rank, apart from the clean cases'
    assert "not in top 20" in text  # IREN's: the code's reading is in the file, rank null
    assert "17" in text and "17 (in-sample)" not in text
    assert "- Hits of the positive runs: 1 of 4" in text
    assert "- False positives of the negative runs: 1 of 2" in text
    assert "SanDisk (NAND): 194 days (hit as of 2025-02-28, priced 2025-09-10)" in text
    assert "IREN (grid power): no hit" in text
    assert (
        "raspberry-pi@2025-10-31: not run (LSE, not an SEC filer: no documents reachable)" in text
    )
    assert "sandisk@2025-08-31: missing" in text
    assert "The pre-registered rule chooses: **M4**" in text


def test_the_command_line_writes_the_sheets_and_the_report(tmp_path: Path) -> None:
    runs = sc.parse_runs(RUNS)
    bundle_dir = tmp_path / "bundles"
    bundle_dir.mkdir()
    for run in runs.runs:
        (bundle_dir / f"{run.label}.json").write_text(
            json.dumps(sc.collect_bundle(get, run)), encoding="utf-8"
        )
    runs_path, marks_path = tmp_path / "runs.json", tmp_path / "marks.json"
    runs_path.write_text(json.dumps(RUNS), encoding="utf-8")
    marks_path.write_text(json.dumps(MARKS), encoding="utf-8")

    status = sc.main(
        [
            "report",
            "--runs",
            str(runs_path),
            "--marks",
            str(marks_path),
            "--bundles",
            str(bundle_dir),
            "--out",
            str(tmp_path / "out"),
        ]
    )

    assert status == 0
    written = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert written["positive_hits"] == "1 of 4" and written["decision"]["build"] == "M4"
    assert "Seven cases are no hit rate" in (tmp_path / "out" / "report.md").read_text(
        encoding="utf-8"
    )


def test_a_bad_file_is_a_clean_error_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "runs.json"
    bad.write_text(json.dumps({"runs": [{"case": "tesla"}]}), encoding="utf-8")

    status = sc.main(
        ["report", "--runs", str(bad), "--marks", str(bad), "--bundles", str(tmp_path)]
    )

    assert status == 2
    assert "scorecard: run 0: no such case 'tesla'" in capsys.readouterr().err
