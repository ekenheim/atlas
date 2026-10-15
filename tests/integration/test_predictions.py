"""A published Hypothesis's predictions and its call (atlas-beliefs ticket 19): publishing a
version makes a call dated the publication; a prediction is recorded on a published version only
and settled once from a Fact, an XBRL observation or a stored TradingView close; its state
(`open`, `settled`, `lapsed`) is read from the deadline; a rejected Hypothesis's predictions stay
listed.

Seam: the `/api/v1` API and single worker passes on a fresh database holding Lumentum's recorded
EDGAR press release and companyfacts; the application clock is the test's. Facts and Beliefs go
through the API; LiteLLM is the scripted chat fake (**the Editor's and the finding judge's answers
are written here**), Hindsight the recorded fake, TradingView the transport-level fake with bars
built around the real publication date. Nothing live is called.
"""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.api.app import create_app
from atlas.audit import Actor
from atlas.cli import run_apply_template
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.fakes.tradingview import ACCESS_TOKEN, FakeTradingView
from tests.harness import TEMPLATE, THEMES, Atlas, Clock

URL_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
QUARTER = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
YEAR = "Net revenue for fiscal year 2026 was $3.01 billion"
FACTS = {
    QUARTER: ("Lumentum's fourth-quarter fiscal 2026 net revenue was $1.01 billion.", 1.01),
    YEAR: ("Lumentum's fiscal 2026 net revenue was $3.01 billion.", 3.01),
}
CONSTRAINT = "Lumentum's revenue is growing fast enough to strain its laser capacity."
CAPTURE = "Lumentum captures a growing share of the value in its laser supply chain."
CONSTRAINT_STATEMENT = (
    "Lumentum reported net revenue of $1.01 billion for the fourth quarter of fiscal year 2026."
)
CAPTURE_STATEMENT = "Lumentum reported net revenue of $3.01 billion for fiscal year 2026."
THESIS = "Lumentum may be straining its laser capacity as its revenue grows in fiscal year 2026."
PREDICTION = "Lead times stay long"
DRAFTER = "hypothesis_editor"
ACTOR = "claude-session"
UNIVERSE = ("coherent", "lumentum", "innolight")


def small_universe(path: Path) -> Path:
    document = yaml.safe_load(THEMES.read_text(encoding="utf-8"))
    document["companies"] = {k: v for k, v in document["companies"].items() if k in UNIVERSE}
    for theme in document["themes"].values():
        theme["companies"] = [c for c in theme["companies"] if c in UNIVERSE]
    target = path / "themes.yaml"
    target.write_text(yaml.safe_dump(document), encoding="utf-8")
    return target


def bars(closes: dict[date, float]) -> str:
    return json.dumps(
        {
            "bars": [
                {
                    "t": int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp()),
                    "o": close,
                    "h": close,
                    "l": close,
                    "c": close,
                    "v": 1000,
                }
                for day, close in sorted(closes.items())
            ]
        }
    )


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
def tradingview() -> Iterator[tuple[FakeTradingView, Served]]:
    fake = FakeTradingView()
    with serve(fake.handle) as served:
        yield fake, served
        served.raise_errors()


def asked(body: dict[str, Any]) -> dict[str, Any]:
    return json.loads(body["messages"][1]["content"])


def editor(body: dict[str, Any]) -> JsonValue:
    """The Hypothesis Editor: it cites, per step, the Belief it is sent for that step."""
    request = asked(body)["request"]
    by_step = {each["step"]: each["ref"] for each in request["beliefs"]}
    statements = {"constraint": CONSTRAINT_STATEMENT, "capture": CAPTURE_STATEMENT}
    return {
        "thesis_statement": THESIS,
        "thesis_belief_refs": [next(iter(by_step.values()))],
        "mechanism": {
            "demand_driver": "AI optics deployments",
            "possible_constraint": "laser capacity",
            "economic_capture_question": None,
        },
        "measurable_predictions": [PREDICTION, "Revenue keeps growing"],
        "catalysts": ["New supply agreements"],
        "falsifiers": ["Qualified second-source capacity comes online"],
        "required_evidence": ["Capacity figures from an original document"],
        "alternative_explanations": ["Inventory build"],
        "unresolved_questions": ["Does revenue growth reflect scarcity or volume?"],
        "steps": [
            {"step": step, "statement": said, "belief_refs": [by_step[step]]}
            for step, said in statements.items()
            if step in by_step
        ],
    }


def supporting(body: dict[str, Any]) -> JsonValue:
    request = asked(body)
    statement = request["request"]["finding"]["statement"]
    quote = request["retrieved_data"][0]
    return {
        "clauses": [{"text": statement, "ref": quote["id"], "basis": quote["text"]}],
        "verdict": "supported",
        "beyond": [],
        "kinds": [],
        "reason": "the quotes state it",
    }


class Predictions:
    """Atlas with a Hypothesis drafted from two proven Beliefs, publishable, at a clock the test
    sets."""

    def __init__(
        self,
        database_url: str,
        tmp_path: Path,
        hindsight_url: str,
        litellm_url: str,
        tradingview: tuple[FakeTradingView, Served],
    ) -> None:
        self.fake = tradingview[0]
        self._facts: dict[str, str] = {}
        self.atlas = Atlas(
            database_url,
            tmp_path,
            hindsight_url,
            litellm_url,
            finding_judge=True,
            hindsight_template_path=TEMPLATE,
            themes_config=small_universe(tmp_path),
            tradingview_enabled=True,
            tradingview_mcp_url=f"{tradingview[1].url}/mcp",
            tradingview_access_token=ACCESS_TOKEN,
            tradingview_token_file=tmp_path / "no-token-file.json",
            tradingview_rate_per_s=1.0,
        )
        self.engine = self.atlas.engine
        self.clock = Clock(datetime.now(UTC))
        self.api: TestClient = TestClient(create_app(self.atlas.settings(), clock=self.clock))
        assert run_apply_template(self.atlas.settings(), None) == 0
        assert self.atlas.cli("companies", "seed").returncode == 0
        plain = self.atlas.settings().model_copy(update={"hindsight_url": None})
        queue = JobQueue(self.engine, actor=Actor(ACTOR))
        queue.enqueue(INGEST_KIND, "lumentum", ingest_payload("lumentum", ["8-K"], None))
        assert Worker(queue, builtin_registry(plain)).run_once() >= 1

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def post(self, path: str, body: dict[str, Any], status: int = 200) -> Any:
        response = self.api.post(path, json=body)
        assert response.status_code == status, response.text
        return response.json()

    def company(self, slug: str = "lumentum") -> str:
        return self.atlas.company(slug)["id"]

    def fact(self, quote: str) -> str:
        """The Fact quoting `quote`, recorded the first time it is asked for."""
        if quote not in self._facts:
            self._facts[quote] = self._record_fact(quote)
        return self._facts[quote]

    def _record_fact(self, quote: str) -> str:
        version = self.atlas.version(URL_EX991)["id"]
        parsed = self.atlas.parsed(version)
        start = parsed.index(quote)
        statement, value = FACTS[quote]
        return self.post(
            "/api/v1/facts",
            {
                "subject_company_id": self.company(),
                "source_version_id": version,
                "quote": quote,
                "span_start": start,
                "span_end": start + len(quote),
                "epistemic_type": "company_claim",
                "step": "context",
                "statement": statement,
                "quantity": {"value": value, "unit": "USD", "metric": "figure"},
                "period": "FY2026",
                "status": "in_effect",
            },
            status=201,
        )["fact"]["id"]

    def belief(self, statement: str, step: str, quote: str) -> str:
        belief = self.post(
            "/api/v1/beliefs",
            {
                "statement": statement,
                "theme": "photonics",
                "step": step,
                "company_ids": [self.company()],
                "as_of": "2026-09-30T00:00:00Z",
                "actor": ACTOR,
                "citations": [
                    {
                        "ref_id": self.fact(quote),
                        "valence": 0.9,
                        "weight": "load_bearing",
                        "note": "the figure",
                    }
                ],
            },
            status=201,
        )["id"]
        self.post(
            f"/api/v1/beliefs/{belief}/judge",
            {"actor": "owner", "judgement": "proven", "confidence": 0.8, "reason": "agreed"},
        )
        return belief

    def worker_pass(self) -> int:
        return self.atlas.worker_pass()

    def settle(self, key: str) -> dict[str, Any]:
        """Enqueue `settle_calls` and run worker passes at the test's clock until it is done."""
        settings = self.atlas.settings()
        queue = JobQueue(self.engine, pacing=Pacing.from_settings(settings))
        job = queue.enqueue("settle_calls", key, {}).job
        worker = Worker(queue, builtin_registry(settings, clock=self.clock))
        for _ in range(12):
            worker.run_once()
            read = self.get(f"/api/v1/jobs/{job.id}")
            if read["status"] in ("succeeded", "failed", "dead"):
                return read
        raise AssertionError("the settlement did not finish")


@pytest.fixture
def predictions(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    tradingview: tuple[FakeTradingView, Served],
) -> Iterator[Predictions]:
    started = Predictions(database_url, tmp_path, hindsight[1].url, litellm.url, tradingview)
    yield started
    started.engine.dispose()


def draft(predictions: Predictions, llm: FakeLiteLLM) -> str:
    """A Hypothesis drafted from a proven constraint and capture Belief, ready to publish."""
    predictions.belief(CONSTRAINT, "constraint", QUARTER)
    predictions.belief(CAPTURE, "capture", YEAR)
    llm.script_role(DRAFTER, ChatReply.answer(editor, tokens=(3000, 700)))
    llm.script_role("finding_judge", *(ChatReply.answer(supporting, tokens=(400, 40)),) * 3)
    saved = predictions.post("/api/v1/hypotheses", {"theme": "photonics"}, status=202)
    predictions.worker_pass()
    hypothesis_id = saved["id"]
    moved = predictions.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/transitions", json={"to": "evidence_ready"}
    )
    assert moved.status_code == 200, moved.text
    return hypothesis_id


def publish(predictions: Predictions, hypothesis_id: str) -> dict[str, Any]:
    return predictions.post(f"/api/v1/hypotheses/{hypothesis_id}/publish-version", {"version": 1})


def day_of(moment: str) -> date:
    return datetime.fromisoformat(moment).astimezone(UTC).date()


def noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, tzinfo=UTC)


def body(published: date, **overrides: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "prediction_index": 0,
        "expected_low": 100.0,
        "expected_high": 120.0,
        "deadline": (published + timedelta(days=30)).isoformat(),
        "source": "price",
        "company_id": None,
        **overrides,
    }


# --- the call a published version makes --------------------------------------------------------


def test_publishing_a_version_makes_a_call_dated_the_publication(
    predictions: Predictions, llm: FakeLiteLLM
) -> None:
    hypothesis_id = draft(predictions, llm)
    assert predictions.get("/api/v1/calls", origin="hypothesis")["items"] == []

    publish(predictions, hypothesis_id)

    (call,) = predictions.get("/api/v1/calls", origin="hypothesis")["items"]
    hypothesis = predictions.get(f"/api/v1/hypotheses/{hypothesis_id}")
    (version,) = hypothesis["versions"]
    assert call["origin_id"] == version["id"]
    assert call["claim"] == THESIS
    assert call["theme"] == "photonics"
    assert call["direction"] is None
    assert call["made_at"] == version["published_at"]
    assert [(c["slug"], c["symbol"]) for c in call["companies"]] == [("lumentum", "NASDAQ:LITE")]
    assert call["state"] == "open"
    # The two Beliefs were proven first, so each made a call of its own.
    assert len(predictions.get("/api/v1/calls", origin="belief")["items"]) == 2


# --- predictions -------------------------------------------------------------------------------


def test_a_prediction_is_recorded_on_a_published_version_only_and_listed(
    predictions: Predictions, llm: FakeLiteLLM
) -> None:
    hypothesis_id = draft(predictions, llm)
    lumentum = predictions.company()
    path = f"/api/v1/hypotheses/{hypothesis_id}/predictions"
    today = predictions.clock().date()
    unpublished = predictions.api.post(path, json=body(today, company_id=lumentum))
    assert (unpublished.status_code, unpublished.json()["error"]["code"]) == (
        409,
        "version_not_published",
    )

    publish(predictions, hypothesis_id)
    made = day_of(
        predictions.get(f"/api/v1/hypotheses/{hypothesis_id}")["versions"][0]["published_at"]
    )
    refusals = {
        "no range": (body(made, company_id=lumentum, expected_low=None, expected_high=None), 422),
        "inverted": (body(made, company_id=lumentum, expected_low=130.0), 422),
        "no company for a price": (body(made), 422),
        "no measure": (body(made, company_id=lumentum, prediction_index=None), 422),
        "no such sentence": (body(made, company_id=lumentum, prediction_index=2), 422),
        "no such version": (body(made, company_id=lumentum, version=2), 404),
        "deadline not after": (body(made, company_id=lumentum, deadline=made.isoformat()), 422),
    }
    for name, (request, status) in refusals.items():
        refused = predictions.api.post(path, json=request)
        assert refused.status_code == status, (name, refused.text)
    codes = predictions.api.post(
        path, json=body(made, company_id=lumentum, deadline=made.isoformat())
    ).json()["error"]["code"]
    assert codes == "deadline_not_after_publication"

    created = predictions.post(path, body(made, company_id=lumentum), status=201)

    assert created["measure"] == PREDICTION  # the sentence it makes measurable
    assert (created["expected_low"], created["expected_high"]) == (100.0, 120.0)
    assert created["deadline"] == (made + timedelta(days=30)).isoformat()
    assert (created["state"], created["settlement"]) == ("open", None)
    assert (created["hypothesis_status"], created["theme"], created["version"]) == (
        "reviewed",
        "photonics",
        1,
    )
    listed = predictions.get(path)
    assert [p["id"] for p in listed["items"]] == [created["id"]]
    assert predictions.get("/api/v1/predictions", state="open")["total"] == 1
    assert predictions.get("/api/v1/predictions", state="settled")["total"] == 0
    assert predictions.api.get(f"/api/v1/hypotheses/{uuid_zero()}/predictions").status_code == 404


def uuid_zero() -> str:
    return "00000000-0000-0000-0000-000000000000"


def test_a_price_prediction_lapses_and_is_settled_once_from_the_stored_close(
    predictions: Predictions, llm: FakeLiteLLM, tradingview: tuple[FakeTradingView, Served]
) -> None:
    hypothesis_id = draft(predictions, llm)
    publish(predictions, hypothesis_id)
    made = day_of(
        predictions.get(f"/api/v1/hypotheses/{hypothesis_id}")["versions"][0]["published_at"]
    )
    deadline = made + timedelta(days=30)
    path = f"/api/v1/hypotheses/{hypothesis_id}/predictions"
    within = predictions.post(path, body(made, company_id=predictions.company()), status=201)
    outside = predictions.post(
        path,
        body(
            made,
            company_id=predictions.company(),
            prediction_index=1,
            expected_high=105.0,
            expected_low=90.0,
        ),
        status=201,
    )
    nothing = predictions.post(
        path, body(made, company_id=predictions.company("innolight")), status=201
    )
    tradingview[0].ohlcv["NASDAQ:LITE"] = bars({deadline - timedelta(days=1): 110.0})
    tradingview[0].ohlcv["NYSE:COHR"] = bars({deadline - timedelta(days=1): 10.0})

    # The deadline has not come: nothing to settle with, and a day to come is refused.
    predictions.clock.now = noon(deadline - timedelta(days=5))
    assert predictions.get("/api/v1/predictions", state="lapsed")["total"] == 0
    early = predictions.api.post(
        f"{path}/{within['id']}/settle", json={"day": deadline.isoformat()}
    )
    assert (early.status_code, early.json()["error"]["code"]) == (422, "day_not_over")
    # The deadline's own day is not over either (its session may still be forming).
    predictions.clock.now = noon(deadline)
    same_day = predictions.api.post(
        f"{path}/{within['id']}/settle", json={"day": deadline.isoformat()}
    )
    assert (same_day.status_code, same_day.json()["error"]["code"]) == (422, "day_not_over")
    held = predictions.settle("deadline-day")
    assert held["status"] == "succeeded", held["failures"]
    assert held["artifacts"]["calls_due"] == 0
    assert predictions.fake.tool_calls == []

    # Past it, unsettled, it is lapsed; the daily pass stores the closes it is settled by.
    predictions.clock.now = noon(deadline + timedelta(days=2))
    assert predictions.get("/api/v1/predictions", state="lapsed")["total"] == 3
    job = predictions.settle("owed")
    assert job["status"] == "succeeded", job["failures"]
    # Each company once: the calls' (and their benchmark's) and the predictions' are the same.
    assert job["artifacts"]["companies_fetched"] == 3
    assert sorted(a["symbol"] for n, a in tradingview[0].tool_calls if "ohlcv" in n) == [
        "HKEX:3308",
        "NASDAQ:LITE",
        "NYSE:COHR",
    ]

    settled = predictions.post(f"{path}/{within['id']}/settle", {"note": "the close on the day"})
    assert settled["state"] == "settled"
    assert settled["settlement"]["outcome"] == "met"
    assert settled["settlement"]["value"] == 110.0
    assert settled["settlement"]["late"] is True
    assert settled["settlement"]["price_symbol"] == "NASDAQ:LITE"
    assert settled["settlement"]["price_day"] == deadline.isoformat()
    assert settled["settlement"]["note"] == "the close on the day"
    missed = predictions.post(f"{path}/{outside['id']}/settle", {})
    assert (missed["settlement"]["outcome"], missed["settlement"]["value"]) == ("missed", 110.0)
    absent = predictions.api.post(f"{path}/{nothing['id']}/settle", json={})
    assert (absent.status_code, absent.json()["error"]["code"]) == (409, "no_price")
    again = predictions.api.post(f"{path}/{within['id']}/settle", json={})
    assert (again.status_code, again.json()["error"]["code"]) == (409, "already_settled")
    wrong = predictions.api.post(f"{path}/{nothing['id']}/settle", json={"fact_id": uuid_zero()})
    assert (wrong.status_code, wrong.json()["error"]["code"]) == (422, "wrong_source")
    gone = predictions.api.post(f"{path}/{uuid_zero()}/settle", json={})
    assert gone.status_code == 404

    states = {p["id"]: p["state"] for p in predictions.get("/api/v1/predictions")["items"]}
    assert states == {within["id"]: "settled", outside["id"]: "settled", nothing["id"]: "lapsed"}

    for statement in (
        "UPDATE prediction SET measure = 'x'",
        "DELETE FROM prediction",
        "UPDATE prediction_settlement SET value = 0",
        "DELETE FROM prediction_settlement",
        "TRUNCATE prediction_settlement",
    ):
        with (
            pytest.raises(DBAPIError, match="insert-only"),
            predictions.engine.begin() as connection,
        ):
            connection.execute(text(statement))


def made_public_later(
    predictions: Predictions, *, fact_version: str, observation: dict[str, Any]
) -> str:
    """After publication, as a dissemination correction would make it: the Fact's document is
    available a day from now, and a copy of the XBRL observation is a filing of a later accession.
    Returns the copy's id."""
    version = predictions.atlas.version(fact_version)["id"]
    with predictions.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_version_availability_correction (id, source_version_id,"
                " available_at, available_at_basis, reason) VALUES (gen_random_uuid(), :version,"
                " now() + interval '1 day', 'sec_dissemination', 'a test: disseminated later')"
            ),
            {"version": version},
        )
        connection.execute(
            text(
                "CREATE TEMP TABLE later_observation ON COMMIT DROP AS"
                " SELECT * FROM financial_observation WHERE id = :id"
            ),
            {"id": observation["id"]},
        )
        copied = connection.execute(
            text(
                "UPDATE later_observation SET id = gen_random_uuid(),"
                " accession = '0001633978-27-000001', available_at = now() + interval '1 day',"
                " previous_observation_id = NULL,"
                " linkage = 'first', suspect_reasons = '{}' RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text("INSERT INTO financial_observation SELECT * FROM later_observation")
        )
    return str(copied)


def test_a_prediction_is_settled_from_a_facts_quantity_or_an_xbrl_observation(
    predictions: Predictions, llm: FakeLiteLLM
) -> None:
    hypothesis_id = draft(predictions, llm)
    publish(predictions, hypothesis_id)
    made = day_of(
        predictions.get(f"/api/v1/hypotheses/{hypothesis_id}")["versions"][0]["published_at"]
    )
    path = f"/api/v1/hypotheses/{hypothesis_id}/predictions"
    lumentum = predictions.company()
    fact = predictions.fact(QUARTER)  # a quantity of 1.01 (USD billion)
    observations = predictions.get(f"/api/v1/companies/{lumentum}/financial-observations")["items"]
    observation = next(each for each in observations if each["unit"] == "USD")
    value = float(observation["value"])
    # News: the document is disseminated, and the filing observed, after the version was published.
    news_observation = made_public_later(
        predictions, fact_version=URL_EX991, observation=observation
    )
    observation = observation | {"id": news_observation}

    by_fact = predictions.post(
        path,
        body(made, source="fact", expected_low=1.0, expected_high=1.2, company_id=None),
        status=201,
    )
    settled = predictions.post(f"{path}/{by_fact['id']}/settle", {"fact_id": fact})
    assert (settled["settlement"]["outcome"], settled["settlement"]["value"]) == ("met", 1.01)
    assert settled["settlement"]["fact_id"] == fact

    below = predictions.post(
        path,
        body(made, source="fact", expected_low=2.0, expected_high=3.0, company_id=None),
        status=201,
    )
    assert (
        predictions.post(f"{path}/{below['id']}/settle", {"fact_id": fact})["settlement"]["outcome"]
        == "missed"
    )

    by_xbrl = predictions.post(
        path,
        body(
            made,
            source="financial_observation",
            company_id=lumentum,
            expected_low=value - 1,
            expected_high=value + 1,
        ),
        status=201,
    )
    mismatched = predictions.api.post(
        f"{path}/{by_xbrl['id']}/settle", json={"observation_id": uuid_zero()}
    )
    assert (mismatched.status_code, mismatched.json()["error"]["code"]) == (
        422,
        "unknown_observation",
    )
    settled = predictions.post(
        f"{path}/{by_xbrl['id']}/settle", {"observation_id": observation["id"]}
    )
    assert settled["settlement"]["outcome"] == "met"
    assert settled["settlement"]["value"] == value
    assert settled["settlement"]["observation_id"] == observation["id"]


def test_a_source_already_public_at_publication_or_about_another_company_cannot_settle(
    predictions: Predictions, llm: FakeLiteLLM
) -> None:
    hypothesis_id = draft(predictions, llm)
    publish(predictions, hypothesis_id)  # now: the Lumentum filing is already public
    made = day_of(
        predictions.get(f"/api/v1/hypotheses/{hypothesis_id}")["versions"][0]["published_at"]
    )
    path = f"/api/v1/hypotheses/{hypothesis_id}/predictions"
    lumentum = predictions.company()
    fact = predictions.fact(QUARTER)
    observations = predictions.get(f"/api/v1/companies/{lumentum}/financial-observations")["items"]
    observation = next(each for each in observations if each["unit"] == "USD")

    by_fact = predictions.post(
        path, body(made, source="fact", expected_low=1.0, expected_high=1.2), status=201
    )
    old_fact = predictions.api.post(f"{path}/{by_fact['id']}/settle", json={"fact_id": fact})
    assert (old_fact.status_code, old_fact.json()["error"]["code"]) == (
        422,
        "source_before_publication",
    )
    by_xbrl = predictions.post(
        path,
        body(made, source="financial_observation", company_id=lumentum, expected_low=0.0),
        status=201,
    )
    old_observation = predictions.api.post(
        f"{path}/{by_xbrl['id']}/settle", json={"observation_id": observation["id"]}
    )
    assert (old_observation.status_code, old_observation.json()["error"]["code"]) == (
        422,
        "source_before_publication",
    )
    # A Fact is about the prediction's company when it names one (checked before the date).
    other = predictions.post(
        path,
        body(made, source="fact", expected_low=1.0, company_id=predictions.company("coherent")),
        status=201,
    )
    wrong_company = predictions.api.post(f"{path}/{other['id']}/settle", json={"fact_id": fact})
    assert (wrong_company.status_code, wrong_company.json()["error"]["code"]) == (
        422,
        "source_mismatch",
    )
    states = {p["id"]: p["state"] for p in predictions.get("/api/v1/predictions")["items"]}
    assert set(states.values()) == {"open"}  # none was settled


def test_a_rejected_hypotheses_predictions_stay_listed(
    predictions: Predictions, llm: FakeLiteLLM
) -> None:
    hypothesis_id = draft(predictions, llm)
    publish(predictions, hypothesis_id)
    made = day_of(
        predictions.get(f"/api/v1/hypotheses/{hypothesis_id}")["versions"][0]["published_at"]
    )
    path = f"/api/v1/hypotheses/{hypothesis_id}/predictions"
    created = predictions.post(path, body(made, company_id=predictions.company()), status=201)

    moved = predictions.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/transitions", json={"to": "rejected"}
    )
    assert moved.status_code == 200, moved.text

    listed = predictions.get("/api/v1/predictions", hypothesis_status="rejected")
    assert [(p["id"], p["hypothesis_status"], p["state"]) for p in listed["items"]] == [
        (created["id"], "rejected", "open")
    ]
    assert predictions.get(path)["total"] == 1
    # Its call stays too: a record of what Atlas said.
    assert len(predictions.get("/api/v1/calls", origin="hypothesis")["items"]) == 1
