"""SimHash near-duplicate detection for Evidence Families (spec Phase 3; ticket 11).

Expected values come from the documented rule `simhash64-w3-blake2b-v1` (the docstring of
`atlas.ledger.families`) and from the syndication fixtures, never from the implementation.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from atlas.ledger.families import SIMHASH_RULE, hamming_distance, simhash, simhash_hex
from atlas.parsing import ParsedText, parse
from tests.harness import REPO

SYNDICATION = REPO / "tests" / "fixtures" / "syndication" / "lumentum" / "www.sec.gov"
FILINGS = SYNDICATION / "Archives" / "edgar" / "data" / "1633978"
ORIGINAL = FILINGS / "000162828026055726" / "lite_ex991xq4fy26.htm"
WIRE_COPY = FILINGS / "000162828026900002" / "lite_ex991xq4fy26wire.htm"
TEN_Q = FILINGS / "000162828026030777" / "lite-20260328.htm"
THRESHOLD = 3  # spec Phase 3: Hamming ≤ 3


def parsed(path: Path) -> str:
    result = parse(path.read_bytes(), "text/html")
    assert isinstance(result, ParsedText)
    return result.text


def feature_hash(feature: str) -> int:
    return int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")


def test_the_rule_is_named() -> None:
    assert SIMHASH_RULE == "simhash64-w3-blake2b-v1"


def test_a_single_feature_text_has_that_features_blake2b_hash() -> None:
    # Two tokens: one feature, "hello world", so every bit is that feature's bit.
    assert simhash("Hello, world!") == feature_hash("hello world")
    assert simhash_hex(simhash("Hello, world!")) == f"{feature_hash('hello world'):016x}"


def test_three_shingles_are_weighted_by_occurrence() -> None:
    # "a b c a b c" has features "a b c" (twice), "b c a", "c a b": "a b c" outweighs
    # either other one alone, so where the other two agree against it they win (2 vs 2 is
    # a tie, which is 0).
    abc, bca, cab = feature_hash("a b c"), feature_hash("b c a"), feature_hash("c a b")
    expected = 0
    for bit in range(64):
        total = sum(
            weight if value >> bit & 1 else -weight
            for value, weight in ((abc, 2), (bca, 1), (cab, 1))
        )
        expected |= (total > 0) << bit
    assert simhash("a b c a b c") == expected


def test_case_punctuation_whitespace_and_compatibility_forms_are_normalized() -> None:
    reference = simhash("lumentum announces fiscal 2026 results")
    for variant in (
        "LUMENTUM ANNOUNCES FISCAL 2026 RESULTS",
        "Lumentum  announces\nfiscal\t2026 — results.",
        "Lumentum, announces: “ﬁscal” 2026 results!",  # the fi ligature is NFKC "fi"
        "Lumentum announces fiscal \uff12\uff10\uff12\uff16 results",  # fullwidth digits
        "lumentum_announces fiscal 2026 results",  # the underscore separates tokens
    ):
        assert simhash(variant) == reference, variant


def test_an_empty_text_has_fingerprint_zero() -> None:
    assert simhash("") == 0
    assert simhash(" ... — !") == 0


def test_the_fingerprint_is_the_same_in_every_process() -> None:
    text = parsed(ORIGINAL)
    program = (
        "import sys; from atlas.ledger.families import simhash, simhash_hex;"
        " print(simhash_hex(simhash(sys.stdin.read())))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", program],
            input=text,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("0", "1", "12345")
    }
    assert outputs == {simhash_hex(simhash(text))}


def test_hamming_distance_counts_differing_bits_of_64() -> None:
    assert hamming_distance(0, 0) == 0
    assert hamming_distance(0b1011, 0b0001) == 2
    assert hamming_distance(0, (1 << 64) - 1) == 64
    assert hamming_distance(-1, (1 << 64) - 1) == 0  # a signed bigint is the same 64 bits


def test_a_syndicated_copy_is_a_near_duplicate_and_an_unrelated_filing_is_not() -> None:
    original, wire_copy, ten_q = parsed(ORIGINAL), parsed(WIRE_COPY), parsed(TEN_Q)
    assert original != wire_copy  # different parses, so not an exact duplicate

    assert 0 < hamming_distance(simhash(original), simhash(wire_copy)) <= THRESHOLD
    assert hamming_distance(simhash(original), simhash(ten_q)) > THRESHOLD
    assert hamming_distance(simhash(wire_copy), simhash(ten_q)) > THRESHOLD


def test_a_small_edit_to_a_long_text_stays_within_the_threshold() -> None:
    original = parsed(ORIGINAL)
    edited = original.replace("Lumentum", "Lumentum Holdings", 1) + "\nReprinted by permission."
    assert hamming_distance(simhash(original), simhash(edited)) <= THRESHOLD
