"""A session's statements judged (beliefs ticket 07): `POST /api/v1/statements/judge` and
`/relate`.

Seam: the `/api/v1` API over Coherent's recorded 10-K (the fixture ingest path), two Facts
recorded through `POST /api/v1/facts` at their real offsets, the LiteLLM fake scripting the
`finding_judge` and `counter_judge` answers, and the role calls the run records. Nothing live.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.harness import Atlas

QUESTION = "Is Coherent's InP laser capacity the constraint on AI data-center optics?"
AGREEMENT = (
    "On March 2, 2026, the Company entered into a multi-year strategic agreement with NVIDIA to"
    " advance the development of advanced optics technologies"
)
COMPETITION = "We may encounter increased competition"
OVERSTATED = "Coherent has a multi-year supply agreement with NVIDIA that is already shipping."
STATEMENT = "Coherent entered into a multi-year strategic agreement with NVIDIA in March 2026."


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
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
) -> Iterator[Atlas]:
    harness = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm.url,
        llm_role_models={"finding_judge": "luna", "counter_judge": "luna"},
    )
    harness.apply_template()
    seeded = harness.cli("companies", "seed")
    assert seeded.returncode == 0, seeded.stderr
    harness.ingest_company("coherent")
    yield harness
    harness.engine.dispose()


def asked(body: dict[str, Any]) -> dict[str, Any]:
    return json.loads(body["messages"][1]["content"])


def fact(atlas: Atlas, quote: str, *, status: str, statement: str, step: str = "control") -> str:
    """Record a Fact at `quote`'s real offsets in the Coherent filing that holds it."""
    [coherent] = [c for c in atlas.get("/api/v1/companies")["items"] if c["slug"] == "coherent"]
    documents = atlas.get(f"/api/v1/companies/{coherent['id']}/sources", limit=100)["items"]
    for document in documents:
        version = document["latest_version_id"]
        content = atlas.api.get(
            f"/api/v1/source-versions/{version}/content", params={"kind": "parsed"}
        )
        start = content.text.find(quote)
        if start >= 0:
            break
    else:
        raise AssertionError(f"no Coherent document holds {quote!r}")
    response = atlas.api.post(
        "/api/v1/facts",
        json={
            "subject_company_id": coherent["id"],
            "source_version_id": version,
            "quote": quote,
            "span_start": start,
            "span_end": start + len(quote),
            "epistemic_type": "company_claim",
            "step": step,
            "statement": statement,
            "period": None,
            "status": status,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["fact"]["id"]


@pytest.fixture
def facts(atlas: Atlas) -> tuple[str, str]:
    agreement = fact(atlas, AGREEMENT, status="in_development", statement=STATEMENT)
    competition = fact(
        atlas,
        COMPETITION,
        status="hedged",
        statement="Coherent says it may encounter increased competition.",
    )
    return agreement, competition


def supported(body: dict[str, Any]) -> JsonValue:
    """The finding judge: supported, the statement one clause based on the first quote whole."""
    request = asked(body)
    quote = request["retrieved_data"][0]
    return {
        "clauses": [
            {
                "text": request["request"]["finding"]["statement"],
                "ref": quote["id"],
                "basis": quote["text"],
            }
        ],
        "verdict": "supported",
        "beyond": [],
        "kinds": [],
        "reason": "the quote states it",
    }


def judge(atlas: Atlas, statement: str, fact_ids: list[str], **extra: Any) -> Any:
    return atlas.api.post(
        "/api/v1/statements/judge",
        json={"question": QUESTION, "statement": statement, "fact_ids": fact_ids} | extra,
    )


def test_a_supported_statement_is_answered_on_the_role_model_and_recorded_in_a_run(
    atlas: Atlas, llm: FakeLiteLLM, facts: tuple[str, str]
) -> None:
    llm.script_role("finding_judge", ChatReply.answer(supported, tokens=(400, 40)))

    response = judge(atlas, STATEMENT, [facts[0]])

    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["verdict"] == "supported"
    assert answer["unverified"] == []
    assert answer["refs"] == {"c1": facts[0]}
    assert answer["judge"] == "finding_judge.v5"
    assert [v["decided"] for v in answer["votes"]] == [True]
    [call] = [b for b in llm.chat_requests() if b["metadata"]["role"] == "finding_judge"]
    assert call["model"] == "luna"
    assert call["metadata"]["run_id"] == answer["run_id"]
    request = asked(call)
    # The judge is sent the Fact's reading and the date, and the quote as low-trust data.
    [claim] = request["request"]["claims"]
    assert claim["status"] == "in_development"
    assert claim["source_date"]
    [quote] = request["retrieved_data"]
    assert (quote["id"], quote["text"], quote["trust"]) == ("c1", AGREEMENT, "low")
    calls = atlas.get(f"/api/v1/runs/{answer['run_id']}/role-calls")
    assert [c["role"] for c in calls["role_calls"]] == ["finding_judge"]


def test_a_misstated_statement_comes_back_with_its_bases_and_reason(
    atlas: Atlas, llm: FakeLiteLLM, facts: tuple[str, str]
) -> None:
    def misstated(body: dict[str, Any]) -> JsonValue:
        quote = asked(body)["retrieved_data"][0]
        return {
            "clauses": [
                {
                    "text": "Coherent has a multi-year supply agreement with NVIDIA",
                    "ref": quote["id"],
                    "basis": "entered into a multi-year strategic agreement with NVIDIA",
                },
                {"text": "that is already shipping", "ref": None, "basis": None},
            ],
            "verdict": "misstated",
            "beyond": ["supply agreement", "already shipping"],
            "kinds": ["tense_or_status", "unstated"],
            "reason": "the quote is a development agreement, not a supply agreement in shipment",
        }

    llm.script_role("finding_judge", ChatReply.answer(misstated, tokens=(400, 40)))

    answer = judge(atlas, OVERSTATED, [facts[0]]).json()

    assert answer["verdict"] == "misstated"
    assert answer["beyond"] == ["supply agreement", "already shipping"]
    assert answer["kinds"] == ["tense_or_status", "unstated"]
    assert [c["ref"] for c in answer["clauses"]] == ["c1", None]
    assert "development agreement" in answer["reason"]
    assert answer["unverified"] == ["that is already shipping"]


def test_a_supported_answer_whose_basis_is_not_in_the_quote_is_turned_to_misstated(
    atlas: Atlas, llm: FakeLiteLLM, facts: tuple[str, str]
) -> None:
    def invented(body: dict[str, Any]) -> JsonValue:
        request = asked(body)
        return {
            "clauses": [
                {
                    "text": request["request"]["finding"]["statement"],
                    "ref": "c1",
                    "basis": "the agreement guarantees NVIDIA supply through 2030",
                }
            ],
            "verdict": "supported",
            "beyond": [],
            "kinds": [],
            "reason": "the quote states it",
        }

    llm.script_role("finding_judge", ChatReply.answer(invented, tokens=(400, 40)))

    answer = judge(atlas, "Coherent guarantees NVIDIA supply through 2030.", [facts[0]]).json()

    assert answer["verdict"] == "misstated"
    assert answer["kinds"] == ["unstated"]
    assert answer["reason"].startswith("basis unverified")
    assert answer["unverified"] == ["Coherent guarantees NVIDIA supply through 2030."]


def test_the_bridge_s_unknown_items_500_is_transient_and_the_next_call_answers(
    atlas: Atlas, llm: FakeLiteLLM, facts: tuple[str, str]
) -> None:
    llm.script_role(
        "finding_judge",
        ChatReply.error(500, "Unknown items in responses API response: [{'type': 'x'}]"),
        ChatReply.answer(supported, tokens=(400, 40)),
    )

    first = judge(atlas, STATEMENT, [facts[0]])
    second = judge(atlas, STATEMENT, [facts[0]])

    assert first.status_code == 503, first.text
    assert first.json()["error"]["code"] == "role_unavailable"
    assert second.status_code == 200, second.text
    assert second.json()["verdict"] == "supported"


def test_counterevidence_facts_are_related_to_the_cited_facts_in_a_given_run(
    atlas: Atlas, llm: FakeLiteLLM, facts: tuple[str, str]
) -> None:
    agreement, competition = facts
    llm.script_role("finding_judge", *(ChatReply.answer(supported, tokens=(400, 40)),) * 2)
    llm.script_role("counter_judge", ChatReply.answer(relating("limits"), tokens=(600, 60)))
    first = judge(atlas, STATEMENT, [agreement]).json()

    second = judge(
        atlas, STATEMENT, [agreement], counter_fact_ids=[competition], run_id=first["run_id"]
    ).json()

    assert second["run_id"] == first["run_id"]
    assert second["counter_relations"] == [
        {
            "counter_fact_id": competition,
            "fact_id": agreement,
            "relation": "limits",
            "reason": "k1 limits it",
        }
    ]


def relating(relation: str) -> Any:
    def answer(body: dict[str, Any]) -> JsonValue:
        challenged = asked(body)["request"]["challenged"]
        return {
            "relations": [
                {"ref": each["ref"], "relation": relation, "reason": f"k1 {relation} it"}
                for each in challenged
            ]
        }

    return answer


@pytest.mark.parametrize("relation", ["contradicts", "unrelated"])
def test_relate_gives_the_counter_judge_s_relation_of_two_facts(
    atlas: Atlas, llm: FakeLiteLLM, facts: tuple[str, str], relation: str
) -> None:
    agreement, competition = facts
    llm.script_role("counter_judge", ChatReply.answer(relating(relation), tokens=(600, 60)))

    response = atlas.api.post(
        "/api/v1/statements/relate",
        json={"question": QUESTION, "fact_id": agreement, "counter_fact_id": competition},
    )

    assert response.status_code == 200, response.text
    answer = response.json()
    assert (answer["relation"], answer["judge"]) == (relation, "counter_judge.v1")
    [call] = [b for b in llm.chat_requests() if b["metadata"]["role"] == "counter_judge"]
    assert call["model"] == "luna"
    sent = asked(call)
    assert sent["request"]["counter"]["ref"] == "k1"
    assert {each["id"]: each["text"] for each in sent["retrieved_data"]} == {
        "k1": COMPETITION,
        "f1": AGREEMENT,
    }


def test_an_unknown_fact_or_run_is_refused(atlas: Atlas, facts: tuple[str, str]) -> None:
    nobody = "00000000-0000-0000-0000-000000000000"

    unknown_fact = judge(atlas, STATEMENT, [nobody])
    unknown_run = judge(atlas, STATEMENT, [facts[0]], run_id=nobody)

    assert unknown_fact.status_code == 422
    assert unknown_fact.json()["error"]["code"] == "unknown_fact"
    assert unknown_run.status_code == 404
