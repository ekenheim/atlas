"""The memory conformance check, rehearsed (memory-quality ticket 14): what CI runs, and what
`scripts/memory-conformance.sh --rehearse` runs.

Seam: the conformance driver (`tests/live/conformance.py`), which drives Atlas through its
worker, its job queue and `/api/v1`, against the recorded Hindsight fake (with derived memories)
and the TradingView fake, both on localhost, behind the same counting proxies a live run uses.
Every check either passes against the fake or reports `pending` with the ticket that builds its
behaviour; the run is written as `results.json` and `summary.md` (to
`ATLAS_CONFORMANCE_RESULTS_DIR` when the script sets it).
"""

import json
import os
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest

from atlas.claims import LAYER_TERMS
from atlas.companies import load_universe
from atlas.conformance import (
    CHECKS,
    BehaviourBank,
    Check,
    ConformanceReport,
    load_known_answers,
    run_known_answers,
)
from atlas.research.probes import load_probes
from tests.fakes.hindsight import BankFacts, RecordedHindsight
from tests.fakes.serve import Served, serve
from tests.fakes.tradingview import FakeTradingView
from tests.live.conformance import (
    PROBES,
    THEMES,
    Caps,
    conformance_settings,
    new_bank_id,
    run_behaviours,
)

REHEARSAL_ANSWERS = (
    Path(__file__).parents[1] / "fixtures" / "memory-conformance" / "known-answers.yaml"
)
TICKETS = {1: "03", 2: "04", 3: "04", 4: "05", 5: "06", 6: "07", 7: "08", 8: "09", 9: "10"}


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    fake.derive_recall_options()  # check 6: recency, prefer_observations, max_tokens
    fake.derive_chunks()  # check 7: each fact's chunk, at Hindsight's default chunk size
    return fake


@pytest.fixture
def tradingview() -> Iterator[Served]:
    with serve(FakeTradingView().handle) as served:
        yield served
        served.raise_errors()


class Rehearsal:
    """A conformance run's pieces against the fakes: settings, the proxies, the report."""

    def __init__(
        self,
        stack: ExitStack,
        database_url: str,
        tmp_path: Path,
        hindsight: Served,
        tradingview: Served,
        *,
        retain_cap: int = 10,
        strict: bool = False,
    ) -> None:
        self.caps = Caps.around(hindsight.url, retain_cap=retain_cap)
        stack.callback(self.caps.close)
        llm_served = stack.enter_context(serve(self.caps.llm.handle))
        self.caps.chain(llm_served.url)
        retains_served = stack.enter_context(serve(self.caps.retains.handle))
        self.bank_id = new_bank_id()
        self.settings = conformance_settings(
            database_url=database_url,
            workdir=tmp_path,
            hindsight_url=retains_served.url,
            hindsight_api_key=None,
            bank_id=self.bank_id,
            tradingview_url=tradingview.url,
            fast=True,
        )
        self.report = ConformanceReport(mode="rehearse", strict=strict)

    def run(self, **kwargs: Any) -> ConformanceReport:
        run_behaviours(
            self.report, self.settings, self.caps, settle_seconds=30, poll_seconds=0.05, **kwargs
        )
        return self.report


def stand_in_for_hindsight_s_llm(fake: RecordedHindsight, bank: BehaviourBank) -> None:
    """What Hindsight's LLM makes of the bank on a live run, which the fake can't: through the
    fake's derivations the feature tickets added, each section's fact is labelled with the
    layers its text names (`script_fact_labels`, ticket 05), the consolidation leaves one
    observation in the theme's scope drawn from a section of each company
    (`derive_observation(scope=)`, ticket 06), and the reflect and each model's refresh cite
    the bank's facts (`script_reflect` with `BankFacts`, ticket 10; `script_refresh`)."""
    items = [item for batch in fake.retained(bank.bank_id) for item in batch]
    for item in items:
        content = str(item["content"]).lower()
        layers = [
            layer
            for layer, terms in LAYER_TERMS.items()
            if any(term.lower() in content for term in terms)
        ]
        fake.script_fact_labels(str(item["document_id"]), [f"layer:{layer}" for layer in layers])
    theme_tag = f"theme:{bank.theme}"
    first: dict[str, dict[str, Any]] = {}
    for item in items:
        for slug, company_id in bank.companies.items():
            if f"company:{company_id}" in item["tags"] and slug not in first:
                first[slug] = item
    (scope,) = [s for s in first[next(iter(first))]["observation_scopes"] if theme_tag in s]
    fake.derive_observation(
        [str(item["document_id"]) for item in first.values()], bank=bank.bank_id, scope=scope
    )
    fake.script_reflect("Coherent and Lumentum report constrained laser capacity.", [BankFacts()])
    for model in bank.template["mental_models"]:
        fake.script_refresh(
            str(model["id"]), "Constrained suppliers.", fake.bank_facts(bank.bank_id)
        )


def results_dir(tmp_path: Path) -> Path:
    configured = os.environ.get("ATLAS_CONFORMANCE_RESULTS_DIR")
    return Path(configured) if configured else tmp_path / "report"


def test_the_rehearsal_passes_or_reports_each_check_pending_with_its_ticket(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    tradingview: Served,
) -> None:
    fake = hindsight[0]
    universe = load_universe(THEMES)
    probes = load_probes(PROBES, universe)
    answers = load_known_answers(REHEARSAL_ANSWERS, universe, probes, min_answers=1)
    strict = os.environ.get("ATLAS_CONFORMANCE_STRICT") == "1"
    with ExitStack() as stack:
        rehearsal = Rehearsal(
            stack, database_url, tmp_path, hindsight[1], tradingview, strict=strict
        )

        def known_answers(bank: BehaviourBank) -> None:
            stand_in_for_hindsight_s_llm(fake, bank)
            rehearsal.report.known_answers = run_known_answers(bank.api, answers, probes)

        report = rehearsal.run(during=known_answers)
    report.write(results_dir(tmp_path))

    # The bank was prepared through the real retain path, then deleted.
    assert report.aborted is None
    assert report.bank_deleted is True
    assert fake.deleted_banks == [rehearsal.bank_id]
    assert fake.bank_documents(rehearsal.bank_id) == []
    assert report.usage.retain_operations == len(fake.retained())
    assert 0 < report.usage.retain_operations <= report.usage.retain_cap
    # The consolidation, check 9's reflect and its refresh of each of the two models.
    assert report.usage.llm_operations == 4

    # Each behaviour check passes, or is pending with the ticket that builds it.
    behaviours = report.behaviours or []
    assert [c.number for c in behaviours] == list(range(1, 11))
    # Tickets 03 to 10 are merged: no check is pending.
    assert [c.number for c in behaviours if c.verdict == "pending"] == []
    chunks = behaviours[6]
    assert chunks.verdict == "passed"
    assert chunks.evidence["facts"] == chunks.evidence["placed_by_chunk"]
    assert chunks.evidence["not_placed"] == [] and chunks.evidence["facts"] != 0
    for check in behaviours:
        assert check.promise and check.source
        if check.verdict == "pending":
            assert check.ticket == TICKETS[check.number]
            assert check.reason == f"pending: ticket {check.ticket}"
        else:
            assert check.verdict == "passed", (check.id, check.reason, check.evidence)
    citations = behaviours[9]
    assert citations.verdict == "passed"
    assert citations.evidence["by_state"] == {"resolved": citations.evidence["memories"]}

    # The known answers resolve against the fixtures and are all within the first 50.
    known = report.known_answers
    assert known is not None
    assert known.errors == []
    assert known.verdict == "passed", known.reason
    assert (known.overall.answers, known.overall.at_50) == (4, 1.0)
    assert known.anchors_found == {"coh-buys-inp-substrates": "part-i-item-1"}
    assert set(known.by_hop) == {
        "demand",
        "system",
        "module",
        "chip",
        "substrate",
        "feedstock",
        "equipment",
    }
    assert known.by_hop["chip"].answers == 2
    assert known.by_test_part["second_source"].answers == 2
    assert known.by_test_part["bom_share"].answers == 0

    # Pending fails nothing unless the run is strict.
    pending = [c for c in behaviours if c.verdict == "pending"]
    assert report.exit_code(strict=False) == 0
    assert report.exit_code(strict=True) == (1 if pending else 0)

    written = json.loads((results_dir(tmp_path) / "results.json").read_text(encoding="utf-8"))
    assert written["exit_code"] == report.exit_code()
    assert [c["verdict"] for c in written["behaviours"]] == [c.verdict for c in behaviours]
    summary = (results_dir(tmp_path) / "summary.md").read_text(encoding="utf-8")
    assert "### 10. citations-resolve" in summary
    assert "Promise: Every citation of a recall resolves; none is broken." in summary
    if strict:  # scripts/memory-conformance.sh --rehearse --strict: pending fails the run
        code = report.exit_code()
        assert code == 0, f"strict: pending {[c.id for c in pending]}, {report.failures()}"


def test_an_answer_whose_sentence_is_not_in_its_document_is_an_error_not_a_miss(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    tradingview: Served,
) -> None:
    universe = load_universe(THEMES)
    probes = load_probes(PROBES, universe)
    raw = REHEARSAL_ANSWERS.read_text(encoding="utf-8").replace(
        "and we commonly refer to them as raw materials.", "and we buy them from Atlantis."
    )
    wrong = tmp_path / "known-answers.yaml"
    wrong.write_text(raw, encoding="utf-8")
    answers = load_known_answers(wrong, universe, probes, min_answers=1)
    with ExitStack() as stack:
        rehearsal = Rehearsal(stack, database_url, tmp_path, hindsight[1], tradingview)

        def known_answers(bank: BehaviourBank) -> None:
            rehearsal.report.known_answers = run_known_answers(bank.api, answers, probes)

        report = rehearsal.run(during=known_answers, checks=[])

    known = report.known_answers
    assert known is not None
    assert [e.id for e in known.errors] == ["coh-buys-inp-substrates"]
    assert "the sentence is not in" in known.errors[0].error
    assert known.overall.answers == 3  # the error is not scored as a miss
    assert known.verdict == "failed"
    assert report.exit_code() == 1


def test_a_cap_aborts_the_run_and_the_bank_is_still_deleted(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    tradingview: Served,
) -> None:
    fake = hindsight[0]
    with ExitStack() as stack:
        rehearsal = Rehearsal(
            stack, database_url, tmp_path, hindsight[1], tradingview, retain_cap=1
        )
        report = rehearsal.run()

    assert report.aborted is not None and "cap" in report.aborted
    assert report.usage.retain_operations == 1
    assert report.usage.refused
    assert report.behaviours is None
    assert report.bank_deleted is True
    assert fake.deleted_banks == [rehearsal.bank_id]
    assert report.exit_code() == 1


def test_an_interrupt_still_deletes_the_bank(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    tradingview: Served,
) -> None:
    fake = hindsight[0]

    def interrupted(bank: BehaviourBank) -> tuple[bool, str | None, dict[str, Any]]:
        raise KeyboardInterrupt

    check = Check(1, "interrupted", None, "-", "-", lambda bank: True, interrupted)
    with ExitStack() as stack:
        rehearsal = Rehearsal(stack, database_url, tmp_path, hindsight[1], tradingview)
        with pytest.raises(KeyboardInterrupt):
            rehearsal.run(checks=[check])

    assert rehearsal.report.bank_deleted is True
    assert fake.deleted_banks == [rehearsal.bank_id]


def test_a_failing_check_fails_the_run(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    tradingview: Served,
) -> None:
    def broken(bank: BehaviourBank) -> tuple[bool, str | None, dict[str, Any]]:
        return False, "the promise does not hold", {"seen": 1}

    check = Check(1, "broken", None, "a promise", "a sentence", lambda bank: True, broken)
    with ExitStack() as stack:
        rehearsal = Rehearsal(stack, database_url, tmp_path, hindsight[1], tradingview)
        report = rehearsal.run(checks=[check])

    (result,) = report.behaviours or []
    assert (result.verdict, result.reason, result.evidence) == (
        "failed",
        "the promise does not hold",
        {"seen": 1},
    )
    assert report.exit_code() == 1
    assert report.bank_deleted is True


def test_check_1_runs_against_the_fake_once_its_behaviour_is_present(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    tradingview: Served,
) -> None:
    """Check 1 is pending until ticket 03 merges; with its gate lifted, it reads each section's
    outcome against its own document in the fake: every section completed and stored."""
    sections = CHECKS[0]
    present = Check(
        sections.number,
        sections.id,
        sections.ticket,
        sections.promise,
        sections.source,
        lambda bank: True,
        sections.run,
    )
    with ExitStack() as stack:
        rehearsal = Rehearsal(stack, database_url, tmp_path, hindsight[1], tradingview)
        report = rehearsal.run(checks=[present])

    (result,) = report.behaviours or []
    assert result.verdict == "passed", (result.reason, result.evidence)
    evidence = result.evidence
    assert evidence["by_state"] == {"completed": evidence["sections"]}
    assert evidence["unaccounted"] == []
