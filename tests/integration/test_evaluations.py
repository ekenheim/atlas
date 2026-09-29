"""`atlas evaluate`: the gold cases run through the pipeline and their results are stored and
served (ticket 25; docs/evaluation-methodology.md; spec user story 55).

Seams: the `atlas evaluate` CLI entry (a subprocess, as the owner and CI run it) and
`GET /api/v1/evaluations[/{id}]`. The cases run in fake mode, the one CI runs: the scripted
answers of `tests/evaluation/gold/` stand in for the model, and Hindsight and SearXNG are the
evaluator's localhost stubs, so this is the deterministic scoring of the pipeline's
deterministic parts. The live mode (the real model) is only checked to refuse without its two
locks; nothing live is called.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from atlas.api.app import create_app
from tests.harness import REPO, SITES, TEMPLATE, make_settings

GOLD = REPO / "tests" / "evaluation" / "gold"
CASES = [e["case_id"] for e in json.loads((GOLD / "manifest.json").read_text("utf-8"))["cases"]]
# The metric each category's checks feed (methodology §7).
METRICS = {
    "EV-SUP-001": {"relationship_recall", "citation_correctness"},
    "EV-COM-001": {"relationship_precision"},
    "EV-SYN-001": {"independent_families"},
    "EV-FUT-001": {"as_of_isolation", "contradiction_discovery"},
    "EV-RST-001": {"as_of_isolation"},
}


def evaluate(
    database_url: str, tmp_path: Path, *args: str, gold: Path = GOLD, **env: str
) -> subprocess.CompletedProcess[str]:
    archive = tmp_path / "archive"
    archive.mkdir(exist_ok=True)
    clean = {k: v for k, v in os.environ.items() if k in ("PATH", "ATLAS_LIVE_TESTS")}
    return subprocess.run(
        [sys.executable, "-m", "atlas", "evaluate", *args],
        cwd=REPO,
        env=clean
        | {
            "HOME": str(tmp_path),
            "ATLAS_DATABASE_URL": database_url,
            "ATLAS_ACTOR": "local-researcher",
            "ATLAS_ARCHIVE_ROOT": str(archive),
            "ATLAS_SOURCE_SITES_CONFIG": str(SITES),
            "ATLAS_HINDSIGHT_TEMPLATE_PATH": str(TEMPLATE),
            "ATLAS_EVALUATION_GOLD_DIR": str(gold),
        }
        | env,
        capture_output=True,
        text=True,
        timeout=600,
    )


@pytest.fixture
def api(database_url: str, tmp_path: Path) -> TestClient:
    return TestClient(create_app(make_settings(tmp_path, database_url=database_url)))


def get(api: TestClient, path: str, **params: Any) -> Any:
    response = api.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_every_gold_case_passes_in_fake_mode_and_the_run_is_stored_and_served(
    database_url: str, tmp_path: Path, api: TestClient
) -> None:
    ran = evaluate(database_url, tmp_path)

    assert ran.returncode == 0, ran.stderr
    summary = json.loads(ran.stdout)
    assert summary["mode"] == "fake"
    assert (summary["cases_total"], summary["cases_passed"]) == (len(CASES), len(CASES))
    assert [c["case_id"] for c in summary["cases"]] == CASES
    for case_id in CASES:
        assert f"{case_id} pass (" in ran.stderr

    runs = get(api, "/api/v1/evaluations")
    [listed] = runs["items"]
    assert listed["id"] == summary["evaluation_run_id"]
    assert (listed["mode"], listed["status"], listed["model"]) == (
        "fake",
        "completed",
        "evaluation/scripted",
    )
    assert (listed["cases_total"], listed["cases_passed"]) == (len(CASES), len(CASES))
    assert listed["case_ids"] == CASES
    manifest = (GOLD / "manifest.json").read_bytes()
    assert listed["gold_manifest_sha256"] == hashlib.sha256(manifest).hexdigest()

    run = get(api, f"/api/v1/evaluations/{listed['id']}")
    results = {r["case_id"]: r for r in run["results"]}
    assert sorted(results) == sorted(CASES)
    for case_id, result in results.items():
        raw = (GOLD / "cases" / f"{case_id}.json").read_bytes()
        assert result["case_sha256"] == hashlib.sha256(raw).hexdigest()
        assert result["passed"] is True, (case_id, result["error"], result["checks"])
        assert result["error"] is None
        assert result["checks"] and all(check["passed"] for check in result["checks"])
        assert set(result["scores"].values()) == {1.0}
    for case_id, metrics in METRICS.items():
        assert set(results[case_id]["scores"]) == metrics
    assert run["categories"]["SUP"] == {"passed": 2, "total": 2}
    assert set(run["categories"]) == {r["category"] for r in results.values()}

    # What Atlas concluded, in the case's terms: the traps are caught for the right reason.
    com = results["EV-COM-001"]["predicted"]
    assert [(c["outcome"], c["reason_code"]) for c in com["claims"]] == [
        ("rejected", "no_directional_language")
    ]
    assert com["relationships"] == []
    edges = {
        (e["subject"], e["object"], e["layer"]): e
        for e in results["EV-DIR-001"]["predicted"]["relationships"]
    }
    assert edges[("aurora", "cirrus", "module")]["review_state"] == "machine_reviewed"
    reversed_edge = edges[("cirrus", "aurora", "module")]
    assert reversed_edge["review_state"] == "needs_human_review"
    assert "direction_not_confirmed" in reversed_edge["reasons"]
    [hedged] = results["EV-HED-001"]["predicted"]["relationships"]
    assert (hedged["review_state"], hedged["reasons"]) == (
        "needs_human_review",
        ["hedged_language"],
    )
    future = results["EV-FUT-001"]["predicted"]["investigation"]
    assert (future["documents"], future["stop_reason"]) == (["s1"], "no_new_independent_evidence")
    skeptic = results["EV-CON-001"]["predicted"]["investigation"]
    assert skeptic["stop_reason"] == "needs_review"
    assert skeptic["contradictions"] == [{"independent": True, "source": "s2"}]
    families = results["EV-SYN-001"]["predicted"]["families"]
    assert len({families[f"s{i}"] for i in range(11)}) == 1
    assert families["s11"] != families["s0"]
    restated = results["EV-RST-001"]["predicted"]["financials"]
    assert [(f["value"], f["linkage"]) for f in restated] == [
        ("22258000000", "first"),
        ("21138000000", "restates"),
    ]

    # Each case ran in its own database, dropped afterwards; the results stay in Atlas's.
    engine = create_engine(database_url)
    with engine.connect() as connection:
        left = connection.execute(
            text("SELECT count(*) FROM pg_database WHERE datname LIKE 'atlas_eval_%'")
        ).scalar_one()
        assert connection.execute(text("SELECT count(*) FROM company")).scalar_one() == 0
    engine.dispose()
    assert left == 0


def test_a_case_whose_gold_atlas_does_not_meet_fails_with_what_was_observed(
    database_url: str, tmp_path: Path, api: TestClient
) -> None:
    # A copy of the gold set in which EV-COM-001 wrongly expects the co-mention to be an edge.
    gold = tmp_path / "gold"
    shutil.copytree(GOLD, gold)
    path = gold / "cases" / "EV-COM-001.json"
    case = json.loads(path.read_text("utf-8"))
    case["gold"]["relationships"][0]["expect"] = "present"
    raw = (json.dumps(case, indent=2) + "\n").encode()
    path.write_bytes(raw)
    index = json.loads((gold / "manifest.json").read_text("utf-8"))
    for entry in index["cases"]:
        if entry["case_id"] == "EV-COM-001":
            entry["case_sha256"] = hashlib.sha256(raw).hexdigest()
    (gold / "manifest.json").write_text(json.dumps(index), "utf-8")

    ran = evaluate(
        database_url, tmp_path, "--case", "EV-COM-001", "--case", "EV-SUP-001", gold=gold
    )

    assert ran.returncode == 1, ran.stderr
    assert "EV-COM-001 FAIL (relationship_precision 1.00, relationship_recall 0.00)" in ran.stderr
    assert "EV-SUP-001 pass" in ran.stderr
    summary = json.loads(ran.stdout)
    assert (summary["cases_total"], summary["cases_passed"]) == (2, 1)
    run = get(api, f"/api/v1/evaluations/{summary['evaluation_run_id']}")
    assert run["case_ids"] == ["EV-COM-001", "EV-SUP-001"]
    assert (run["cases_total"], run["cases_passed"]) == (2, 1)
    failed = next(r for r in run["results"] if r["case_id"] == "EV-COM-001")
    assert failed["passed"] is False
    assert failed["case_sha256"] == hashlib.sha256(raw).hexdigest()
    assert failed["scores"] == {"relationship_precision": 1.0, "relationship_recall": 0.0}
    [check] = [c for c in failed["checks"] if not c["passed"]]
    assert check["key"] == "relationships[0]"
    assert check["expected"]["expect"] == "present"
    assert check["observed"] == {"edges": []}


def test_a_live_evaluation_needs_both_locks_and_the_model(
    database_url: str, tmp_path: Path, api: TestClient
) -> None:
    without_opt_in = evaluate(database_url, tmp_path, "--live", ATLAS_LIVE_TESTS="")
    assert without_opt_in.returncode == 2
    assert "set ATLAS_LIVE_TESTS=1 as well as --live" in without_opt_in.stderr

    without_model = evaluate(database_url, tmp_path, "--live", ATLAS_LIVE_TESTS="1")
    assert without_model.returncode == 2
    assert "set ATLAS_LITELLM_URL and ATLAS_LITELLM_API_KEY" in without_model.stderr

    unknown = evaluate(database_url, tmp_path, "--case", "EV-SUP-404")
    assert unknown.returncode == 2
    assert "no such case in the gold set: EV-SUP-404" in unknown.stderr

    assert get(api, "/api/v1/evaluations")["items"] == []
    missing = api.get(f"/api/v1/evaluations/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_stored_results_are_insert_only(database_url: str, tmp_path: Path) -> None:
    ran = evaluate(database_url, tmp_path, "--case", "EV-SYN-001")
    assert ran.returncode == 0, ran.stderr

    engine = create_engine(database_url)
    for statement in ("UPDATE evaluation SET passed = false", "DELETE FROM evaluation"):
        with pytest.raises(DBAPIError, match="evaluation rows are insert-only"):
            with engine.begin() as connection:
                connection.execute(text(statement))
    engine.dispose()
