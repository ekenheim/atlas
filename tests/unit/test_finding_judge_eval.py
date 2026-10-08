"""The finding judge's eval over the argument statements (pilot 0.5.3, fix T2): the labels
builder (`.scratch/tools/argument_statement_labels.py`) and the eval's requests
(`.scratch/tools/finding_judge_eval.py --argument --dry-run`), on a synthetic pilot directory.

Seam: the two scripts' entry points (`main`) and the eval's request builder, loaded from their
files. The cards, labels and quotes are synthetic, shaped like 0.5.3's; none is production
text, and nothing is called.
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from tests.harness import REPO

TOOLS = REPO / ".scratch" / "tools"
QUESTION = "Is InP laser capacity the constraint on AI optics, and who gains?"
PLANNED = "We plan to double our indium phosphide capacity by the end of 2027."
CUSTOMERS = "Customers are starting to recognize there will not be enough capacity for everybody."
REPORTED = "We shipped 1.6T modules to our largest hyperscale customer in the quarter."


def tool(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fact(
    fact_id: str, status: str, statement: str, quote: str, quantity: Any = None
) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "company_id": "c0",
        "company_name": "Zephyr Optics",
        "step": "relief",
        "status": status,
        "statement": statement,
        "quantity": quantity,
        "period": "by the end of 2027" if status == "planned" else None,
        "source_title": "Zephyr Optics Q3 2026 call",
        "source_span": {
            "claim_id": fact_id,
            "source_version_id": "v1",
            "span_start": 100,
            "span_end": 100 + len(quote),
            "quote": quote,
        },
        "against": [],
    }


def pilot(root: Path) -> Path:
    """Two investigations: one card of two steps (three statements, one failing), and one
    with no card (skipped)."""
    planned = fact(
        "f1",
        "planned",
        "Zephyr plans to double its InP capacity by the end of 2027.",
        PLANNED,
        {"value": 2.0, "unit": "x", "metric": "InP capacity"},
    )
    customers = fact("f2", "in_effect", "Customers see too little capacity.", CUSTOMERS)
    shipped = fact("f3", "in_effect", "Zephyr shipped 1.6T modules.", REPORTED)
    card = {
        "steps": [
            {
                "step": "relief",
                "statements": [
                    {
                        "statement": "Zephyr has doubled its InP capacity.",
                        "facts": [planned],
                        "counterevidence": [customers],
                    },
                    {
                        "statement": "Zephyr plans to double its InP capacity by 2027.",
                        "facts": [planned],
                        "counterevidence": [],
                    },
                ],
            },
            {
                "step": "capture",
                "statements": [
                    {
                        "statement": "Zephyr shipped 1.6T modules to its largest customer.",
                        "facts": [shipped],
                        "counterevidence": [],
                    }
                ],
            },
        ]
    }
    review = {
        "card": {
            "statements": [
                {
                    "step": "relief",
                    "index": 1,
                    "trust_gate": "fail",
                    "misstatement": "A plan written as done.",
                },
                {"step": "relief", "index": 2, "trust_gate": "pass"},
                {"step": "capture", "index": 1, "trust_gate": "pass"},
            ]
        }
    }
    directory = root / "pilot-arg"
    (directory / "inv-1" / "review").mkdir(parents=True)
    (directory / "inv-2").mkdir()
    (directory / "inv-1" / "investigation.json").write_text(
        json.dumps({"question": QUESTION, "research_card": card}), "utf-8"
    )
    (directory / "inv-1" / "review" / "workflow-result.json").write_text(
        json.dumps(review), "utf-8"
    )
    (directory / "inv-2" / "investigation.json").write_text(
        json.dumps({"question": "no card", "research_card": None}), "utf-8"
    )
    return directory


def test_the_labels_builder_writes_each_card_statement_with_its_label_and_facts(
    tmp_path: Path,
) -> None:
    directory = pilot(tmp_path)

    assert tool("argument_statement_labels").main(["--pilot", str(directory)]) == 0

    entries = json.loads((directory / "labeled-statements.json").read_text("utf-8"))
    assert [(e["investigation"], e["step"], e["index"], e["trust_gate"]) for e in entries] == [
        (1, "relief", 1, "fail"),
        (1, "relief", 2, "pass"),
        (1, "capture", 1, "pass"),
    ]
    first = entries[0]
    assert (first["question"], first["misstatement"]) == (QUESTION, "A plan written as done.")
    assert [(f["kind"], f["status"], f["quote"]) for f in first["facts"]] == [
        ("fact", "planned", PLANNED),
        ("counter", "in_effect", CUSTOMERS),
    ]
    assert first["facts"][0]["quantity"] == "2.0 x (InP capacity)"
    assert first["facts"][0]["period"] == "by the end of 2027"


def test_the_eval_builds_one_request_per_labelled_statement_with_each_fact_s_reading(
    tmp_path: Path,
) -> None:
    directory = pilot(tmp_path)
    tool("argument_statement_labels").main(["--pilot", str(directory)])
    labels = directory / "labeled-statements.json"
    evaluate = tool("finding_judge_eval")

    built = evaluate.requests(evaluate.labelled_rows(labels), argument=True, pilot=directory)

    assert len(built) == 3
    request, quotes = built[0]
    assert request.research_question == QUESTION
    assert request.finding.statement == "Zephyr has doubled its InP capacity."
    assert request.finding.claim_refs == ["c1", "c2"]
    sent = request.model_dump(mode="json")["claims"]
    assert [
        (c["ref"], c["predicate"], c["object"], c["status"], c["period"], c["quantity"])
        for c in sent
    ] == [
        ("c1", "fact", "", "planned", "by the end of 2027", "2.0 x (InP capacity)"),
        ("c2", "fact", "", "in_effect", None, None),
    ]
    assert sent[0]["reading"] == "Zephyr plans to double its InP capacity by the end of 2027."
    assert [(q.id, q.text, q.trust) for q in quotes] == [
        ("c1", PLANNED, "low"),
        ("c2", CUSTOMERS, "low"),
    ]

    # The dry run builds them all and calls nothing.
    out = tmp_path / "out"
    assert (
        evaluate.main(["--argument", "--dry-run", "--labels", str(labels), "--out", str(out)]) == 0
    )
    summary = json.loads((out / "result.json").read_text("utf-8"))["summary"]
    assert (summary["requests"], summary["calls"], summary["argument"]) == (3, 0, True)
    assert (summary["misstated_labelled"], summary["supported_labelled"]) == (1, 2)
