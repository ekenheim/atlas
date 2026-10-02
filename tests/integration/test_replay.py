"""Replay banks (ticket 22; §9.2): the pipeline replayed at a cutoff in an isolated
`atlas-replay-<id>` bank, then the bank deleted.

Seam: `/api/v1/replay-jobs`, the `atlas` CLI (`sources import`) and single worker passes, on
a fresh database, against the recorded Hindsight fake served on localhost, which plays both
the research bank and the local replay Hindsight. The documents are the hand-written
synthetic fixtures in `tests/fixtures/replay/` (see its README): two published before the
cutoff, and a future-dated one published after it, which is retained into the research bank
first, so the replay has something to leak.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from tests.fakes.hindsight import BankFacts, RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import BANK, QUOTA_ERROR, REPO, Atlas

FIXTURES = REPO / "tests" / "fixtures" / "replay"
CUTOFF = "2025-12-31T23:59:59+00:00"
DOCUMENTS = {
    # name: (file, origin URL, published at)
    "early": (
        "early-capacity-update.html",
        "https://example.com/replay/early-capacity-update.html",
        "2025-03-03T09:00:00+00:00",
    ),
    "mid": (
        "mid-customer-update.html",
        "https://example.com/replay/mid-customer-update.html",
        "2025-06-02T09:00:00+00:00",
    ),
    "future": (
        "future-dated-supply-shock.html",
        "https://example.com/replay/future-dated-supply-shock.html",
        "2026-03-02T09:00:00+00:00",
    ),
}
EARLY_QUOTE = "running close to full utilization"
FUTURE_QUOTE = "indium phosphide wafer shortage of the future quarter"
QUESTIONS = 2  # the default question set's (configs/replay/question-sets.yaml)
PERMANENT_ERROR = "ValueError: document exceeds the extraction schema's maximum length"


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> Iterator[Atlas]:
    served = hindsight[1]
    harness = Atlas(
        database_url,
        tmp_path,
        served.url,
        replay_hindsight_url=served.url,
        replay_consolidation_timeout_seconds=0.05,
    )
    harness.apply_template()
    yield harness
    harness.engine.dispose()


def import_documents(atlas: Atlas, *names: str) -> dict[str, dict[str, Any]]:
    """Import the fixtures (and retain them into the research bank)."""
    imported: dict[str, dict[str, Any]] = {}
    for name in names:
        file, origin, published = DOCUMENTS[name]
        result = atlas.cli(
            "sources",
            "import",
            "--company",
            "lumentum",
            "--file",
            str(FIXTURES / file),
            "--origin-url",
            origin,
            "--published-at",
            published,
        )
        assert result.returncode == 0, result.stderr
        imported[name] = json.loads(result.stdout)
    atlas.worker_pass()
    return imported


def request_replay(atlas: Atlas, **body: Any) -> dict[str, Any]:
    response = atlas.api.post("/api/v1/replay-jobs", json={"cutoff": CUTOFF, **body})
    assert response.status_code == 202, response.text
    return response.json()


def version_ids(imported: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {name: result["source_version_id"] for name, result in imported.items()}


def test_a_future_dated_source_is_accepted_zero_times(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    imported = import_documents(atlas, "early", "mid", "future")
    ids = version_ids(imported)
    future_documents = [d for d in fake.bank_documents(BANK) if ids["future"] in d]
    assert future_documents  # the research bank holds the future-dated source
    future_fact = fake.derived_fact(future_documents[0], BANK)
    lumentum = atlas.company("lumentum")["id"]
    # Each reflect cites every fact the answering bank holds, and a research-bank memory of
    # the future-dated source; its text quotes both an earlier and the future-dated source.
    answer = f'Utilization: "{EARLY_QUOTE}". And: "{FUTURE_QUOTE}".'
    for _ in range(QUESTIONS):
        fake.script_reflect(answer, [BankFacts(), future_fact])

    requested = request_replay(atlas, company_ids=[lumentum])
    replay_bank = requested["bank_id"]
    atlas.worker_pass()
    replay = atlas.get(f"/api/v1/replay-jobs/{requested['id']}")

    # Requested: only what was available at the cutoff, in chronological order.
    assert replay_bank == f"atlas-replay-{requested['id']}"
    assert requested["status"] == "pending"
    assert requested["availability_convention"] == "available_at"
    assert requested["eligible_source_versions"] == 2
    assert [v["source_version_id"] for v in requested["source_versions"]] == [
        ids["early"],
        ids["mid"],
    ]
    # Finished, and the bank is gone.
    assert replay["status"] == "completed"
    assert replay["stage"] == "done"
    assert replay["bank_deleted_at"] is not None
    assert replay["error"] is None
    assert fake.deleted_banks == [replay_bank]
    assert fake.bank_documents(replay_bank) == []
    # Retained: the earlier sources only, one batch each, oldest first.
    batches = fake.retained(replay_bank)
    retained = [{item["metadata"]["source_version_id"] for item in b} for b in batches]
    assert retained == [{ids["early"]}, {ids["mid"]}]
    assert [v["retain_status"] for v in replay["source_versions"]] == ["completed"] * 2
    assert all(v["facts"] and v["sections"] for v in replay["source_versions"])
    assert replay["consolidation"]["status"] == "completed"
    # Recall: scoped like production research; nothing names the future-dated source.
    assert len(replay["answers"]) == QUESTIONS
    for recall in fake.requests("POST", "memories/recall"):
        assert recall["tags"] == [f"company:{lumentum}"]
        assert recall["tags_match"] == "any_strict"
    for answer_row in replay["answers"]:
        recalled = answer_row["recall"]
        assert {m["source_version_id"] for m in recalled} == {ids["early"], ids["mid"]}
        assert all(ids["future"] not in (m["document_id"] or "") for m in recalled)
        assert {m["provenance"]["state"] for m in recalled} == {"resolved"}
        # Citations: the earlier sources resolve; the research bank's memory of the future
        # source doesn't exist in the replay bank (broken), and its quote matches nothing.
        resolved = [c for c in answer_row["citations"] if c["state"] == "resolved"]
        cited = {s["source_version_id"] for c in resolved for s in c["sources"]}
        assert cited == {ids["early"], ids["mid"]}
        (future,) = [c for c in answer_row["citations"] if c["memory_id"] == future_fact]
        assert future["state"] == "broken"
        quotes = {c["text"]: c for c in answer_row["citations"] if c["kind"] == "quote"}
        assert quotes[EARLY_QUOTE]["state"] == "resolved"
        assert quotes[EARLY_QUOTE]["quote"]["source_version_id"] == ids["early"]
        assert quotes[FUTURE_QUOTE]["state"] == "unverified"
        assert ids["future"] not in {e["source_version_id"] for e in answer_row["evidence"]}
        assert answer_row["leakage"] == {
            "recall_memories": 0,
            "citations": 0,
            "source_version_ids": [],
        }
    assert replay["leakage"] == {
        "retained": 0,
        "recall_memories": 0,
        "citations": 0,
        "source_version_ids": [],
        "future_accepted": 0,
    }
    # The research bank and its ledger are untouched.
    assert future_documents[0] in fake.bank_documents(BANK)
    with atlas.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT count(*) FROM memory_document WHERE bank_id = :bank"),
            {"bank": replay_bank},
        ).scalar_one()
    assert rows == 0


def test_a_replay_bank_is_created_from_the_template_without_mental_models(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    import_documents(atlas, "early")
    fake.script_reflect("An answer.", [BankFacts()])
    fake.script_reflect("An answer.", [BankFacts()])

    requested = request_replay(atlas)
    atlas.worker_pass()
    replay = atlas.get(f"/api/v1/replay-jobs/{requested['id']}")

    imports = [
        json.loads(call.content)
        for call in fake.calls
        if call.method == "POST" and call.url.path.endswith(f"/{replay['bank_id']}/import")
    ]
    assert len(imports) == 2  # the dry run, then the import
    assert all("mental_models" not in body for body in imports)
    template = json.loads((REPO / "configs" / "hindsight" / "bank-template.json").read_text())
    assert replay["template_version"] == template["template_version"]
    # Without companies, the questions are scoped by every theme.
    assert replay["scope"]["tags"] == ["theme:photonics"]
    assert replay["status"] == "completed"


def test_a_failed_replay_still_deletes_its_bank(atlas: Atlas, fake: RecordedHindsight) -> None:
    ids = version_ids(import_documents(atlas, "early", "mid"))
    fake.hold_retains(
        "failed",
        where=lambda documents: any(ids["mid"] in d for d in documents),
        error_message=PERMANENT_ERROR,
    )

    requested = request_replay(atlas)
    atlas.worker_pass()
    replay = atlas.get(f"/api/v1/replay-jobs/{requested['id']}")

    assert replay["status"] == "failed"
    assert replay["final_status"] == "failed"
    assert PERMANENT_ERROR in replay["error"]
    assert [v["retain_status"] for v in replay["source_versions"]] == ["completed", "failed"]
    assert replay["answers"] == []
    assert replay["bank_deleted_at"] is not None
    assert fake.deleted_banks == [replay["bank_id"]]
    job = atlas.get(f"/api/v1/jobs/{replay['job_id']}")
    assert job["status"] == "succeeded"


def test_a_quota_failure_pauses_the_replay_and_keeps_its_bank(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    import_documents(atlas, "early")
    fake.hold_retains("failed", where=lambda _: True, error_message=QUOTA_ERROR, times=1)

    requested = request_replay(atlas)
    atlas.worker_pass()
    replay = atlas.get(f"/api/v1/replay-jobs/{requested['id']}")
    queue = atlas.get("/api/v1/queue")

    assert replay["status"] == "running"
    assert replay["stage"] == "retain"
    assert replay["bank_deleted_at"] is None
    assert fake.deleted_banks == []
    assert queue["pause"]["paused"] is True
    assert "replay" in queue["pause"]["kinds"]


def test_a_cancelled_replay_deletes_its_bank(atlas: Atlas, fake: RecordedHindsight) -> None:
    import_documents(atlas, "early")
    requested = request_replay(atlas)

    cancelled = atlas.api.post(f"/api/v1/replay-jobs/{requested['id']}/cancel")
    atlas.worker_pass()
    replay = atlas.get(f"/api/v1/replay-jobs/{requested['id']}")
    again = atlas.api.post(f"/api/v1/replay-jobs/{requested['id']}/cancel")

    assert cancelled.status_code == 202, cancelled.text
    assert cancelled.json()["cancel_requested_at"] is not None
    assert replay["status"] == "cancelled"
    assert replay["bank_deleted_at"] is not None
    assert fake.retained(replay["bank_id"]) == []
    assert fake.deleted_banks == [replay["bank_id"]]
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "replay_finished"


def test_consolidation_is_waited_for_within_a_bound(atlas: Atlas, fake: RecordedHindsight) -> None:
    import_documents(atlas, "early")
    fake.hold_consolidations("processing")
    fake.script_reflect("An answer.", [BankFacts()])
    fake.script_reflect("An answer.", [BankFacts()])

    requested = request_replay(atlas)
    atlas.worker_pass()
    replay = atlas.get(f"/api/v1/replay-jobs/{requested['id']}")

    assert replay["consolidation"]["status"] == "timed_out"
    assert replay["consolidation"]["polls"] == 5  # retain_poll_attempts
    assert replay["status"] == "completed"
    assert len(replay["answers"]) == QUESTIONS
    assert replay["bank_deleted_at"] is not None


def test_replay_operations_count_against_the_codex_budget(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    import_documents(atlas, "early", "mid")
    before = codex_used(atlas)
    fake.script_reflect("An answer.", [BankFacts()])
    fake.script_reflect("An answer.", [BankFacts()])

    request_replay(atlas)
    atlas.worker_pass()

    assert codex_used(atlas) == before + 3  # two retain batches and the consolidation


def codex_used(atlas: Atlas) -> int:
    budgets = atlas.get("/api/v1/queue")["budgets"]
    return next(b["used"] for b in budgets if b["provider"] == "codex")


def test_a_replays_retains_ask_for_the_configured_extractor_and_stay_on_the_codex_budget(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    atlas = Atlas(
        database_url,
        tmp_path,
        served.url,
        replay_hindsight_url=served.url,
        replay_consolidation_timeout_seconds=0.05,
        retain_extractor="minimax",
    )
    atlas.apply_template()
    import_documents(atlas, "early", "mid")
    assert codex_used(atlas) == 0  # the research bank's routed retains spend their own budget
    fake.script_reflect("An answer.", [BankFacts()])
    fake.script_reflect("An answer.", [BankFacts()])

    requested = request_replay(atlas)
    atlas.worker_pass()

    replay = atlas.get(f"/api/v1/replay-jobs/{requested['id']}")
    assert replay["status"] == "completed"
    # The replay bank's items carry the key like the research bank's (a Hindsight with no
    # such route ignores it).
    batches = fake.retained(requested["bank_id"])
    assert len(batches) == 2
    assert {item["metadata"]["extractor"] for batch in batches for item in batch} == {"minimax"}
    assert codex_used(atlas) == 3  # its two retain batches and the consolidation
    atlas.engine.dispose()


def test_a_replays_retains_send_the_same_observation_scopes_as_the_research_banks(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    import_documents(atlas, "early", "mid")
    fake.script_reflect("An answer.", [BankFacts()])
    fake.script_reflect("An answer.", [BankFacts()])

    requested = request_replay(atlas)
    atlas.worker_pass()

    research = [item for batch in fake.retained(BANK) for item in batch]
    replayed = [item for batch in fake.retained(requested["bank_id"]) for item in batch]
    assert research and replayed
    # Lumentum is in one theme: one scope, the theme's (memory-quality ticket 06).
    assert {json.dumps(item["observation_scopes"]) for item in research + replayed} == {
        json.dumps([["theme:photonics"]])
    }


def test_replays_are_listed_newest_first(atlas: Atlas) -> None:
    import_documents(atlas, "early")
    first = request_replay(atlas)
    second = request_replay(atlas)

    listed = atlas.get("/api/v1/replay-jobs")

    assert listed["total"] == 2
    assert [r["id"] for r in listed["items"]] == [second["id"], first["id"]]
    assert listed["items"][0]["selected_source_versions"] == 1
    assert atlas.api.get(f"/api/v1/replay-jobs/{first['id']}").status_code == 200
    missing = atlas.api.get("/api/v1/replay-jobs/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"cutoff": "2999-01-01T00:00:00+00:00"}, "cutoff_in_future"),
        ({"cutoff": "2000-01-01T00:00:00+00:00"}, "no_eligible_source_versions"),
        ({"cutoff": CUTOFF, "question_set": "nope"}, "unknown_question_set"),
        (
            {"cutoff": CUTOFF, "company_ids": ["00000000-0000-0000-0000-000000000000"]},
            "unknown_company",
        ),
        ({"cutoff": CUTOFF, "max_source_versions": 4}, "max_source_versions_exceeded"),
        ({"cutoff": "2025-12-31T23:59:59"}, "invalid_request"),  # no offset
    ],
)
def test_a_replay_that_cant_run_is_refused(atlas: Atlas, body: dict[str, Any], code: str) -> None:
    import_documents(atlas, "early")

    response = atlas.api.post("/api/v1/replay-jobs", json=body)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code


def test_a_replay_needs_the_local_hindsight(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    atlas = Atlas(database_url, tmp_path, hindsight[1].url)
    try:
        response = atlas.api.post("/api/v1/replay-jobs", json={"cutoff": CUTOFF})
    finally:
        atlas.engine.dispose()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "replay_not_configured"
