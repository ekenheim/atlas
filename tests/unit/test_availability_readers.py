"""No SQL in `backend/atlas` compares a Source Version's own `available_at` with an as-of
time, a cutoff, a "since" or a bound parameter: every such comparison reads the corrected
availability (`source_version_availability`, migration 0012; `atlas.ledger.availability`).

The check reads every string constant of the package (migrations and the view's own module
excepted). A statement that compares `available_at` with a bound parameter, `as_of`, `cutoff`
or `since` must name the view; otherwise it is on the allow-list below with its reason.
"""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend" / "atlas"
VIEW = "source_version_availability"

COMPARISON = re.compile(
    r"available_at\s*(?:<=|>=|<|>)\s*(?:CAST\(\s*)?(?::\w+|%\(\w+\)s|as_of\b|cutoff\b|since\b)"
    r"|(?::\w+|%\(\w+\)s|\bas_of\b|\bcutoff\b|\bsince\b)(?:\s+AS\s+\w+\))?\s*(?:<=|>=|<|>)\s*\w+\.available_at",
    re.IGNORECASE,
)

# (path under backend/atlas, the comparison's text) -> why the raw column is right there.
ALLOWED: dict[tuple[str, str], str] = {}


def _statements(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    prose = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
    }  # docstrings are prose, not SQL
    for node in ast.walk(tree):
        if id(node) in prose:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            parts = [v.value if isinstance(v, ast.Constant) else " ? " for v in node.values]
            found.append((node.lineno, "".join(str(p) for p in parts)))
    return found


def raw_comparisons() -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for path in sorted(BACKEND.rglob("*.py")):
        relative = path.relative_to(BACKEND).as_posix()
        if relative.startswith("db/migrations/") or relative == "ledger/availability.py":
            continue
        for line, statement in _statements(ast.parse(path.read_text(encoding="utf-8"))):
            if VIEW in statement:
                continue
            for match in COMPARISON.finditer(statement):
                if (relative, match.group(0)) not in ALLOWED:
                    hits.append((relative, line, match.group(0)))
    return hits


def test_every_as_of_comparison_of_a_source_version_s_availability_reads_the_corrected_view() -> (
    None
):
    assert raw_comparisons() == []


def test_the_check_finds_a_raw_comparison() -> None:
    sample = "SELECT 1 FROM source_version v WHERE v.available_at <= :as_of"
    assert COMPARISON.search(sample)
    assert COMPARISON.search("WHERE :cutoff >= v.available_at")
    assert not COMPARISON.search("ORDER BY v.available_at DESC")


def test_every_allow_list_entry_has_a_reason() -> None:
    assert all(reason.strip() for reason in ALLOWED.values())
