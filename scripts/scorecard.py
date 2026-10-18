"""The early-call scorecard's reader and reporter (atlas-beliefs ticket 29a; ticket 29).

The scorecard asks whether Atlas, reading only what was public on a past date, names a bottleneck
before the market priced it, and stays quiet where there was none. Each run is one isolated
Researcher session (`agent/run.sh researcher` with `ATLAS_AGENT_ISOLATED=true`), the lead's to
start. This script does the two things around the runs, over Atlas's API and nothing else (GETs
only; no model call, no write):

1. `sheets`: for each run in the runs file, reads the session's Beliefs (with their Facts' quotes
   and documents), Facts, card and recorded tool trace, writes the raw answers to `bundles/` and a
   **review sheet** to `sheets/`: the answer key's row for the case (what a hit states, from
   documents public by the as-of date), the session's Beliefs with their citations, space for a
   mark and a reason, and a summary of the trace (what it searched and read, its Facts by the month
   their documents became public, what Atlas refused it). A sheet holds **no price, no priced date,
   no closed-book verdict and no code rank**: the reviewers see the key and the Beliefs only.
2. `report`: from the stored bundles, the runs file (the lead's closed-book verdicts and code
   ranks; the code's within-company rank and pooled percentile may come from a code-readings
   file instead) and the reviewers' marks file, writes `report.md` and `results.json`: per run
   the raw hit, the closed-book verdict and the code's rank side by side (no composite score),
   the hits of the positive runs, the false positives of the negative runs, the lead time in
   days of the earliest as-of that hit, the misses by class (M1 to M5, FP) and what the
   pre-registered rule chooses to build. Seven cases are no hit rate, and the report says so.

The key (`KEY`) is the answer key fixed on 2026-10-18 before any run, from
`docs/research/early-signal-case-studies.md`; nothing in it changes after the first run
(`.scratch/atlas-beliefs/issues/29-the-early-call-scorecard.md`, Amendment 1 holds the rules).

    uv run python scripts/scorecard.py sheets --runs runs.json --base-url http://localhost:8000
    uv run python scripts/scorecard.py report --runs runs.json --marks marks.json --bundles DIR \\
        [--code-readings readings.json]

The runs file::

    {"frozen": {"signal_scorer": "signals-v3", "agent_model": "claude-opus-5-5", ...},
     "runs": [{"case": "sandisk", "as_of": "2025-02-28", "session_id": "...",
               "configuration": {...},            # the same keys as `frozen`; a run that differs
                                                  # is flagged and not scored
               "closed_book": "stated|hedged|not_stated",
               "code_rank": 3,                    # within-company top-20 rank, null: not in it
               "code_pooled_percentile": 0.97,    # optional
               "fact_precision": 0.95, "trust_gate": 0.05,    # optional guardrails
               "result_file": "out/claude-result.json",       # optional (ticket 29b): read for its
                                                  # `permission_denials`, reported; a path from
                                                  # the runs file's folder
               "started_at": "2026-10-20T05:00:00Z",          # optional, together; a fallback only:
               "finished_at": "2026-10-20T05:30:00Z"}],       # the window is the session's own
                                                  # created time to its close (else its last
                                                  # tool call), from Atlas; the other sessions
                                                  # created inside are listed for the lead
     "not_run": [{"case": "raspberry-pi", "reason": "no documents reachable"}]}

The marks file (the reviewers', then the lead's)::

    {"marks": [{"run": "sandisk@2025-02-28", "reviewer": "A", "belief_id": "...",
                "mark": "hit|miss|false_positive", "reason": "one line"}],
     "adjudications": [{"run": "...", "belief_marks": {"<belief id>": "hit"},
                        "outcome": "hit|miss|false_positive|clean",  # optional override
                        "miss_class": "M1".."M5" | "FP", "reason": "..."}]}
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

REPO = Path(__file__).resolve().parents[1]

type Kind = Literal["positive", "calibration", "negative", "squeezed_buyer"]
type Get = Callable[..., Any]  # (path, **params) -> the decoded JSON answer of a GET


@dataclass(frozen=True)
class Case:
    id: str
    name: str
    slug: str | None  # the company in Atlas's universe (None: not an SEC filer, no company yet)
    kind: Kind
    as_of_dates: tuple[str, ...]
    hit_text: str  # what a hit states, from documents public by the as-of date
    priced: str | None  # the date the lead time runs to
    in_sample: bool = False  # the code's vocabulary was written from this case

    @property
    def scored(self) -> bool:
        return self.kind != "calibration"

    @property
    def positive(self) -> bool:
        return self.kind in ("positive", "squeezed_buyer")


# The answer key, fixed 2026-10-18 before any run (ticket 29, "The answer key").
KEY: dict[str, Case] = {
    case.id: case
    for case in (
        Case(
            "sandisk",
            "SanDisk (NAND)",
            "sandisk",
            "positive",
            ("2025-02-28", "2025-05-31", "2025-08-31"),
            "NAND undersupply that the suppliers chose (utilisation cut while profitable),"
            " forecast by the company to last; price increases",
            "2025-09-10",
            in_sample=True,
        ),
        Case(
            "iren",
            "IREN (grid power)",
            "iren",
            "positive",
            ("2025-03-31", "2025-05-31"),
            "Grid power for AI data centres is short; connections take years; IREN holds"
            " secured power",
            "2025-08-28",
        ),
        Case(
            "axt",
            "AXT (InP), calibration, not scored",
            "axt",
            "calibration",
            ("2025-08-31",),
            "InP substrates short, two suppliers, export permits the gate",
            "2025-10-30",
            in_sample=True,
        ),
        Case(
            "etoro",
            "eToro (negative)",
            "etoro",
            "negative",
            ("2025-09-30",),
            "No bottleneck: activity follows volatility",
            None,
        ),
        Case(
            "snap",
            "Snap (negative, inverse)",
            "snap",
            "negative",
            ("2025-08-31",),
            "No bottleneck: ad inventory outgrows demand, prices falling",
            None,
        ),
        Case(
            "poet",
            "POET (negative, photonics)",
            "poet-technologies",
            "negative",
            ("2025-11-30",),
            "No bottleneck: capacity meets demand, ramp slipping, equity-financed",
            None,
        ),
        Case(
            "raspberry-pi",
            "Raspberry Pi (squeezed buyer)",
            None,
            "squeezed_buyer",
            ("2025-10-31",),
            "Squeezed by a DRAM shortage (the cost side), not a holder of one",
            "2026-03-31",
        ),
    )
}

QUESTION = (
    "As of {date}, does anything constrain supply in {company}'s market, who holds it,"
    " and what would relieve it?"
)
CLOSED_BOOK = ("stated", "hedged", "not_stated")
MARKS = ("hit", "miss", "false_positive")
OUTCOMES = ("hit", "miss", "false_positive", "clean")
MISS_CLASSES = ("M1", "M2", "M3", "M4", "M5", "FP")
MISS_CLASS_MEANING = {
    "M1": "the key's document is not in the archive (intake)",
    "M2": "in the archive, never surfaced (signal vocabulary or search)",
    "M3": "read, not recorded as a Fact (skill)",
    "M4": "recorded, but in no Belief or under the wrong step (predicate and step model)",
    "M5": "the Belief misstated (judge)",
    "FP": "a supply constraint the company holds, found on a negative (discipline, Skeptic)",
}
FACT_PRECISION_FLOOR = 0.92
TRUST_GATE_CEILING = 0.10
CODE_TOP = 20
# The twelve Atlas tools an isolated run is allowed (`agent/run.sh`'s `isolated_tools`; a unit test
# keeps the two the same) and the actor run.sh opens its session with.
ISOLATED_TOOLS = (
    "close_session",
    "companies",
    "search",
    "read",
    "locate",
    "record_fact",
    "get_fact",
    "judge_statement",
    "relate_facts",
    "propose_belief",
    "cite_belief",
    "recall",
)
RESEARCHER_ACTOR = "atlas-researcher"


class ScorecardError(ValueError):
    """A runs file, marks file or bundle that does not fit what the scorecard needs."""


# --- the runs ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Run:
    case: str
    as_of: str
    session_id: str
    configuration: dict[str, Any]
    closed_book: str | None
    code_read: bool  # the code's reading is in the file (code_rank may still be null)
    code_rank: int | None
    code_pooled_percentile: float | None
    fact_precision: float | None
    trust_gate: float | None
    # Ticket 29b: where run.sh left claude's result (its `permission_denials`), and the run's
    # window (run.sh's log line: `started_at`, `finished_at`, UTC) to find other sessions in.
    result_file: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def label(self) -> str:
        return f"{self.case}@{self.as_of}"


@dataclass(frozen=True)
class Runs:
    frozen: dict[str, Any]
    runs: tuple[Run, ...]
    not_run: dict[str, str]  # case id -> why


def _object(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScorecardError(f"{what} must be a JSON object")
    return cast(dict[str, Any], value)


def _list(value: Any, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise ScorecardError(f"{what} must be a JSON list")
    return cast(list[Any], value)


def _instant(value: str) -> datetime:
    """A time with an offset (a `Z` is UTC), as Atlas and run.sh write them."""
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as error:
        raise ScorecardError(f"{value!r} is not an ISO time") from error
    if moment.tzinfo is None:
        raise ScorecardError(f"{value!r} has no offset")
    return moment


def _optional_text(row: dict[str, Any], key: str, what: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ScorecardError(f"{what}: {key} must be a non-empty string or null")
    return value


def _optional_number(row: dict[str, Any], key: str, what: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ScorecardError(f"{what}: {key} must be a number or null")
    return float(value)


def parse_runs(document: Any) -> Runs:
    """The runs file, checked against the key: a known case, one of its as-of dates, each once."""
    top = _object(document, "the runs file")
    runs: list[Run] = []
    seen: set[str] = set()
    for index, item in enumerate(_list(top.get("runs", []), "runs")):
        row = _object(item, f"run {index}")
        case_id = str(row.get("case"))
        if case_id not in KEY:
            raise ScorecardError(f"run {index}: no such case {case_id!r} ({', '.join(KEY)})")
        as_of = str(row.get("as_of"))
        if as_of not in KEY[case_id].as_of_dates:
            raise ScorecardError(
                f"run {index}: {case_id} is run as of {', '.join(KEY[case_id].as_of_dates)},"
                f" not {as_of!r}"
            )
        session_id = row.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ScorecardError(f"run {index}: session_id is missing")
        closed_book = row.get("closed_book")
        if closed_book is not None and closed_book not in CLOSED_BOOK:
            raise ScorecardError(f"run {index}: closed_book is one of {', '.join(CLOSED_BOOK)}")
        rank = row.get("code_rank")
        if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int) or rank < 1):
            raise ScorecardError(f"run {index}: code_rank is a rank from 1 or null")
        label = f"{case_id}@{as_of}"
        if label in seen:
            raise ScorecardError(f"run {index}: {label} is listed twice")
        seen.add(label)
        what = f"run {label}"
        started_at = _optional_text(row, "started_at", what)
        finished_at = _optional_text(row, "finished_at", what)
        if (started_at is None) != (finished_at is None):
            raise ScorecardError(f"{what}: started_at and finished_at come together")
        if started_at is not None and finished_at is not None:
            if _instant(finished_at) < _instant(started_at):
                raise ScorecardError(f"{what}: finished_at is before started_at")
        runs.append(
            Run(
                case=case_id,
                as_of=as_of,
                session_id=session_id,
                configuration=_object(row.get("configuration", {}), f"{what} configuration"),
                closed_book=cast("str | None", closed_book),
                code_read="code_rank" in row,
                code_rank=rank,
                code_pooled_percentile=_optional_number(row, "code_pooled_percentile", what),
                fact_precision=_optional_number(row, "fact_precision", what),
                trust_gate=_optional_number(row, "trust_gate", what),
                result_file=_optional_text(row, "result_file", what),
                started_at=started_at,
                finished_at=finished_at,
            )
        )
    not_run: dict[str, str] = {}
    for item in _list(top.get("not_run", []), "not_run"):
        row = _object(item, "a not_run entry")
        case_id = str(row.get("case"))
        if case_id not in KEY:
            raise ScorecardError(f"not_run: no such case {case_id!r}")
        reason = str(row.get("reason") or "").strip()
        if not reason:
            raise ScorecardError(f"not_run: {case_id} needs a reason")
        not_run[case_id] = reason
    return Runs(_object(top.get("frozen", {}), "frozen"), tuple(runs), not_run)


def apply_code_readings(runs: Runs, readings: Any) -> Runs:
    """The code's readings (`scripts/signal_replay.py`, committed by the lead before any session)
    laid over the runs: `{"<case>@<as-of>": {"rank": 3 | null, "pooled_percentile": 0.97}}`,
    the within-company rank among the company's top 20 and the pooled percentile across the
    universe (k = 20, `--since` 365 days before the as-of date; Amendment 1), both reported
    beside the session's reading and never combined with it. A reading for a run that is not in
    the file is refused."""
    table = _object(readings, "the code readings")
    labels = {run.label for run in runs.runs}
    for label in table:
        if label not in labels:
            raise ScorecardError(f"code readings: {label!r} is not a run in the runs file")
    updated: list[Run] = []
    for run in runs.runs:
        if run.label not in table:
            updated.append(run)
            continue
        reading = _object(table[run.label], f"code reading {run.label}")
        rank = reading.get("rank")
        if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int) or rank < 1):
            raise ScorecardError(f"code reading {run.label}: rank is a rank from 1 or null")
        pooled = _optional_number(reading, "pooled_percentile", f"code reading {run.label}")
        if pooled is not None and not 0 <= pooled <= 1:
            raise ScorecardError(f"code reading {run.label}: pooled_percentile is from 0 to 1")
        updated.append(
            replace(
                run,
                code_read="rank" in reading or run.code_read,
                code_rank=rank if "rank" in reading else run.code_rank,
                code_pooled_percentile=pooled
                if "pooled_percentile" in reading
                else run.code_pooled_percentile,
            )
        )
    return Runs(runs.frozen, tuple(updated), runs.not_run)


def coverage(runs: Runs) -> list[dict[str, str]]:
    """Every case at every as-of date: run, reported not run with its reason, or missing."""
    have = {run.label for run in runs.runs}
    rows: list[dict[str, str]] = []
    for case in KEY.values():
        for as_of in case.as_of_dates:
            label = f"{case.id}@{as_of}"
            if label in have:
                rows.append({"run": label, "status": "run"})
            elif case.id in runs.not_run:
                rows.append({"run": label, "status": "not run", "reason": runs.not_run[case.id]})
            else:
                rows.append({"run": label, "status": "missing"})
    return rows


def off_configuration(runs: Runs, run: Run) -> list[str]:
    """The frozen settings this run's recorded configuration does not match (a key it leaves
    out counts): a run on another configuration is flagged and not scored."""
    return [
        key
        for key, wanted in runs.frozen.items()
        if key not in run.configuration or run.configuration[key] != wanted
    ]


# --- reading a run through the API -------------------------------------------------------------

PAGE = 500
# run.sh takes its two timestamps to the second, the end rounded down: a session opened in the
# second after `finished_at` is still in the window.
WINDOW_SLACK = timedelta(seconds=1)


def permission_denials(run: Run, base: Path | None) -> dict[str, Any] | None:
    """The `permission_denials` of the run's `claude-result.json` (ticket 29b, L4): how many calls
    Claude Code refused the agent and which tools they named. None when the runs file names no
    result file; a file it names that cannot be read is an error, not a silent zero. A result
    without the key reports `count` null: the run did not say."""
    if run.result_file is None:
        return None
    path = Path(run.result_file)
    if base is not None and not path.is_absolute():
        path = base / path
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ScorecardError(f"{run.label}: cannot read the result file {path}: {error}") from error
    document = _object(result, f"{run.label}: the result file")
    if "permission_denials" not in document:
        return {"count": None, "tools": []}
    denials = _list(document["permission_denials"], f"{run.label}: permission_denials")
    tools = sorted(
        {str(_object(each, "a permission denial").get("tool_name", "?")) for each in denials}
    )
    return {"count": len(denials), "tools": tools}


def run_window(run: Run, session: dict[str, Any], trace: list[Any]) -> dict[str, str] | None:
    """The run's window, from Atlas's own record and not the pod's clock (ticket 29b): it starts
    when the run's session was created and ends when the session was closed, else at its last
    recorded tool call. Only a time Atlas lacks is taken from the runs file (`started_at`,
    `finished_at`, the end a second late because run.sh takes it to the second). None when
    neither has one."""
    start = session.get("started_at") or run.started_at
    end = session.get("finished_at")
    source = "session closed"
    if end is None and trace:
        end = max((str(_object(call, "a tool call")["at"]) for call in trace), key=_instant)
        source = "last tool call"
    if end is None and run.finished_at is not None:
        end = (_instant(run.finished_at) + WINDOW_SLACK).isoformat()
        source = "runs file"
    if start is None or end is None:
        return None
    return {"start": str(start), "end": str(end), "source": source}


def sessions_in_window(get: Get, window: dict[str, str], own_id: str) -> list[dict[str, Any]]:
    """Every OTHER Atlas session created inside the run's window (ticket 29b, N1): the run's
    session is opened by run.sh, so these are unrelated sessions (another agent's, the lead's), and
    the lead decides whether any of them touched the run."""
    start = _instant(window["start"])
    end = _instant(window["end"])
    found: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = _object(get("/sessions", limit=PAGE, offset=offset), "the sessions")
        items = _list(page.get("items"), "the sessions")
        for item in items:
            session = _object(item, "a session")
            if str(session["id"]) == own_id:
                continue
            if start <= _instant(str(session["started_at"])) <= end:
                found.append(
                    {
                        key: session.get(key)
                        for key in ("id", "started_at", "isolated", "actor", "theme", "question")
                    }
                )
        offset += len(items)
        if not items or offset >= int(page.get("total", 0)):
            break
    return found


def collect_bundle(get: Get, run: Run, base: Path | None = None) -> dict[str, Any]:
    """Everything the scorecard reads of one run, as Atlas answered it: the session (its Facts and
    card), its tool trace, its Beliefs in full and the day each cited or recorded document became
    public, the permission denials of its result file (`base`: where a relative path is read from)
    and the other sessions opened in its window. `get(path, **params)` is a GET of `/api/v1`; the
    tests hand in recorded answers."""
    session = _object(get(f"/sessions/{run.session_id}"), "the session")
    trace = _list(get(f"/sessions/{run.session_id}/tool-calls"), "the tool trace")
    beliefs: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = _object(
            get("/beliefs", theme=session["theme"], limit=PAGE, offset=offset), "the beliefs"
        )
        items = _list(page.get("items"), "the beliefs")
        for item in items:
            summary = _object(item, "a Belief")
            if summary.get("produced_by") == run.session_id:
                beliefs.append(_object(get(f"/beliefs/{summary['id']}"), "a Belief"))
        offset += len(items)
        if not items or offset >= int(page.get("total", 0)):
            break
    dates: dict[str, str] = {}
    for belief in beliefs:
        for citation in _list(belief.get("citations", []), "citations"):
            row = _object(citation, "a citation")
            dates[str(row["source_version_id"])] = str(row["available_at"])
    for fact in _list(session.get("fact_items", []), "the Facts"):
        version = str(
            _object(_object(fact, "a Fact")["assertion"], "an Assertion")["source_version_id"]
        )
        if version not in dates:
            dates[version] = str(
                _object(get(f"/source-versions/{version}"), "a version")["available_at"]
            )
    window = run_window(run, session, trace)
    return {
        "run": run.label,
        "session": session,
        "tool_calls": trace,
        "beliefs": beliefs,
        "version_dates": dates,
        "permission_denials": permission_denials(run, base),
        "window": window,
        "other_sessions_in_window": (
            None if window is None else sessions_in_window(get, window, run.session_id)
        ),
    }


# --- the trace ---------------------------------------------------------------------------------


def trace_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    """What the session did, from Atlas's own record of its calls and the Facts it recorded:
    calls by tool and outcome, what Atlas refused it, the searches, the distinct documents read,
    and its Facts by the month their documents became public."""
    calls = [_object(each, "a tool call") for each in _list(bundle["tool_calls"], "tool calls")]
    by_tool = Counter(str(call["tool"]) for call in calls)
    outcomes = Counter(str(call["outcome"]) for call in calls)
    refusals = Counter(str(call["reason"]) for call in calls if call["outcome"] != "ok")
    searches: list[str] = []
    read_versions: set[str] = set()
    for call in calls:
        arguments = _object(call.get("arguments", {}), "arguments")
        if call["tool"] == "search" and call["outcome"] == "ok":
            searches.append(f"{arguments.get('company', '?')}: {arguments.get('q', '')}")
        if call["tool"] == "read" and call["outcome"] == "ok" and "version_id" in arguments:
            read_versions.add(str(arguments["version_id"]))
    dates = _object(bundle["version_dates"], "version dates")
    months: Counter[str] = Counter()
    session = _object(bundle["session"], "the session")
    for fact in _list(session.get("fact_items", []), "the Facts"):
        version = str(
            _object(_object(fact, "a Fact")["assertion"], "an Assertion")["source_version_id"]
        )
        months[str(dates.get(version, "unknown"))[:7]] += 1
    return {
        "calls": len(calls),
        "by_tool": dict(sorted(by_tool.items())),
        "by_outcome": dict(sorted(outcomes.items())),
        "refusals": dict(sorted(refusals.items())),
        "searches": searches,
        "documents_read": len(read_versions),
        "facts": sum(months.values()),
        "facts_by_document_month": dict(sorted(months.items())),
    }


def foreign_citations(bundle: dict[str, Any]) -> list[dict[str, str]]:
    """The citations of the run's Beliefs that are not of a Fact the run's own session recorded
    (another session's Fact, or an Assertion): an isolated session may cite only its own, so
    each is a leak or a bug and the reviewer is told."""
    session = _object(bundle["session"], "the session")
    own = {
        str(_object(fact, "a Fact")["id"]) for fact in _list(session.get("fact_items", []), "Facts")
    }
    found: list[dict[str, str]] = []
    for belief in _list(bundle["beliefs"], "Beliefs"):
        row = _object(belief, "a Belief")
        for citation in _list(row.get("citations", []), "citations"):
            cited = _object(citation, "a citation")
            if cited.get("kind") != "fact" or str(cited["ref_id"]) not in own:
                found.append({"belief_id": str(row["id"]), "ref_id": str(cited["ref_id"])})
    return found


# --- the review sheet --------------------------------------------------------------------------


def review_sheet(run: Run, bundle: dict[str, Any]) -> str:
    """The sheet a blind reviewer marks: the key's row for the case, the session's Beliefs with
    their citations, and the trace. No price, priced date, closed-book verdict or code rank."""
    case = KEY[run.case]
    session = _object(bundle["session"], "the session")
    lines = [
        f"# Review sheet: {case.name}, as of {run.as_of}",
        "",
        f"Run: `{run.label}`",
        f"Question: {QUESTION.format(date=run.as_of, company=case.name.split(' (')[0])}",
        "",
        "## The key",
        "",
        f"- Case kind: {case.kind.replace('_', ' ')}",
        f"- A hit states: {case.hit_text}",
        "",
        "Mark each Belief below, from its statement and the Facts it cites alone:",
        "",
        "- `hit`: the Belief states the key's bottleneck, and its cited Facts, from documents"
        " public by the as-of date, carry it. A statement no cited Fact carries is not scored.",
        "- `miss`: it does not (for a negative: it states no supply constraint the company holds).",
        "- `false_positive`: a negative's Belief that states a supply constraint the company"
        " holds.",
        "",
        "Give each mark one line of reason. Do not look anything up: the key and the Beliefs are"
        " all you are given.",
        "",
        f"## The session's Beliefs ({len(_list(bundle['beliefs'], 'Beliefs'))})",
        "",
    ]
    beliefs = [_object(each, "a Belief") for each in _list(bundle["beliefs"], "Beliefs")]
    foreign = foreign_citations(bundle)
    strangers = {each["ref_id"] for each in foreign}
    if foreign:
        lines += [
            f"WARNING: {len(foreign)} citation(s) below are of a Fact the run's own session did"
            " not record. An isolated session may cite only its own Facts: flag the run.",
            "",
        ]
    if not beliefs:
        lines += [
            "The session proposed no Belief. The run is a miss unless the card says otherwise.",
            "",
        ]
    for number, belief in enumerate(beliefs, 1):
        companies = ", ".join(
            str(c.get("display_name", c.get("name", "?"))) for c in belief["companies"]
        )
        lines += [
            f"### Belief {number}: `{belief['id']}`",
            "",
            f"- Statement: {belief['statement']}",
            f"- Step: {belief['step']}; companies: {companies or 'none named'}",
            f"- As of: {belief['as_of']}",
            "- Citations:",
        ]
        for citation in _list(belief.get("citations", []), "citations"):
            row = _object(citation, "a citation")
            lines += [
                f"  - valence {row['valence']:+g}, {row['weight']}: {row.get('statement') or ''}",
                f'    quote: "{row["quote"]}"',
                f"    document: {row.get('source_title') or '(untitled)'},"
                f" public {str(row['available_at'])[:10]}",
            ]
            if str(row["ref_id"]) in strangers:
                lines.append(
                    "    WARNING: this Fact was not recorded in the run's own session"
                    " (another session's, or not a Fact): flag it"
                )
        lines += ["", "- Mark: ____   (hit / miss / false_positive)", "- Reason: ____", ""]
    card = session.get("card_markdown")
    lines += [
        "## The session's card",
        "",
        "What the session wrote down as its answer (read it beside the Beliefs; a Belief is"
        " marked on its own Facts, not on the card):",
        "",
        *(
            [f"> {line}" for line in str(card).splitlines()]
            if isinstance(card, str) and card.strip()
            else ["The session wrote no card."]
        ),
        "",
    ]
    summary = trace_summary(bundle)
    lines += [
        "## Trace summary",
        "",
        f"- Isolated session: {'yes' if session.get('isolated') else 'NO (not scored: flag it)'}",
        f"- Permission denials: {_denials_text(bundle.get('permission_denials'))}",
        f"- Other sessions opened during the run: {_others_text(bundle)}",
        f"- Tool calls: {summary['calls']} ({_inline(summary['by_tool'])});"
        f" outcomes {_inline(summary['by_outcome'])}",
        f"- Atlas refused or failed: {_inline(summary['refusals']) or 'nothing'}",
        f"- Documents read: {summary['documents_read']}; Facts recorded: {summary['facts']}",
        f"- Facts by the month their documents became public: "
        f"{_inline(summary['facts_by_document_month']) or 'none'}",
        "- Searches:",
    ]
    lines += [f"  - {each}" for each in summary["searches"]] or ["  - none"]
    return "\n".join(lines) + "\n"


def _inline(counts: dict[str, int]) -> str:
    return ", ".join(f"{key} {value}" for key, value in counts.items())


def _denials_text(denials: Any) -> str:
    """The run's permission denials in a line: the count and the tools they named."""
    if denials is None:
        return "not recorded (the runs file names no result file)"
    row = _object(denials, "permission denials")
    if row["count"] is None:
        return "the result did not say"
    tools = ", ".join(str(each) for each in _list(row["tools"], "denied tools"))
    return f"{row['count']}" + (f" ({tools})" if row["count"] else "")


def _others_text(bundle: dict[str, Any]) -> str:
    """The other sessions Atlas created during the run's window, in a line."""
    others = bundle.get("other_sessions_in_window")
    if others is None:
        return "not checked: no window (not scored)"
    sessions = [_object(each, "a session") for each in _list(others, "other sessions")]
    if not sessions:
        return "none"
    return f"{len(sessions)}: {_others_list(sessions)} (the lead decides)"


def _others_list(sessions: Sequence[dict[str, Any]]) -> str:
    """Other sessions by id, actor, theme and whether they were isolated."""
    return ", ".join(
        f"{each['id']} (actor {each.get('actor')}, theme {each.get('theme')},"
        f" {'isolated' if each.get('isolated') else 'not isolated'})"
        for each in sessions
    )


# --- the marks ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunOutcome:
    run: str
    case: str
    outcome: str | None  # hit / miss / false_positive / clean / calibration; None: unsettled
    belief_marks: dict[str, str]
    unresolved: tuple[str, ...]  # Beliefs the reviewers disagreed on and no one adjudicated
    miss_class: str | None
    reason: str | None
    not_scored: str | None  # why the run is flagged and not scored


def resolve_run(
    run: Run,
    runs: Runs,
    bundle: dict[str, Any],
    marks: Sequence[dict[str, Any]],
    adjudication: dict[str, Any] | None,
) -> RunOutcome:
    """The run's outcome by the key: each Belief's mark where both reviewers agree (the lead's
    adjudicated mark where they do not), the run a hit when any Belief is, a miss otherwise; a
    negative's false positive is a Belief marked so. A run on another configuration, or one that
    was not an isolated session, is flagged and not scored."""
    case = KEY[run.case]
    beliefs = [str(_object(each, "a Belief")["id"]) for each in _list(bundle["beliefs"], "Beliefs")]
    problems: list[str] = []
    session = _object(bundle["session"], "the session")
    changed = off_configuration(runs, run)
    # Atlas's own record of the session, not the runs file's: the model and the actor it was
    # opened with (run.sh opens it as `atlas-researcher`).
    frozen_model = runs.frozen.get("agent_model")
    if frozen_model is not None and session.get("model") != frozen_model:
        changed.append(f"session model {session.get('model')!r}")
    if session.get("actor") != RESEARCHER_ACTOR:
        changed.append(f"session actor {session.get('actor')!r}")
    if changed:
        problems.append(f"another configuration than the frozen one: {', '.join(changed)}")
    if not session.get("isolated"):
        problems.append("the session was not isolated")
    # Amendment 2, Validity: no call outside the isolated tool list (`open_session` included: the
    # runner opened the session, so the agent opening one is a second session).
    outside = sorted(
        {
            str(_object(call, "a tool call")["tool"])
            for call in _list(bundle["tool_calls"], "tool calls")
        }
        - set(ISOLATED_TOOLS)
    )
    if outside:
        problems.append(f"the trace shows tools outside the isolated list: {', '.join(outside)}")
    if bundle.get("window") is None:
        problems.append("no window: the session has no start or end time and the runs file none")
    given = adjudication or {}
    decided = {
        str(k): str(v) for k, v in _object(given.get("belief_marks", {}), "belief_marks").items()
    }
    by_belief: dict[str, dict[str, str]] = {}
    for mark in marks:
        if mark["run"] != run.label:
            continue
        if mark["mark"] not in MARKS:
            raise ScorecardError(f"{run.label}: mark {mark['mark']!r} is one of {', '.join(MARKS)}")
        if mark["belief_id"] not in beliefs:
            raise ScorecardError(f"{run.label}: Belief {mark['belief_id']} is not the session's")
        by_belief.setdefault(str(mark["belief_id"]), {})[str(mark["reviewer"])] = str(mark["mark"])
    final: dict[str, str] = {}
    unresolved: list[str] = []
    for belief in beliefs:
        if belief in decided:
            final[belief] = decided[belief]
            continue
        given_marks = set(by_belief.get(belief, {}).values())
        if len(given_marks) == 1:
            final[belief] = next(iter(given_marks))
        elif len(given_marks) > 1:
            unresolved.append(belief)
    for mark in final.values():
        if mark not in MARKS:
            raise ScorecardError(f"{run.label}: mark {mark!r} is one of {', '.join(MARKS)}")
        if mark == "hit" and not case.positive:
            raise ScorecardError(f"{run.label}: a {case.kind} case has no hit to mark")
        if mark == "false_positive" and case.positive:
            raise ScorecardError(f"{run.label}: only a negative has a false positive")
    reason = cast("str | None", given.get("reason"))
    miss_class = cast("str | None", given.get("miss_class"))
    if miss_class is not None and miss_class not in MISS_CLASSES:
        raise ScorecardError(f"{run.label}: miss_class is one of {', '.join(MISS_CLASSES)}")
    outcome = cast("str | None", given.get("outcome"))
    if outcome is not None and outcome not in OUTCOMES:
        raise ScorecardError(f"{run.label}: outcome is one of {', '.join(OUTCOMES)}")
    if outcome is None and not unresolved:
        outcome = _derived_outcome(case, final)
    return RunOutcome(
        run=run.label,
        case=run.case,
        outcome=outcome,
        belief_marks=final,
        unresolved=tuple(unresolved),
        miss_class=miss_class,
        reason=reason,
        not_scored="; ".join(problems) or None,
    )


def _derived_outcome(case: Case, final: dict[str, str]) -> str:
    if not case.scored:
        return "calibration"
    marks = set(final.values())
    if case.positive:
        return "hit" if "hit" in marks else "miss"
    return "false_positive" if "false_positive" in marks else "clean"


# --- the report --------------------------------------------------------------------------------


def lead_days(case: Case, outcomes: Sequence[RunOutcome]) -> dict[str, Any] | None:
    """The lead time of a positive case: days from the earliest as-of date whose run hit to the
    priced date. None when no scored run hit, or the case has no priced date."""
    if case.priced is None:
        return None
    hits = sorted(
        o.run.split("@", 1)[1]
        for o in outcomes
        if o.case == case.id and o.outcome == "hit" and o.not_scored is None
    )
    if not hits:
        return None
    days = (date.fromisoformat(case.priced) - date.fromisoformat(hits[0])).days
    return {"earliest_hit_as_of": hits[0], "priced": case.priced, "days": days}


def decide_build(outcomes: Sequence[RunOutcome]) -> dict[str, Any]:
    """The pre-registered rule (Amendment 1): the same miss class on two positive cases triggers
    its build; otherwise the most frequent class across the positive runs plus AXT decides, a tie
    going to M1 (else the lowest-numbered of the tied); one miss alone triggers nothing."""
    classified = [
        o
        for o in outcomes
        if o.not_scored is None
        and o.outcome in ("miss", "calibration")
        and o.miss_class in MISS_CLASSES
        and o.miss_class != "FP"
        and (KEY[o.case].positive or o.case == "axt")
    ]
    counts = Counter(o.miss_class for o in classified)
    cases_by_class: dict[str, set[str]] = {}
    for o in classified:
        if KEY[o.case].positive:  # AXT is calibration: it joins only the fallback count
            cases_by_class.setdefault(str(o.miss_class), set()).add(o.case)
    detail = {"runs_by_class": dict(sorted(counts.items()))}
    twice = {c: len(s) for c, s in cases_by_class.items() if len(s) >= 2}
    if twice:
        top = max(twice.values())
        chosen = sorted(c for c, n in twice.items() if n == top)
        return {
            **detail,
            "build": chosen[0],
            "also": chosen[1:],
            "reason": f"{chosen[0]} on {top} positive cases "
            f"({', '.join(sorted(cases_by_class[chosen[0]]))})",
        }
    if sum(counts.values()) == 0:
        return {**detail, "build": None, "reason": "no classified miss"}
    if sum(counts.values()) == 1:
        return {**detail, "build": None, "reason": "one miss alone triggers nothing"}
    top = max(counts.values())
    tied = sorted(c for c, n in counts.items() if n == top and c is not None)
    chosen = "M1" if "M1" in tied else tied[0]
    why = "the most frequent class across the positive runs and AXT"
    if len(tied) > 1:
        why += f", a tie of {', '.join(tied)} going to {chosen}"
    return {**detail, "build": chosen, "reason": why}


def build_report(
    runs: Runs,
    bundles: dict[str, dict[str, Any]],
    marks: Sequence[dict[str, Any]],
    adjudications: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """The structured report (`results.json`): per run the raw hit, closed-book verdict and code
    rank side by side, never combined; the case summaries; the miss classes and the rule."""
    by_run = {str(each["run"]): each for each in adjudications}
    outcomes: list[RunOutcome] = []
    rows: list[dict[str, Any]] = []
    for run in runs.runs:
        case = KEY[run.case]
        outcome = resolve_run(run, runs, bundles[run.label], marks, by_run.get(run.label))
        outcomes.append(outcome)
        flags: list[str] = []
        if outcome.not_scored:
            flags.append(f"not scored: {outcome.not_scored}")
        if run.fact_precision is not None and run.fact_precision < FACT_PRECISION_FLOOR:
            flags.append(
                f"Fact precision {run.fact_precision:.0%} is below {FACT_PRECISION_FLOOR:.0%}"
            )
        if run.trust_gate is not None and run.trust_gate > TRUST_GATE_CEILING:
            flags.append(f"trust gate {run.trust_gate:.0%} is above {TRUST_GATE_CEILING:.0%}")
        if outcome.unresolved:
            flags.append(f"{len(outcome.unresolved)} Belief(s) await the lead's adjudication")
        if outcome.outcome == "miss" and outcome.miss_class is None:
            flags.append("a miss with no class")
        strangers = foreign_citations(bundles[run.label])
        if strangers:
            flags.append(
                f"cites {len(strangers)} Fact(s) the run's own session did not record"
                " (isolation leak or bug)"
            )
        if case.positive and run.closed_book == "stated":
            flags.append("not discriminating: the closed-book model states it")
        others = bundles[run.label].get("other_sessions_in_window")
        if others:
            flags.append(
                f"{len(others)} other session(s) opened during the run's window (the lead"
                f" decides): {', '.join(str(each['id']) for each in others)}"
            )
        denials = bundles[run.label].get("permission_denials")
        if denials is not None and denials["count"]:
            flags.append(f"permission denials: {_denials_text(denials)}")
        trace = trace_summary(bundles[run.label])
        rows.append(
            {
                "run": run.label,
                "case": run.case,
                "kind": case.kind,
                "as_of": run.as_of,
                "session_id": run.session_id,
                "raw": None if outcome.not_scored else outcome.outcome,
                "closed_book": run.closed_book,
                "code_read": run.code_read,
                "code_rank": run.code_rank,
                "code_rank_in_sample": case.in_sample,
                "code_pooled_percentile": run.code_pooled_percentile,
                "miss_class": outcome.miss_class,
                "beliefs": len(_list(bundles[run.label]["beliefs"], "Beliefs")),
                "belief_marks": outcome.belief_marks,
                "tool_calls": trace["calls"],
                "permission_denials": denials,
                "window": bundles[run.label].get("window"),
                "other_sessions_in_window": bundles[run.label].get("other_sessions_in_window"),
                "flags": flags,
            }
        )
    scored = [o for o in outcomes if o.not_scored is None]
    positive = [o for o in scored if KEY[o.case].positive]
    negative = [o for o in scored if KEY[o.case].kind == "negative"]
    summaries: dict[str, Any] = {}
    for case in KEY.values():
        mine = [o for o in scored if o.case == case.id]
        summaries[case.id] = {
            "runs": len(mine),
            "hits": sum(1 for o in mine if o.outcome == "hit"),
            "false_positives": sum(1 for o in mine if o.outcome == "false_positive"),
            "lead": lead_days(case, scored) if case.positive else None,
        }
    return {
        "coverage": coverage(runs),
        "runs": rows,
        "cases": summaries,
        "positive_hits": f"{sum(1 for o in positive if o.outcome == 'hit')} of {len(positive)}",
        "negative_false_positives": (
            f"{sum(1 for o in negative if o.outcome == 'false_positive')} of {len(negative)}"
        ),
        # A false positive of a negative is an FP; a miss is its class (None: unclassified).
        "misses_by_class": dict(
            sorted(
                Counter(
                    "FP" if o.outcome == "false_positive" else str(o.miss_class)
                    for o in scored
                    if o.outcome in ("miss", "false_positive")
                ).items()
            )
        ),
        "decision": decide_build(scored),
        "frozen": runs.frozen,
    }


def render_report(result: dict[str, Any]) -> str:
    """`report.md`: the numbers as they are, with the caveat that seven cases are no hit rate."""
    lines = [
        "# The early-call scorecard",
        "",
        "Seven cases are no hit rate: these are counts of runs, read case by case. The session's"
        " raw hit, the closed-book verdict and the code's rank are side by side and are never"
        " combined into a score. A closed-book `stated` makes a positive case not discriminating"
        " for the session's reading; AXT's and SanDisk's code ranks are in-sample (the code's"
        " vocabulary was written from them); IREN, eToro, Snap, POET and Raspberry Pi are its"
        " clean cases.",
        "",
        "## Per run",
        "",
        "| Run | Session | Raw | Closed book | Code rank (within company) |"
        " Pooled percentile (k=20, 365 days) | Miss class | Beliefs | Calls |"
        " Permission denials | Flags |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in result["runs"]:
        if not row["code_read"]:
            rank = ""
        elif row["code_rank"] is None:
            rank = f"not in top {CODE_TOP}"
        else:
            rank = str(row["code_rank"])
        if rank and row["code_rank_in_sample"]:
            rank += " (in-sample)"
        denials = (
            "" if row["permission_denials"] is None else _denials_text(row["permission_denials"])
        )
        pooled = (
            ""
            if row["code_pooled_percentile"] is None
            else f"{row['code_pooled_percentile']:.0%}"
            + (" (in-sample)" if row["code_rank_in_sample"] else "")
        )
        lines.append(
            f"| {row['run']} | `{row['session_id']}` | {row['raw'] or 'not scored'} |"
            f" {row['closed_book'] or ''} | {rank} | {pooled} | {row['miss_class'] or ''} |"
            f" {row['beliefs']} | {row['tool_calls']} |"
            f" {denials} | {'; '.join(row['flags'])} |"
        )
    lines += [
        "",
        "## Totals",
        "",
        f"- Hits of the positive runs: {result['positive_hits']}",
        f"- False positives of the negative runs: {result['negative_false_positives']}",
        "",
        "## Lead time (as-of date of the earliest hit to the priced date)",
        "",
    ]
    for case_id, summary in result["cases"].items():
        lead = summary["lead"]
        if KEY[case_id].positive:
            text = (
                f"{lead['days']} days (hit as of {lead['earliest_hit_as_of']},"
                f" priced {lead['priced']})"
                if lead
                else "no hit"
            )
            lines.append(f"- {KEY[case_id].name}: {text}")
    during = [row for row in result["runs"] if row["other_sessions_in_window"]]
    lines += [
        "",
        "## Other sessions during a run (the lead decides; not a reason to drop a run alone)",
        "",
    ]
    lines += [
        f"- {row['run']} ({row['window']['start']} to {row['window']['end']}, from"
        f" {row['window']['source']}): {_others_list(row['other_sessions_in_window'])}"
        for row in during
    ] or ["- none"]
    lines += ["", "## Not run or missing", ""]
    gaps = [each for each in result["coverage"] if each["status"] != "run"]
    lines += [
        f"- {g['run']}: {g['status']}" + (f" ({g['reason']})" if "reason" in g else "")
        for g in gaps
    ] or ["- none"]
    decision = result["decision"]
    lines += [
        "",
        "## Misses by class and the rule",
        "",
        *[
            f"- {c}: {n} ({MISS_CLASS_MEANING.get(c, '')})"
            for c, n in result["misses_by_class"].items()
        ],
        "",
        f"The pre-registered rule chooses: **{decision['build'] or 'no build'}**"
        f" ({decision['reason']}).",
        "",
    ]
    return "\n".join(lines)


# --- the command line --------------------------------------------------------------------------


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def command_sheets(arguments: argparse.Namespace) -> int:
    import httpx2  # the reader's only dependency, imported where it is used

    runs = parse_runs(_load(arguments.runs))
    out = Path(arguments.out or REPO / ".scratch" / "live-runs" / f"{_stamp()}-scorecard")
    (out / "bundles").mkdir(parents=True, exist_ok=True)
    (out / "sheets").mkdir(parents=True, exist_ok=True)
    client = httpx2.Client(base_url=arguments.base_url.rstrip("/") + "/api/v1", timeout=120.0)

    def get(path: str, **params: Any) -> Any:
        response = client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    for run in runs.runs:
        bundle = collect_bundle(get, run, Path(arguments.runs).resolve().parent)
        (out / "bundles" / f"{run.label}.json").write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (out / "sheets" / f"{run.label}.md").write_text(review_sheet(run, bundle), encoding="utf-8")
        print(f"{run.label}: {len(bundle['beliefs'])} Beliefs")
    print(f"wrote {out}")
    return 0


def command_report(arguments: argparse.Namespace) -> int:
    runs = parse_runs(_load(arguments.runs))
    if arguments.code_readings:
        runs = apply_code_readings(runs, _load(arguments.code_readings))
    marks_file = _object(_load(arguments.marks), "the marks file")
    bundles = {
        run.label: _object(_load(str(Path(arguments.bundles) / f"{run.label}.json")), run.label)
        for run in runs.runs
    }
    result = build_report(
        runs,
        bundles,
        [_object(each, "a mark") for each in _list(marks_file.get("marks", []), "marks")],
        [
            _object(each, "an adjudication")
            for each in _list(marks_file.get("adjudications", []), "adjudications")
        ],
    )
    out = Path(arguments.out or REPO / ".scratch" / "live-runs" / f"{_stamp()}-scorecard")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "report.md").write_text(render_report(result), encoding="utf-8")
    print(f"wrote {out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)
    sheets = commands.add_parser("sheets", help="read the runs and write the review sheets")
    sheets.add_argument("--runs", required=True)
    sheets.add_argument("--base-url", default="http://localhost:8000")
    sheets.add_argument("--out")
    sheets.set_defaults(handler=command_sheets)
    report = commands.add_parser("report", help="the report, from the bundles and the marks")
    report.add_argument("--runs", required=True)
    report.add_argument("--marks", required=True)
    report.add_argument("--bundles", required=True)
    report.add_argument(
        "--code-readings",
        help="the code's readings by run: rank and pooled percentile (see apply_code_readings)",
    )
    report.add_argument("--out")
    report.set_defaults(handler=command_report)
    arguments = parser.parse_args(argv)
    try:
        return cast("int", arguments.handler(arguments))
    except ScorecardError as error:
        print(f"scorecard: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
