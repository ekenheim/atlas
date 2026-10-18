"""The bear checks' typed answer (Chokepoint Watch ticket W8): a reason exactly when a check is
unknown, and a plain sentence for every reason of every key."""

import re
from typing import get_args

import pytest
from pydantic import ValidationError

from atlas.bear_checks.models import (
    CHECK_KEYS,
    CheckKey,
    DilutionCheck,
    NetCashCheck,
    UnknownReason,
    unknown_summary,
)


@pytest.mark.parametrize("key", CHECK_KEYS)
@pytest.mark.parametrize("reason", get_args(UnknownReason.__value__))
def test_every_reason_of_every_key_has_a_plain_sentence(key: CheckKey, reason: UnknownReason):
    sentence = unknown_summary(key, reason)

    assert sentence.startswith("Not known: ") and sentence.endswith(".")
    assert not re.search(r"[a-z]+_[a-z]+", sentence)  # no code leaks into the words


def test_an_unknown_check_needs_its_reason_and_no_other_has_one():
    with pytest.raises(ValidationError):
        DilutionCheck(
            key="dilution",
            status="unknown",
            unknown_reason=None,
            summary="Not known: x.",
            value=None,
            basis="",
            sources=[],
        )
    with pytest.raises(ValidationError):
        NetCashCheck(
            key="net_cash",
            status="clear",
            unknown_reason="no_xbrl",
            summary="x.",
            value=None,
            basis="",
            sources=[],
        )


def test_not_known_builds_the_unknown_check_with_its_sentence():
    check = NetCashCheck.not_known("stale_figure", "the balance sheet is old")

    assert (check.key, check.status, check.unknown_reason) == (
        "net_cash",
        "unknown",
        "stale_figure",
    )
    assert check.summary == (
        "Not known: the latest balance sheet with cash is more than 15 months old."
    )
    assert (check.value, check.sources) == (None, [])
