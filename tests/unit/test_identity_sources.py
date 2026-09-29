"""The identity sources at their transport boundary: SEC's ticker file and submissions, GLEIF
and OpenFIGI (keyless), each with its rate limit.

The fake (`tests/fakes/identity.py`) answers from hand-written fixtures built from the identity
research's trimmed live responses (`tests/fixtures/identity/manifest.json`); expected values
below are the research's, not recomputed.
"""

from datetime import date

import pytest

from atlas.identity.gleif import GLEIF_RATE_LIMITER, GleifClient
from atlas.identity.http import IdentitySourceError
from atlas.identity.openfigi import (
    MAX_JOBS_PER_REQUEST,
    OPENFIGI_RATE_LIMITER,
    MappingJob,
    OpenFigiClient,
)
from atlas.identity.sec import SecIdentityClient
from atlas.sources.sec_http import SEC_RATE_LIMITER, TokenBucket
from tests.fakes.identity import FakeIdentitySources

UA = "Atlas Research ops@example.com"


class Sleeps(list[float]):
    def __call__(self, seconds: float) -> None:
        self.append(seconds)


def still_clock() -> float:
    return 0.0


def bucket(limiter: TokenBucket) -> TokenBucket:
    """A fresh bucket at the same rate as `limiter`, on a clock that never moves."""
    return TokenBucket(1 / limiter._interval, clock=still_clock)  # pyright: ignore[reportPrivateUsage]


def sec(fake: FakeIdentitySources, sleeps: Sleeps | None = None) -> SecIdentityClient:
    return SecIdentityClient(
        UA,
        transport=fake.transport,
        limiter=bucket(SEC_RATE_LIMITER),
        sleep=sleeps if sleeps is not None else Sleeps(),
    )


def gleif(fake: FakeIdentitySources, sleeps: Sleeps | None = None) -> GleifClient:
    return GleifClient(
        transport=fake.transport,
        limiter=bucket(GLEIF_RATE_LIMITER),
        sleep=sleeps if sleeps is not None else Sleeps(),
    )


def openfigi(fake: FakeIdentitySources, sleeps: Sleeps | None = None) -> OpenFigiClient:
    return OpenFigiClient(
        transport=fake.transport,
        limiter=bucket(OPENFIGI_RATE_LIMITER),
        sleep=sleeps if sleeps is not None else Sleeps(),
    )


# --- SEC ---


def test_sec_ticker_file_maps_tickers_to_ciks_with_a_coarse_exchange() -> None:
    fake = FakeIdentitySources()
    client = sec(fake)

    [lite] = client.by_ticker("LITE")
    [tsm] = client.by_ticker("tsm")
    [aircastle] = client.by_ticker("AYR")

    assert (lite.cik, lite.name, lite.exchange) == (
        "0001633978",
        "Lumentum Holdings Inc.",
        "Nasdaq",
    )
    # An ADR is filed under the foreign issuer's own CIK; nothing marks it as an ADR.
    assert (tsm.cik, tsm.exchange) == ("0001046179", "NYSE")
    assert aircastle.exchange is None
    # Class suffixes are one canonical form: SEC's `-` (OpenFIGI's `/`, feeds' `.`).
    assert [r.cik for r in client.by_ticker("BRK/B")] == ["0001067983"]
    assert [r.cik for r in client.by_ticker("BRK.A")] == ["0001067983"]
    # The file is read once per client, with the declared User-Agent.
    assert fake.paths() == ["/files/company_tickers_exchange.json"]
    assert fake.calls[0].url.host == "www.sec.gov"
    assert fake.calls[0].headers["User-Agent"] == UA


def test_sec_name_lookup_is_equality_after_normalisation() -> None:
    client = sec(FakeIdentitySources())

    assert [r.cik for r in client.by_name("COHERENT CORP")] == ["0000820318"]
    assert [r.cik for r in client.by_name("Coherent Corp.")] == ["0000820318"]
    assert client.by_name("Coherent Holdings") == []
    assert client.by_name("Lumentum") == []  # never a similarity match


def test_sec_submissions_give_former_names_state_and_the_null_lei() -> None:
    fake = FakeIdentitySources()

    coherent = sec(fake).submissions("0000820318")

    assert coherent is not None
    assert fake.calls[0].url.host == "data.sec.gov"
    assert (coherent.name, coherent.state_of_incorporation, coherent.lei) == (
        "COHERENT CORP.",
        "PA",
        None,
    )
    assert coherent.tickers == ("COHR",)
    assert coherent.exchanges == ("NYSE",)
    [former] = coherent.former_names
    assert (former.name, former.valid_from, former.valid_to) == (
        "II-VI INC",
        date(1995, 10, 4),
        date(2022, 9, 1),
    )
    assert not coherent.adr_shell


def test_an_unsponsored_adr_cik_is_a_shell() -> None:
    soitec_adr = sec(FakeIdentitySources()).submissions("0001445214")

    assert soitec_adr is not None
    assert soitec_adr.adr_shell


def test_an_unknown_cik_is_none() -> None:
    fake = FakeIdentitySources(missing_submissions={"CIK0000000001.json"})

    assert sec(fake).submissions("0000000001") is None


def test_sec_requests_share_the_ten_per_second_limit() -> None:
    sleeps = Sleeps()
    client = sec(FakeIdentitySources(), sleeps)

    client.submissions("0000820318")
    client.submissions("0001633978")
    client.submissions("0001046179")

    assert sleeps == pytest.approx([0.1, 0.2])


# --- GLEIF ---


def test_gleif_record_keeps_a_lapsed_lei_and_its_former_name() -> None:
    fake = FakeIdentitySources()

    coherent = gleif(fake).record("549300O5C25A0MMHHU33")

    assert coherent is not None
    assert (coherent.legal_name, coherent.jurisdiction, coherent.registration_status) == (
        "Coherent Corp.",
        "US-PA",
        "LAPSED",
    )
    assert coherent.other_names == ("II-VI Incorporated",)
    assert fake.calls[0].url.host == "api.gleif.org"
    assert fake.calls[0].url.path == "/api/v1/lei-records/549300O5C25A0MMHHU33"


def test_gleif_isin_lookup_gives_an_adrs_underlying_issuer() -> None:
    fake = FakeIdentitySources()

    [issuer] = gleif(fake).by_isin("US8740391003")

    assert issuer.lei == "549300KB6NK5SBD14S87"
    assert issuer.jurisdiction == "TW"
    assert issuer.other_names == ("Taiwan Semiconductor Manufacturing Company Limited",)
    assert fake.calls[0].url.params["filter[isin]"] == "US8740391003"


def test_gleif_full_text_returns_parent_and_subsidiaries() -> None:
    records = gleif(FakeIdentitySources()).fulltext("Lumentum")

    assert [r.legal_name for r in records] == [
        "LUMENTUM HOLDINGS INC.",
        "Lumentum Operations LLC",
        "LUMENTUM TECHNOLOGY UK LIMITED",
    ]


def test_gleif_exact_legal_name_filter() -> None:
    fake = FakeIdentitySources()

    [coherent] = gleif(fake).by_legal_name("COHERENT CORP.")

    assert coherent.lei == "549300O5C25A0MMHHU33"
    assert fake.calls[0].url.params["filter[entity.legalName]"] == "COHERENT CORP."


def test_gleif_unknown_lei_is_none() -> None:
    assert gleif(FakeIdentitySources()).record("5493000SYNTHETIC0036") is None


def test_gleif_keeps_to_sixty_requests_a_minute() -> None:
    sleeps = Sleeps()
    client = gleif(FakeIdentitySources(), sleeps)

    for _ in range(3):
        client.record("549300JLWRRC38DWEF52")

    assert sleeps == pytest.approx([1.0, 2.0])


# --- OpenFIGI ---


def test_openfigi_matches_the_segment_mic_not_the_operating_mic() -> None:
    xnas, xngs = openfigi(FakeIdentitySources()).map(
        [
            MappingJob("TICKER", "LITE", mic_code="XNAS"),
            MappingJob("TICKER", "LITE", mic_code="XNGS"),
        ]
    )

    assert xnas.figis == ()
    assert xnas.warning == "No identifier found."
    [venue] = xngs.figis
    assert (venue.figi, venue.exch_code, venue.composite_figi) == (
        "BBG0073F9SD2",
        "UW",
        "BBG0073F9RT7",
    )


def test_openfigi_composite_and_adr_rows() -> None:
    lite, tsm = openfigi(FakeIdentitySources()).map(
        [MappingJob("TICKER", "LITE", exch_code="US"), MappingJob("TICKER", "TSM", exch_code="US")]
    )

    [composite] = lite.figis
    assert (composite.figi, composite.composite_figi, composite.share_class_figi) == (
        "BBG0073F9RT7",
        "BBG0073F9RT7",
        "BBG0073F9RS8",
    )
    [adr] = tsm.figis
    assert adr.depositary_receipt
    assert (adr.security_type2, adr.name) == ("Depositary Receipt", "TAIWAN SEMICONDUCTOR-SP ADR")


def test_openfigi_tickers_travel_with_its_class_separator() -> None:
    fake = FakeIdentitySources()

    [brk] = openfigi(fake).map([MappingJob("TICKER", "BRK-B", exch_code="US")])

    assert fake.openfigi_batches == [[{"idType": "TICKER", "idValue": "BRK/B", "exchCode": "US"}]]
    assert brk.figis[0].ticker == "BRK-B"


def test_openfigi_error_and_warning_shapes() -> None:
    cik, isin, iivi = openfigi(FakeIdentitySources()).map(
        [
            MappingJob("CIK", "1633978"),
            MappingJob("ID_ISIN", "US0000000000"),
            MappingJob("TICKER", "IIVI", exch_code="US"),  # no ticker history
        ]
    )

    assert cik.error == "Invalid value for idType."
    assert isin.error == "Invalid idValue format."
    assert (iivi.figis, iivi.warning) == ((), "No identifier found.")


def test_openfigi_sends_at_most_ten_jobs_per_request() -> None:
    fake = FakeIdentitySources()
    jobs = [MappingJob("TICKER", "LITE", exch_code="US")] * 12

    results = openfigi(fake).map(jobs)

    assert MAX_JOBS_PER_REQUEST == 10
    assert [len(batch) for batch in fake.openfigi_batches] == [10, 2]
    assert len(results) == 12
    assert all(r.figis[0].figi == "BBG0073F9RT7" for r in results)


def test_openfigi_keeps_to_twenty_five_requests_a_minute() -> None:
    sleeps = Sleeps()
    client = openfigi(FakeIdentitySources(), sleeps)

    for _ in range(3):
        client.map([MappingJob("TICKER", "LITE", exch_code="US")])

    assert sleeps == pytest.approx([2.4, 4.8])


def test_openfigi_429_waits_for_the_ratelimit_reset() -> None:
    fake = FakeIdentitySources()
    fake.rate_limit_openfigi(times=1, reset_s=7)
    sleeps = Sleeps()

    [lite] = openfigi(fake, sleeps).map([MappingJob("TICKER", "LITE", exch_code="US")])

    assert lite.figis[0].figi == "BBG0073F9RT7"
    assert 7.0 in sleeps
    assert len(fake.calls) == 2


def test_openfigi_persistent_429_fails_clearly() -> None:
    fake = FakeIdentitySources()
    fake.rate_limit_openfigi(times=10, reset_s=1)

    with pytest.raises(IdentitySourceError, match=r"OpenFIGI: .*gave up after 4 attempts"):
        openfigi(fake).map([MappingJob("TICKER", "LITE", exch_code="US")])


def test_a_job_takes_exch_code_or_mic_code_not_both() -> None:
    with pytest.raises(ValueError, match="not both"):
        MappingJob("TICKER", "LITE", exch_code="US", mic_code="XNGS")
