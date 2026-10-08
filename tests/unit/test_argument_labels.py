"""The standing regression set from the 0.5.3 argument-plan reviews (pilot-review tooling).

`labels.json` (built by `.scratch/tools/argument_labels.py` from the gitignored review
folders) holds Atlas's and the reviewers' own words about 853 Facts, the cards' statements
and counter-Facts, and no quote. `argument_regression.py` joins it with the local quotes and
runs Atlas's deterministic checks. The builder and the script are tested here on a synthetic
review folder (`tests/fixtures/pilot-0.5.3-argument/sample-review/`, invented text).
"""

import importlib.util
import json
import re
import shutil
import sys
from collections.abc import Callable, Iterator, Sequence
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, cast

import pytest
from pydantic import BaseModel, ConfigDict

from atlas.assertions import InvalidAssertion
from atlas.facts import service as facts_service

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "pilot-0.5.3-argument"
LABELS = FIXTURES / "labels.json"
SAMPLE = FIXTURES / "sample-review"
TOOLS = ROOT / ".scratch" / "tools"


def _tool(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


Verdict = Literal["right", "wrong", "off-question"]


class FactLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str
    investigation: int
    company: str | None
    step: str
    status: str
    statement: str
    quantity: dict[str, Any] | None
    period: str | None
    source_title: str | None
    verdict: Verdict
    by: Literal["both", "lead"]
    reason: str | None
    right_reading: str | None
    reviewer_a: str | None
    reviewer_b: str | None
    category: (
        Literal["status", "context_added", "merged", "period", "quantity", "misreading", "other"]
        | None
    )


class JudgeLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt: int | None
    verdict: str | None
    outcome: str | None
    kinds: list[str]


class StatementLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investigation: int
    step: str
    index: int
    text: str
    fact_ids: list[str]
    counter_fact_ids: list[str]
    trust_gate: Literal["pass", "fail"]
    misstatement: str | None
    saved_work: bool | None
    judge: list[JudgeLabel]


class CounterFactLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str
    investigation: int
    step: str | None
    on_step: str
    challenged_fact_ids: list[str]
    verdict: Verdict | None


class Labels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    note: str
    category_rules: list[dict[str, str]]
    facts: list[FactLabel]
    statements: list[StatementLabel]
    counter_facts: list[CounterFactLabel]
    totals: dict[str, dict[str, Any]]


# The reviewed counts (experiments.md, results.md), per investigation 1..5.
FACTS = [170, 188, 157, 138, 200]
RIGHT = [133, 138, 119, 103, 117]
WRONG = [26, 33, 27, 14, 25]
OFF_QUESTION = [11, 17, 11, 21, 58]
STATEMENTS = [34, 0, 30, 34, 32]
FAILING = [4, 0, 6, 2, 5]
COUNTER_FACTS = [12, 0, 12, 9, 17]
WRONG_BY_STATUS = [16, 24, 10, 3, 12]

# The first words of five Facts' quotes. None may appear anywhere in the labels.
QUOTE_SENTINELS = [
    "our datacom transceiver capacity expansion at our",
    "the tremendous growth in demand for indium",
    "for us, you know, growing revenue, meeting",
    "most of our products are not manufactured",
    "we expect those benefits to increase further",
]

MAX_TEXT = 600

needs_labels = pytest.mark.skipif(
    not LABELS.exists(), reason="labels.json is built by the lead from the local review folders"
)


def _every(_: Any) -> bool:
    return True


def _per_investigation(items: Sequence[Any], pick: Callable[[Any], bool] = _every) -> list[int]:
    return [sum(1 for i in items if i.investigation == n and pick(i)) for n in range(1, 6)]


def _has_verdict(verdict: str, fact: FactLabel) -> bool:
    return fact.verdict == verdict


def _fails_the_gate(statement: StatementLabel) -> bool:
    return statement.trust_gate == "fail"


def _wrong_on_status(fact: FactLabel) -> bool:
    return fact.verdict == "wrong" and fact.category == "status"


@needs_labels
def test_the_committed_labels_validate_and_pin_the_reviewed_counts() -> None:
    labels = Labels.model_validate_json(LABELS.read_text(encoding="utf-8"))

    assert _per_investigation(labels.facts) == FACTS
    for verdict, expected in (("right", RIGHT), ("wrong", WRONG), ("off-question", OFF_QUESTION)):
        assert _per_investigation(labels.facts, partial(_has_verdict, verdict)) == expected
    assert _per_investigation(labels.statements) == STATEMENTS
    assert _per_investigation(labels.statements, _fails_the_gate) == FAILING
    assert _per_investigation(labels.counter_facts) == COUNTER_FACTS
    assert _per_investigation(labels.facts, _wrong_on_status) == WRONG_BY_STATUS

    # Only a wrong Fact has a category; the totals block says what the lists say.
    assert all((f.category is not None) == (f.verdict == "wrong") for f in labels.facts)
    assert [labels.totals["facts"][str(n)] for n in range(1, 6)] == FACTS
    assert [labels.totals["counter_facts"][str(n)] for n in range(1, 6)] == COUNTER_FACTS

    # Every cited id is a Fact of the same investigation; every challenged id too.
    ids = {(f.investigation, f.fact_id) for f in labels.facts}
    assert len(ids) == len(labels.facts)
    counter_ids = {(c.investigation, c.fact_id) for c in labels.counter_facts}
    for statement in labels.statements:
        for fact_id in statement.fact_ids:
            assert (statement.investigation, fact_id) in ids
        for fact_id in statement.counter_fact_ids:
            assert (statement.investigation, fact_id) in counter_ids
    for counter in labels.counter_facts:
        for fact_id in counter.challenged_fact_ids:
            assert (counter.investigation, fact_id) in ids


@needs_labels
def test_the_labels_hold_no_quote_text() -> None:
    raw = LABELS.read_text(encoding="utf-8")
    labels = Labels.model_validate_json(raw)

    flat = re.sub(r"\s+", " ", raw.lower())
    for sentinel in QUOTE_SENTINELS:
        assert sentinel not in flat
    assert not any(key in raw for key in ('"quote"', '"context_before"', '"context_after"'))

    def strings(node: object) -> Iterator[str]:
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for value in cast("dict[str, object]", node).values():
                yield from strings(value)
        elif isinstance(node, list):
            for value in cast("list[object]", node):
                yield from strings(value)

    # Atlas's own statements run to about 550 characters; a quote's context would be longer.
    assert all(len(text) < MAX_TEXT for text in strings(json.loads(raw)))
    assert len(labels.facts) == sum(FACTS)


def test_the_builder_cuts_a_review_folder_into_labels_without_quotes() -> None:
    builder = _tool("argument_labels")
    f1, f2, f3 = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    )

    labels = Labels.model_validate(builder.build(SAMPLE))

    by_id = {f.fact_id: f for f in labels.facts}
    assert [f.fact_id for f in labels.facts] == [f1, f2, f3]
    right, wrong, off = by_id[f1], by_id[f2], by_id[f3]
    assert (right.investigation, right.company, right.step, right.status) == (
        1,
        "Acme Photonics",
        "constraint",
        "in_effect",
    )
    assert right.quantity == {"value": 40.0, "unit": "%", "metric": "laser capacity increase"}
    assert right.period == "this year"
    assert right.source_title == "Acme Q2 call"
    assert (right.verdict, right.by, right.category) == ("right", "both", None)
    assert right.reason == "Quote states both the sell-out and the 40% lift."
    assert (wrong.verdict, wrong.category) == ("wrong", "status")
    assert wrong.right_reading and wrong.right_reading.endswith("(planned).")
    assert wrong.source_title == "Acme Q2 call"
    # A lead's call with no reason keeps the reviewers' two verdicts.
    assert (off.verdict, off.by, off.reason) == ("off-question", "lead", None)
    assert (off.reviewer_a, off.reviewer_b) == ("off-question", "right")
    assert off.source_title == "Borealis filing"

    first, second = labels.statements
    assert (first.step, first.index, first.trust_gate, first.saved_work) == (
        "constraint",
        1,
        "pass",
        True,
    )
    assert first.fact_ids == [f1]
    assert first.counter_fact_ids == [f3]
    assert first.misstatement is None
    assert [(j.attempt, j.verdict, j.outcome) for j in first.judge] == [(1, "supported", "kept")]
    assert (second.step, second.index, second.trust_gate, second.saved_work) == (
        "relief",
        1,
        "fail",
        False,
    )
    assert second.misstatement == "Presents a next-quarter plan as done."
    assert [(j.attempt, j.verdict, j.kinds) for j in second.judge] == [
        (1, "misstated", ["tense"]),
        (2, "supported", []),
    ]

    (counter,) = labels.counter_facts
    assert (counter.fact_id, counter.step, counter.on_step) == (f3, "constraint", "constraint")
    assert counter.challenged_fact_ids == [f1]
    assert counter.verdict == "off-question"

    totals = labels.totals
    assert totals["facts"] == {"1": 3}
    assert totals["right"] == {"1": 1}
    assert totals["statements_failing"] == {"1": 1}
    assert totals["wrong_by_category"]["status"] == {"1": 1}

    # Neither the quotes nor any context text is in the output.
    raw = json.dumps(builder.build(SAMPLE))
    for compact in json.loads(
        (SAMPLE / "inv-1" / "review" / "facts-compact.json").read_text("utf-8")
    ):
        assert compact["quote"] not in raw
        assert compact["quote"][:30] not in raw
    assert '"quote"' not in raw


def test_the_builder_refuses_a_quote_that_slips_into_a_field(tmp_path: Path) -> None:
    builder = _tool("argument_labels")
    folder = tmp_path / "review"
    (folder / "inv-1").mkdir(parents=True)
    (folder / "inv-1" / "review").mkdir()
    for name in ("final-verdicts", "facts-compact", "workflow-result"):
        source = SAMPLE / "inv-1" / "review" / f"{name}.json"
        (folder / "inv-1" / "review" / f"{name}.json").write_text(
            source.read_text("utf-8"), "utf-8"
        )
    compact = json.loads((folder / "inv-1" / "review" / "facts-compact.json").read_text("utf-8"))
    compact[0]["statement"] = compact[0]["quote"]  # a Fact whose statement is its quote
    (folder / "inv-1" / "review" / "facts-compact.json").write_text(json.dumps(compact), "utf-8")
    (folder / "inv-1" / "investigation.json").write_text(
        (SAMPLE / "inv-1" / "investigation.json").read_text("utf-8"), "utf-8"
    )

    with pytest.raises(AssertionError, match="a quote slipped"):
        builder.build(folder)


@pytest.mark.parametrize(
    ("reason", "category"),
    [
        ("Quote is future tense ('will be'), unlike its sibling Fact marked planned.", "status"),
        ("Merges two facts. The timing comes from the context, not the quote.", "merged"),
        ("The second-half timing comes from the context after the quote.", "context_added"),
        ("Wrong period: the 8-K filed 2023-08-16 reports Q4 FY2023.", "period"),
        ("quantity collapses the $20-25M range to 25", "quantity"),
        ("In context, 'it' is gross margin, which refers to something else.", "misreading"),
        ("Nothing to match here.", "other"),
        (None, "other"),
    ],
)
def test_the_category_of_a_reason_is_its_first_keyword_match(
    reason: str | None, category: str
) -> None:
    assert _tool("argument_labels").categorise(reason) == category


def _sample_labels(tmp_path: Path) -> Path:
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(_tool("argument_labels").build(SAMPLE)), "utf-8")
    return path


def test_the_regression_script_reports_each_check_and_exits_nonzero_on_a_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _tool("argument_regression")
    labels = _sample_labels(tmp_path)
    arguments = ["--data", str(SAMPLE), "--labels", str(labels)]

    # As the code stands: check_quantity and the references rule accept the right Fact.
    assert script.main(arguments) == 0
    table = capsys.readouterr().out
    assert "check_quantity" in table
    assert "ungrounded" in table
    assert "without_references" in table
    assert "REGRESSION" not in table
    assert script.main([*arguments, "--max-right", "0"]) == 0
    capsys.readouterr()

    # A check that refuses everything refuses the right Fact with a quantity.
    def refuse_all(*_: object, **__: object) -> None:
        raise InvalidAssertion("quantity_not_in_quote", "refused by the test")

    monkeypatch.setattr(facts_service, "check_quantity", refuse_all)
    assert script.main(arguments) == 1
    table = capsys.readouterr().out
    assert "REGRESSION" in table
    assert "right Facts refused: 1" in table
    assert script.main([*arguments, "--max-right", "1"]) == 0


def test_the_regression_script_flags_a_passing_statement_that_a_check_newly_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _tool("argument_regression")
    labels = _sample_labels(tmp_path)
    from atlas.investigations import grounding

    def flag_everything(statement: str, ground: object) -> list[str]:
        return ["everything"]

    monkeypatch.setattr(grounding, "ungrounded", flag_everything)

    arguments = ["--data", str(SAMPLE), "--labels", str(labels), "--max-pass-flagged"]
    assert script.main([*arguments, "0"]) == 1
    capsys.readouterr()
    # One passing statement flagged; the failing one is a catch, not a regression.
    assert script.main([*arguments, "1"]) == 0


def test_the_regression_check_pools_several_label_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _tool("argument_regression")
    single: dict[str, Any] = _tool("argument_labels").build(SAMPLE)
    folders: list[Path] = []
    for name in ("run-a", "run-b"):
        folder = tmp_path / name
        shutil.copytree(SAMPLE, folder)
        folders.append(folder)
    pooled_labels: list[Path] = []
    for name in ("labels-a.json", "labels-b.json"):
        path = tmp_path / name
        path.write_text(json.dumps(single), "utf-8")
        pooled_labels.append(path)

    arguments = [
        "--data",
        str(folders[0]),
        "--data",
        str(folders[1]),
        "--labels",
        str(pooled_labels[0]),
        "--labels",
        str(pooled_labels[1]),
    ]
    assert script.main(arguments) == 0
    table = capsys.readouterr().out
    assert f"runs: {pooled_labels[0]}, {pooled_labels[1]}" in table
    assert table.count("Facts (refused / tested)") == 1

    # One run alone and the pool of two: the tested counts double.
    assert script.main(["--data", str(folders[0]), "--labels", str(pooled_labels[0])]) == 0
    single_table = capsys.readouterr().out
    count = re.search(r"quantity\s+(\S+ / \d+)", single_table)
    pooled = re.search(r"quantity\s+(\S+ / \d+)", table)
    assert count and pooled
    single_tested = int(count.group(1).split("/")[1])
    assert int(pooled.group(1).split("/")[1]) == 2 * single_tested


def test_the_regression_script_skips_a_check_that_does_not_exist_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _tool("argument_regression")
    labels = _sample_labels(tmp_path)
    monkeypatch.delattr(facts_service, "check_status", raising=False)
    monkeypatch.delattr(facts_service, "check_quantity")

    assert script.main(["--data", str(SAMPLE), "--labels", str(labels)]) == 0

    output = capsys.readouterr().out
    assert re.search(r"check_status\s+skipped", output)
    assert re.search(r"check_quantity\s+skipped", output)
    assert "Step status replay: skipped" in output
