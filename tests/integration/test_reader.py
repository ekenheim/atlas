"""The reading agent (bottleneck-argument ticket 03): a Reader works one argument step by a loop
of `reader` role calls, each one action (search the archive, recall, read, record a Fact,
done), within its call and passage bounds and the run's token budget.

Seam: the `read_step` job (the standalone Reader) enqueued on the queue and run by single
worker passes; observed through `/api/v1` (the job's artifacts, the Facts, the run's role
calls) and the requests the LiteLLM fake received. The Source Versions are the recorded
Coherent EDGAR filings (its FY2026 10-K and a 10-Q), ingested and retained through the fixture
path with the recorded Hindsight fake. **The Reader's answers are scripted here**, each computed
from the request it answers (the hit ids it was sent). Nothing live is called.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from atlas.jobs import JobQueue
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.harness import Atlas

QUESTION = "Is indium phosphide laser capacity the constraint on AI data-center optics?"
AS_OF = "2026-12-31T00:00:00Z"
# From the Coherent FY2026 10-K (the recorded fixture's parsed text): one passage of Item 1.
SHERMAN = "we announced the expansion of our Sherman, Texas, manufacturing facility"
DURING = (
    "During fiscal 2026, we announced the expansion of our Sherman, Texas, manufacturing facility"
)
SHERMAN_QUERY = "Sherman Texas manufacturing facility expansion"
ACTIONS = ("search_archive", "recall", "read", "record_fact", "done")


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


@pytest.fixture
def llm() -> FakeLiteLLM:
    return FakeLiteLLM()


@pytest.fixture
def litellm(llm: FakeLiteLLM) -> Iterator[Served]:
    with serve(llm.handle) as served:
        yield served
        served.raise_errors()


@pytest.fixture
def start(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
) -> Iterator[Callable[..., Atlas]]:
    started: list[Atlas] = []

    def make(**overrides: Any) -> Atlas:
        atlas = Atlas(database_url, tmp_path, hindsight[1].url, litellm.url, **overrides)
        started.append(atlas)
        atlas.apply_template()
        seeded = atlas.cli("companies", "seed")
        assert seeded.returncode == 0, seeded.stderr
        atlas.ingest_company("coherent")
        return atlas

    yield make
    for atlas in started:
        atlas.engine.dispose()


# --- helpers --------------------------------------------------------------------------------------


def asked(body: dict[str, Any]) -> dict[str, Any]:
    """A chat request's user message: `{"request": ..., "retrieved_data": [...]}`."""
    return json.loads(body["messages"][1]["content"])


def act(name: str, **args: JsonValue) -> dict[str, JsonValue]:
    """A Reader answer: the action, its arguments in the field of its name, the others null."""
    answer: dict[str, JsonValue] = {"action": name}
    answer.update({each: None for each in ACTIONS})
    answer[name] = args
    return answer


def holding(body: dict[str, Any], words: str) -> str:
    """The id of the hit or window the Reader was sent whose text holds `words`."""
    sent = [each for each in asked(body)["retrieved_data"] if words in each["text"]]
    assert sent, f"no passage sent holds {words!r}"
    return sent[0]["id"]


def fact(
    passage: Callable[[dict[str, Any]], str],
    quote: str,
    *,
    statement: str,
    status: str,
    step: str = "relief",
    quantity: dict[str, JsonValue] | None = None,
    period: str | None = None,
) -> ChatReply:
    """A `record_fact` answer in the single-fact form (`reader.v1`'s, still accepted)."""
    return ChatReply.answer(
        lambda body: act(
            "record_fact",
            passage_id=passage(body),
            quote=quote,
            company_slug="coherent",
            step=step,
            statement=statement,
            quantity=quantity,
            period=period,
            status=status,
            challenges=[],
        ),
        tokens=(2000, 120),
    )


def next_window(body: dict[str, Any]) -> dict[str, JsonValue]:
    """Read the window after the one the last result read ("..., window 7 of 17")."""
    [window] = asked(body)["request"]["results"][-1]["items"]
    shown = int(window["note"].split("window ")[1].split(" of ")[0])
    return act("read", ref=window["id"], source_version_id=None, anchor=None, window=shown + 1)


def read_step(atlas: Atlas, step: str = "relief", **payload: JsonValue) -> str:
    """Enqueue a `read_step` job for Coherent's step and run it; its job ID."""
    body: dict[str, JsonValue] = {
        "theme": "photonics",
        "question": QUESTION,
        "step": step,
        "company_ids": [atlas.company("coherent")["id"]],
        "as_of": AS_OF,
    }
    job = JobQueue(atlas.engine).enqueue("read_step", f"read:{step}", body | payload).job
    atlas.worker_pass()
    return str(job.id)


def reader_requests(llm: FakeLiteLLM) -> list[dict[str, Any]]:
    return [body for body in llm.chat_requests() if body["metadata"]["role"] == "reader"]


# --- the tests ------------------------------------------------------------------------------------


def test_a_reader_searches_reads_records_facts_and_is_told_why_one_was_refused(
    start: Callable[..., Atlas], llm: FakeLiteLLM
) -> None:
    atlas = start()
    llm.script_role(
        "reader",
        ChatReply.json(
            act("search_archive", query=SHERMAN_QUERY, company_slugs=["coherent"]),
            tokens=(1500, 60),
        ),
        # Accepted: the quote is in the hit, as written; an announcement, recorded as planned.
        fact(
            lambda body: holding(body, SHERMAN),
            SHERMAN,
            statement="Coherent announced the expansion of its Sherman, Texas, manufacturing"
            " facility during fiscal 2026.",
            status="planned",
            period="fiscal 2026",
        ),
        # Refused: the hit doesn't say it.
        fact(
            lambda body: holding(body, SHERMAN),
            "Coherent supplies NVIDIA with advanced lasers from Sherman",
            statement="Coherent supplies NVIDIA with advanced lasers.",
            status="in_effect",
        ),
        # Refused by the Fact's own check: the quantity's number is not in the quote.
        fact(
            lambda body: holding(body, DURING),
            DURING,
            statement="Coherent announced a threefold expansion of its Sherman facility.",
            status="planned",
            quantity={"value": 3, "unit": "x", "metric": "Sherman capacity"},
        ),
        # Reads around the hit: the window of Item 1 it starts in, then the next one.
        ChatReply.answer(
            lambda body: act(
                "read",
                ref=holding(body, SHERMAN),
                source_version_id=None,
                anchor=None,
                window=None,
            ),
            tokens=(2500, 50),
        ),
        ChatReply.answer(next_window, tokens=(3000, 50)),
        ChatReply.json(
            act("done", summary="Coherent announced the Sherman expansion; no capacity figure."),
            tokens=(3000, 40),
        ),
    )

    job_id = read_step(atlas)

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    artifacts = job["artifacts"]
    assert (artifacts["reader_status"], artifacts["stop_reason"]) == ("done", "done")
    assert artifacts["step"] == "relief"
    assert artifacts["calls"] == 7
    assert artifacts["summary"].startswith("Coherent announced the Sherman expansion")
    # What it searched and read is on the artifacts.
    [searched] = artifacts["searches"]
    assert (searched["query"], searched["company_slugs"]) == (SHERMAN_QUERY, ["coherent"])
    assert 0 < searched["hits"] <= 6
    first, second = artifacts["reads"]
    assert (first["section"], second["section"]) == ("part-i-item-1", "part-i-item-1")
    assert second["window"] == first["window"] + 1
    assert artifacts["passages"] == searched["hits"] + 2
    # One Fact recorded, two refused with their reasons.
    [recorded] = artifacts["facts"]
    ten_k = recorded["source_version_id"]
    assert (recorded["company"], recorded["step"], recorded["status"]) == (
        "coherent",
        "relief",
        "planned",
    )
    assert [r["reason_code"] for r in artifacts["refused"]] == [
        "quote_not_found",
        "quantity_not_in_quote",
    ]
    assert (artifacts["facts_recorded"], artifacts["facts_refused"]) == (1, 2)
    # The standalone Reader has no question plan (pilot-review R2-01): its search is not held
    # to the question's terms, and its Fact answers no part.
    assert (searched["part"], recorded["part"]) == (None, None)
    assert artifacts["facts_by_part"] == {"none": 1}
    # The Fact, through the Facts API: the quote at its archived span, its status kept.
    facts = atlas.get("/api/v1/facts", step="relief")["items"]
    [found] = facts
    assert found["id"] == recorded["fact_id"]
    assert (found["status"], found["period"], found["quantity"]) == (
        "planned",
        "fiscal 2026",
        None,
    )
    assert found["investigation_id"] is None
    assert found["part"] is None
    assertion = found["assertion"]
    assert assertion["quote"] == SHERMAN
    assert assertion["source_version_id"] == ten_k
    assert assertion["epistemic_type"] == "company_claim"
    assert assertion["extractor_version"] == "reader.v4"
    assert atlas.parsed(ten_k)[assertion["span_start"] : assertion["span_end"]] == SHERMAN
    # Each refusal came back to the Reader in its next call, with the reason.
    calls = reader_requests(llm)
    assert len(calls) == 7
    after_first_refusal = asked(calls[3])["request"]
    assert after_first_refusal["refused"] == 1
    last = after_first_refusal["results"][-1]
    assert (last["action"], last["ok"]) == ("record_fact", False)
    assert last["message"].startswith("refused (quote_not_found)")
    after_second = asked(calls[4])["request"]["results"][-1]
    assert after_second["message"].startswith("refused (quantity_not_in_quote)")
    # The request tells it the step, the companies (the seed first) and what it has done.
    request = asked(calls[1])["request"]
    assert request["step"]["key"] == "relief"
    assert (request["question_parts"], request["step"]["focus"]) == ([], None)
    assert request["companies"][0] == {
        "slug": "coherent",
        "name": "Coherent",
        "layer": atlas.company("coherent")["layer"],
        "seed": True,
    }
    assert request["searched"] == [f'"{SHERMAN_QUERY}" in coherent: {searched["hits"]} hits']
    assert (request["calls_left"], request["passages_left"]) == (22, 40 - searched["hits"])
    assert all(each["trust"] == "low" for each in asked(calls[1])["retrieved_data"])
    assert [each["ref"] for each in asked(calls[6])["request"]["recorded"]] == ["r1"]
    # Every call is a role call of the run, with its tokens.
    role_calls = atlas.get(f"/api/v1/runs/{artifacts['run_id']}/role-calls")
    assert [(c["role"], c["status"]) for c in role_calls["role_calls"]] == [
        ("reader", "accepted")
    ] * 7
    assert (role_calls["tokens_in"], role_calls["tokens_out"]) == (16_000, 560)
    assert {body["metadata"]["run_id"] for body in calls} == {artifacts["run_id"]}


def test_the_reader_stops_at_its_call_bound_and_is_refused_past_its_passage_bound(
    start: Callable[..., Atlas], llm: FakeLiteLLM
) -> None:
    atlas = start(reader_max_calls=3, reader_max_passages=2)
    searching = ChatReply.json(
        act("search_archive", query="indium phosphide capacity", company_slugs=[]),
        tokens=(800, 40),
    )
    llm.script_role("reader", searching, searching, searching)

    job_id = read_step(atlas, "constraint")

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    artifacts = job["artifacts"]
    assert (artifacts["reader_status"], artifacts["stop_reason"]) == ("bounded", "max_calls")
    assert artifacts["calls"] == 3
    assert artifacts["passages"] == 2
    assert [s["hits"] for s in artifacts["searches"]] == [2]
    calls = reader_requests(llm)
    assert len(calls) == 3  # no fourth call: the bound stops it
    second = asked(calls[1])["request"]
    assert (second["calls_left"], second["passages_left"]) == (1, 0)
    refused = asked(calls[2])["request"]["results"][-1]
    assert (refused["action"], refused["ok"]) == ("search_archive", False)
    assert "passage budget is spent" in refused["message"]
    assert atlas.get("/api/v1/facts", step="constraint")["items"] == []


def test_two_invalid_answers_in_a_row_stop_the_reader(
    start: Callable[..., Atlas], llm: FakeLiteLLM
) -> None:
    atlas = start()
    # Names one action and fills another: invalid, repaired once, then quarantined; twice.
    wrong = act("done", summary="nothing")
    wrong["action"] = "recall"
    llm.script_role("reader", *(ChatReply.json(wrong, tokens=(300, 20)),) * 4)

    job_id = read_step(atlas, "control")

    artifacts = atlas.get(f"/api/v1/jobs/{job_id}")["artifacts"]
    assert (artifacts["reader_status"], artifacts["stop_reason"]) == ("bounded", "quarantined")
    assert (artifacts["calls"], artifacts["quarantined"]) == (2, 2)
    role_calls = atlas.get(f"/api/v1/runs/{artifacts['run_id']}/role-calls")["role_calls"]
    assert [c["status"] for c in role_calls] == ["quarantined", "quarantined"]
    # The second call was told the first answer was set aside.
    second = asked(reader_requests(llm)[2])["request"]["results"][-1]
    assert (second["action"], second["ok"]) == ("invalid", False)
    # The control step looks for qualified suppliers and the competitors the company names.
    looks_for = asked(reader_requests(llm)[0])["request"]["step"]["looks_for"]
    assert "how many suppliers the customers have qualified" in looks_for
    assert "which competitors the company itself names" in looks_for


def test_a_recall_lists_the_sections_memory_points_to_and_the_reader_reads_one(
    start: Callable[..., Atlas], llm: FakeLiteLLM, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    atlas = start()
    llm.script_role(
        "reader",
        ChatReply.json(act("recall", query="Coherent Sherman capacity"), tokens=(700, 30)),
        ChatReply.answer(
            lambda body: act(
                "read",
                ref=asked(body)["request"]["results"][-1]["items"][0]["id"],
                source_version_id=None,
                anchor=None,
                window=None,
            ),
            tokens=(900, 30),
        ),
        ChatReply.json(act("done", summary="read where Memory pointed"), tokens=(900, 20)),
    )

    job_id = read_step(atlas, "capture")

    artifacts = atlas.get(f"/api/v1/jobs/{job_id}")["artifacts"]
    assert artifacts["reader_status"] == "done"
    [recalled] = artifacts["recalls"]
    assert recalled["query"] == "Coherent Sherman capacity"
    assert recalled["memories"] > 0
    # Asked as investigations ask Memory, at the Reader's text budget and the step's as-of time,
    # with every observation's source facts (they point at the sections to read).
    [sent] = hindsight[0].requests("POST", "memories/recall")
    assert sent == {
        "query": "Coherent Sherman capacity",
        "budget": "high",
        "tags": ["theme:photonics"],
        "tags_match": "any_strict",
        "max_tokens": 16_000,
        "prefer_observations": True,
        "query_timestamp": "2026-12-31T00:00:00+00:00",
        "include": {"source_facts": {"max_tokens": -1}, "chunks": {}},
    }
    calls = reader_requests(llm)
    memory = asked(calls[1])["request"]["results"][-1]["items"][0]
    assert memory["id"] == "m1"
    # Memory's text is sent as low-trust data, never quoted as a Fact; the Reader reads the
    # section it points to.
    sent_memory = next(each for each in asked(calls[1])["retrieved_data"] if each["id"] == "m1")
    assert sent_memory["trust"] == "low"
    [read] = artifacts["reads"]
    assert (read["source_version_id"], read["section"]) == (
        memory["source_version_id"],
        memory["section"],
    )
    assert artifacts["passages"] == 1  # a memory is not a passage; the window is


def one_fact(body: dict[str, Any], quote: str, statement: str, status: str) -> dict[str, JsonValue]:
    return {
        "passage_id": holding(body, SHERMAN),
        "quote": quote,
        "company_slug": "coherent",
        "step": "relief",
        "statement": statement,
        "quantity": None,
        "period": None,
        "status": status,
        "challenges": [],
    }


def test_one_record_fact_carries_several_facts_each_recorded_or_refused_on_its_own(
    start: Callable[..., Atlas], llm: FakeLiteLLM
) -> None:
    atlas = start()
    llm.script_role(
        "reader",
        ChatReply.json(
            act("search_archive", query=SHERMAN_QUERY, company_slugs=["coherent"]),
            tokens=(1500, 60),
        ),
        # Two Facts from one hit in one call: the first is in the hit, the second is not.
        ChatReply.answer(
            lambda body: act(
                "record_fact",
                facts=[
                    one_fact(
                        body,
                        SHERMAN,
                        "Coherent announced the expansion of its Sherman, Texas, manufacturing"
                        " facility.",
                        "planned",
                    ),
                    one_fact(
                        body,
                        "Sherman doubled its laser output in the quarter",
                        "Coherent's Sherman facility doubled its laser output.",
                        "in_effect",
                    ),
                ],
            ),
            tokens=(2000, 200),
        ),
        ChatReply.json(act("done", summary="one Fact on the Sherman expansion"), tokens=(2000, 30)),
    )

    job_id = read_step(atlas)

    artifacts = atlas.get(f"/api/v1/jobs/{job_id}")["artifacts"]
    assert (artifacts["reader_status"], artifacts["calls"]) == ("done", 3)
    assert (artifacts["facts_recorded"], artifacts["facts_refused"]) == (1, 1)
    [recorded] = artifacts["facts"]
    assert (recorded["ref"], recorded["status"]) == ("r1", "planned")
    [refused] = artifacts["refused"]
    assert refused["reason_code"] == "quote_not_found"
    [found] = atlas.get("/api/v1/facts", step="relief")["items"]
    assert found["assertion"]["quote"] == SHERMAN
    # Both outcomes came back to the Reader in its next call, Fact by Fact.
    request = asked(reader_requests(llm)[2])["request"]
    assert (request["refused"], [f["ref"] for f in request["recorded"]]) == (1, ["r1"])
    result = request["results"][-1]
    assert (result["action"], result["ok"]) == ("record_fact", False)
    assert result["message"].startswith("1 of 2 facts recorded; ")
    assert "fact 1: recorded as r1 (coherent, relief, planned)" in result["message"]
    assert "fact 2: refused (quote_not_found): " in result["message"]


def test_done_before_any_search_is_refused_and_counted_as_a_call(
    start: Callable[..., Atlas], llm: FakeLiteLLM
) -> None:
    atlas = start()
    llm.script_role(
        "reader",
        # The 0.5.1 invalidation Reader's first answer: nothing searched, nothing to summarize.
        ChatReply.json(act("done", summary="no searches yet; nothing to say"), tokens=(800, 30)),
        ChatReply.json(
            act("search_archive", query="new entrants capacity", company_slugs=["coherent"]),
            tokens=(900, 40),
        ),
        ChatReply.json(act("done", summary="searched; no new entrant named"), tokens=(1500, 30)),
    )

    job_id = read_step(atlas, "invalidation")

    artifacts = atlas.get(f"/api/v1/jobs/{job_id}")["artifacts"]
    assert (artifacts["reader_status"], artifacts["stop_reason"]) == ("done", "done")
    assert artifacts["calls"] == 3
    assert artifacts["summary"] == "searched; no new entrant named"
    assert [s["query"] for s in artifacts["searches"]] == ["new entrants capacity"]
    calls = reader_requests(llm)
    assert len(calls) == 3
    refused = asked(calls[1])["request"]["results"][-1]
    assert (refused["action"], refused["ok"]) == ("done", False)
    assert refused["message"].startswith("search first: ")
    assert asked(calls[1])["request"]["calls_left"] == 22


# From the Coherent FY2026 10-K: the NVIDIA agreement entered, as a contiguous part of its
# sentence (the rest, "to advance the development of ...", would say development is its aim).
NVIDIA = "the Company entered into a multi-year strategic agreement with NVIDIA"
NVIDIA_QUERY = "multi-year strategic agreement with NVIDIA"
NVIDIA_STATEMENT = "Coherent entered into a multi-year strategic agreement with NVIDIA."


def test_a_fact_whose_status_its_quote_contradicts_is_refused_and_the_reader_is_told_the_status_to_use(  # noqa: E501 (the ticket names it)
    start: Callable[..., Atlas], llm: FakeLiteLLM
) -> None:
    atlas = start()
    llm.script_role(
        "reader",
        ChatReply.json(
            act("search_archive", query=NVIDIA_QUERY, company_slugs=["coherent"]),
            tokens=(1500, 60),
        ),
        # An agreement recorded as development under way: refused, with the status to use.
        fact(
            lambda body: holding(body, NVIDIA),
            NVIDIA,
            step="capture",
            statement=NVIDIA_STATEMENT,
            status="in_development",
        ),
        # Recorded again with the status the refusal names.
        fact(
            lambda body: holding(body, NVIDIA),
            NVIDIA,
            step="capture",
            statement=NVIDIA_STATEMENT,
            status="planned",
        ),
        ChatReply.json(act("done", summary="the NVIDIA agreement's commitment"), tokens=(2000, 30)),
    )

    job_id = read_step(atlas, "capture")

    artifacts = atlas.get(f"/api/v1/jobs/{job_id}")["artifacts"]
    assert (artifacts["reader_status"], artifacts["calls"]) == ("done", 4)
    [refused] = artifacts["refused"]
    assert refused["reason_code"] == "status_agreement"
    [recorded] = artifacts["facts"]
    assert (recorded["step"], recorded["status"]) == ("capture", "planned")
    [found] = atlas.get("/api/v1/facts", step="capture")["items"]
    assert found["status"] == "planned"
    assert found["assertion"]["quote"] == NVIDIA
    assert found["assertion"]["extractor_version"] == "reader.v4"
    calls = reader_requests(llm)
    told = asked(calls[2])["request"]
    assert told["refused"] == 1
    last = told["results"][-1]
    assert (last["action"], last["ok"]) == ("record_fact", False)
    assert last["message"].startswith("refused (status_agreement)")
    assert "`planned`" in last["message"]
    # The step's request says what a researcher looks for in it: customer concentration too.
    assert "customer concentration: customers over 10% of revenue" in (told["step"]["looks_for"])
    assert "'accounted for'" in told["step"]["looks_for"]
