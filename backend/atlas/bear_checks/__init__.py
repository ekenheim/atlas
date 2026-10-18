"""Mechanical bear checks (Chokepoint Watch ticket W4): dilution, shelf or ATM filings, GAAP
gross margin, customer concentration, going-concern language and net cash, deterministic and
sourced, as of a time. `models` the answer, `xbrl` the checks that read XBRL, `patterns` the
sentence patterns, `service` the checks over the ledger and the archive."""

from atlas.bear_checks.models import (
    CHECK_KEYS,
    BearCheck,
    BearChecks,
    BearCheckSource,
    CheckKey,
    CheckStatus,
    UnknownReason,
)
from atlas.bear_checks.service import UnknownCompany, bear_checks

__all__ = [
    "CHECK_KEYS",
    "BearCheck",
    "BearCheckSource",
    "BearChecks",
    "CheckKey",
    "CheckStatus",
    "UnknownCompany",
    "UnknownReason",
    "bear_checks",
]
