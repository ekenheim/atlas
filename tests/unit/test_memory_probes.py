"""The memory probe set (memory-quality ticket 02): the probe file is validated at load, and
the report of a recall answer counts what the reading index returned.

The recall answer (`tests/fixtures/memory-probe/recall-answer.json`) is hand-written in the
shape of `POST /api/v1/memory/recall`'s response (checked against `RecallResponse` below),
not recorded from production: seven memories, of which an observation and a world fact share
a text (whitespace aside), two facts differ only in case, one is unverified, one is broken,
and one resolves to a section with no company. Expected values are counted by hand from it.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from atlas.companies import load_universe
from atlas.research import RecallResponse
from atlas.research.probes import (
    ProbeConfigError,
    balance,
    balance_summary,
    load_probes,
    measure,
    pointed_versions,
    report,
    summary,
)
from tests.harness import REPO, THEMES

PROBES = REPO / "configs" / "memory" / "probes.yaml"
PILOT_PLAN = REPO / ".scratch" / "pilot" / "pilot-plan.md"
ANSWER = REPO / "tests" / "fixtures" / "memory-probe" / "recall-answer.json"
LUMENTUM = "c1b77861-cb62-5c38-a26b-200add1a7b04"
COHERENT = "cbe30797-ec30-53f2-8015-7acad1f4c9c7"
NAMES = {LUMENTUM: "lumentum", COHERENT: "coherent"}


def answer() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(ANSWER.read_text(encoding="utf-8"))
    RecallResponse.model_validate(loaded)  # the shape the API returns
    return loaded


# --- the probe file ---


def test_the_probe_file_holds_the_five_pilot_questions_verbatim_with_four_queries_each() -> None:
    probes = load_probes(PROBES, load_universe(THEMES))

    plan = PILOT_PLAN.read_text("utf-8")
    table = re.findall(r"^\| (\d) \| (.+?) \| .+? \| .+? \|\r?$", plan, re.M)
    assert [probe.question for probe in probes.probes] == [question for _, question in table]
    assert len(probes.probes) == 5
    assert all(len(probe.queries) == 4 for probe in probes.probes)
    assert all(probe.scope.theme_ids == ("photonics",) for probe in probes.probes)
    recalls = probes.recalls()
    assert len(recalls) == 25
    assert [(r.kind, r.index) for r in recalls[:5]] == [
        ("question", 0),
        ("query", 1),
        ("query", 2),
        ("query", 3),
        ("query", 4),
    ]
    assert recalls[0].theme_ids == ["photonics"]


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "probes.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_probe_without_a_scope_is_refused(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "version: 1\nprobes:\n  - id: a\n    question: Q?\n    queries: [q]\n",
    )

    with pytest.raises(ProbeConfigError, match="scope"):
        load_probes(path, load_universe(THEMES))


def test_a_probe_with_an_empty_scope_is_refused(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "version: 1\nprobes:\n  - id: a\n    question: Q?\n    scope: {theme_ids: []}\n"
        "    queries: [q]\n",
    )

    with pytest.raises(ProbeConfigError, match="theme_ids"):
        load_probes(path, load_universe(THEMES))


def test_a_probe_with_an_unknown_theme_is_refused(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "version: 1\nprobes:\n  - id: a\n    question: Q?\n    scope: {theme_ids: [optics]}\n"
        "    queries: [q]\n",
    )

    with pytest.raises(ProbeConfigError, match="unknown theme optics"):
        load_probes(path, load_universe(THEMES))


# --- the report ---


def test_the_measures_of_one_recall_answer() -> None:
    measured = measure([answer()], NAMES)

    assert measured.memories == 7
    assert measured.resolved == 5
    # A and B's Item 1 (Lumentum), C's Item 1A and D's cover (Coherent), E's chunk-001.
    assert measured.sections == 5
    assert measured.companies == 2  # the section with no company names nobody
    assert measured.observations == 2
    assert measured.observation_share == 0.2857
    # The fact under the observation (rank 2), and Coherent's fact in other case (rank 5).
    assert measured.repeats == 2
    # The first observation was built from the fact returned at rank 2.
    assert measured.superseded == 1
    lumentum, coherent = measured.ranking
    # Lumentum: rank 1 (two sections) and rank 2: 1 + 1 + 1/2.
    assert (lumentum.company_id, lumentum.name) == (LUMENTUM, "lumentum")
    assert (lumentum.pointers, lumentum.score, lumentum.best_rank) == (3, 2.5, 1)
    # Coherent: ranks 3 and 5: 1/3 + 1/5.
    assert (coherent.company_id, coherent.name) == (COHERENT, "coherent")
    assert (coherent.pointers, coherent.score, coherent.best_rank) == (2, 0.5333, 3)


def test_the_report_totals_count_sections_once_and_add_up_pointers() -> None:
    probes = load_probes(PROBES, load_universe(THEMES)).recalls()
    question, query, other = probes[0], probes[1], probes[5]

    reported = report(
        [(question, answer()), (query, answer()), (other, "HTTP 502: hindsight_unavailable")],
        NAMES,
    )

    assert [row.error for row in reported.results] == [
        None,
        None,
        "HTTP 502: hindsight_unavailable",
    ]
    assert list(reported.by_probe) == ["laser-chips"]
    total = reported.total
    assert (total.memories, total.resolved, total.sections, total.companies) == (14, 10, 5, 2)
    assert total.repeats == 4  # repeats are counted within one answer
    assert total.superseded == 2
    assert [(c.name, c.pointers, c.score) for c in total.ranking] == [
        ("lumentum", 6, 5.0),
        ("coherent", 4, 1.0667),
    ]
    text = summary(reported)
    assert "| laser-chips | question 0 | 7 | 5 | 5 | 2 | 29% | 2 |" in text
    assert "| inp-substrates | question 0 | failed: HTTP 502: hindsight_unavailable" in text
    assert "1. lumentum: 5.0 (6 pointers, best rank 1)" in text


# --- the bank's balance (pilot-review ticket 24) ---

AXT = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 10, 6, tzinfo=UTC)
AVAILABLE = {  # the window starts 2024-10-06 (730 days)
    "a9ec1d5d-9b72-533a-ab44-62e5e14caefd": datetime(2023, 3, 1, tzinfo=UTC),
    "f7100847-6eeb-5970-9c70-767162d75351": datetime(2025, 8, 1, tzinfo=UTC),
    "21b714b0-a0ef-5ee1-843e-c81909464f50": datetime(2023, 11, 1, tzinfo=UTC),
    "a947bff8-9349-551b-8b15-b7d00d33a19f": datetime(2026, 5, 1, tzinfo=UTC),
}
RESEARCHED = {**NAMES, AXT: "axt"}


def test_balance_lists_every_researched_company_with_weight_share_and_age() -> None:
    # By hand: Lumentum has three pointers (rank 1 twice: two versions; rank 2), weight 2.5;
    # Coherent two (ranks 3 and 5), 1/3 + 1/5; the section with no company is not counted.
    result = balance([answer()], RESEARCHED, AVAILABLE, now=NOW)

    rows = {row.name: row for row in result.companies}
    assert [row.name for row in result.companies] == ["lumentum", "coherent", "axt"]
    assert (rows["lumentum"].pointers, rows["lumentum"].score) == (3, 2.5)
    assert (rows["coherent"].pointers, rows["coherent"].score) == (2, 0.5333)
    assert (rows["axt"].pointers, rows["axt"].score, rows["axt"].share) == (0, 0.0, 0.0)
    assert result.total_score == 3.0333
    assert (rows["lumentum"].share, rows["coherent"].share) == (0.8242, 0.1758)
    # Before 2024-10-06: Lumentum's a9ec twice of three; Coherent's one of two.
    assert (rows["lumentum"].pre_window, rows["lumentum"].dated) == (2, 3)
    assert rows["lumentum"].pre_window_share == 0.6667
    assert rows["coherent"].pre_window_share == 0.5
    assert rows["axt"].pre_window_share is None
    assert (result.pre_window, result.dated, result.pre_window_share) == (3, 5, 0.6)
    assert result.zero_weight == ["axt"]
    assert result.over_pre_window == ["lumentum", "coherent"]


def test_balance_window_and_missing_dates() -> None:
    result = balance([answer()], RESEARCHED, {}, now=NOW)
    assert result.dated == 0
    assert result.over_pre_window == []
    wide = balance([answer()], RESEARCHED, AVAILABLE, now=NOW, window_days=3650)
    assert wide.pre_window == 0
    # Every resolved memory's version, the one with no company too.
    assert pointed_versions([answer()]) == sorted(
        [*AVAILABLE, "a38bd9cd-aa4d-567d-b49f-0058fe69c1ef"]
    )


def test_balance_counts_companies_outside_the_researched_set_apart() -> None:
    result = balance([answer()], {AXT: "axt"}, AVAILABLE, now=NOW)
    assert result.outside_universe_pointers == 5
    assert result.outside_universe_score == 3.0333
    assert result.total_score == 3.0333


def test_balance_summary_names_zero_weight_and_old_companies_first() -> None:
    text = balance_summary(balance([answer()], RESEARCHED, AVAILABLE, now=NOW))
    first = text.splitlines()[0]
    assert "companies at 0 weight: axt" in first
    assert "lumentum, coherent" in first
    assert "| axt | 0 | 0.0 | 0% | 0/0 | n/a |" in text
