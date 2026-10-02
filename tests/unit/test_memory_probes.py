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
from pathlib import Path
from typing import Any

import pytest

from atlas.companies import load_universe
from atlas.research import RecallResponse
from atlas.research.probes import (
    ProbeConfigError,
    load_probes,
    measure,
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
    assert [(c.name, c.pointers, c.score) for c in total.ranking] == [
        ("lumentum", 6, 5.0),
        ("coherent", 4, 1.0667),
    ]
    text = summary(reported)
    assert "| laser-chips | question 0 | 7 | 5 | 5 | 2 | 29% | 2 |" in text
    assert "| inp-substrates | question 0 | failed: HTTP 502: hindsight_unavailable" in text
    assert "1. lumentum: 5.0 (6 pointers, best rank 1)" in text
